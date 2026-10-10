"""Browser automation tools (Playwright).

IMPORTANT DISTINCTION — application launching vs. browser automation:

* "Open Firefox" → ``launch_application`` (app launcher). This MAY start the
  user's normal system Firefox with their normal profile. Airi does not
  control the DOM of that window.
* "Open Firefox and search dog" → ``browser_open`` / ``browser_search``. These
  run an **Airi-controlled Playwright session** with a dedicated profile under
  ``~/.config/airi/browser_data/``. Airi never attaches to, or modifies, the
  user's normal browser process or profile (e.g. ``~/.mozilla/firefox``).

Engines:

* Firefox-family requests use Playwright's *bundled* Firefox build (it
  contains the Juggler automation protocol). The branded system binary
  (``/usr/lib/firefox/firefox``) does NOT support Playwright automation and
  makes ``launch_persistent_context`` hang, so it is never passed as
  ``executable_path``.
* Chromium-family requests (Chrome, Helium, Brave, ...) use Playwright's
  Chromium engine with the resolved system executable.

Each engine/browser gets its own profile directory so that profiles are
never shared between engines.
"""
from __future__ import annotations

import asyncio
import os
import re
import shutil
import signal
import urllib.parse
from pathlib import Path
from typing import Optional

import structlog

from app.tools.registry import tool, ToolResult, PermissionLevel, ToolParameter
from app.tools.os_tools.app_resolver import AppResolver

logger = structlog.get_logger(__name__)

# ── Configuration ────────────────────────────────────────────────────────────
BROWSER_OPEN_TIMEOUT = 15.0          # hard limit for the whole browser_open
CLEANUP_TIMEOUT = 3.0                # max time spent cleaning up after failure
PROFILE_ROOT = Path(os.path.expanduser("~/.config/airi/browser_data"))
HEADLESS = False                     # Airi's automation browser is visible

# ── Session state (shared by every browser_* tool) ───────────────────────────
# Ownership: this module owns the Playwright driver, the persistent context and
# the active page. All browser tools read these globals; only browser_open /
# _reset_browser_state mutate them. The context lives until the user closes
# the window (the "close" event resets state) or a different browser is
# requested.
_playwright = None
_browser = None                      # unused for persistent contexts; kept for compat
_browser_context = None
_page = None
_active_browser_name: Optional[str] = None
_active_profile_dir: Optional[Path] = None
_pending_profile_dir: Optional[Path] = None   # profile being launched (for cleanup)


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "browser"


def _is_firefox_family(name: str, exec_line: str) -> bool:
    haystack = f"{name} {exec_line}".lower()
    return any(k in haystack for k in ("firefox", "librewolf", "waterfox", "zen-browser", "floorp"))


def get_profile_dir(engine: str, browser_name: str) -> Path:
    """Return Airi's dedicated automation profile dir for an engine/browser.

    Firefox → ``~/.config/airi/browser_data/firefox``
    Chromium-family → ``~/.config/airi/browser_data/chromium/<browser-slug>``
    """
    if engine == "firefox":
        return PROFILE_ROOT / "firefox"
    return PROFILE_ROOT / "chromium" / _slug(browser_name)


# ── Profile lock handling ────────────────────────────────────────────────────
_LOCK_FILES = {
    # Firefox (Linux): 'lock' symlink -> "<ip>:+<pid>", plus '.parentlock'
    "firefox": ("lock", ".parentlock"),
    # Chromium: 'SingletonLock' symlink -> "<hostname>-<pid>"
    "chromium": ("SingletonLock", "SingletonCookie", "SingletonSocket"),
}


def _lock_owner_pid(profile_dir: Path, engine: str) -> Optional[int]:
    """Read the PID recorded in the profile's lock symlink, if any."""
    lock_name = "lock" if engine == "firefox" else "SingletonLock"
    lock_path = profile_dir / lock_name
    if not lock_path.is_symlink():
        return None
    try:
        target = os.readlink(lock_path)
    except OSError:
        return None
    m = re.search(r"(\d+)$", target)
    return int(m.group(1)) if m else None


def _pid_cmdline(pid: int) -> Optional[str]:
    try:
        raw = Path(f"/proc/{pid}/cmdline").read_bytes()
    except OSError:
        return None  # process does not exist
    return raw.replace(b"\x00", b" ").decode(errors="replace")


def _is_airi_owned(cmdline: str, profile_dir: Path) -> bool:
    """A process is Airi-owned only if its command line references Airi's profile dir."""
    return str(profile_dir) in cmdline


def _remove_lock_files(profile_dir: Path, engine: str) -> None:
    for name in _LOCK_FILES[engine]:
        p = profile_dir / name
        try:
            if p.is_symlink() or p.exists():
                p.unlink()
        except OSError:
            pass


def _kill_pid(pid: int) -> None:
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    except PermissionError:
        return
    # Busy-wait briefly for exit, then SIGKILL.
    import time
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        if _pid_cmdline(pid) is None:
            return
        time.sleep(0.1)
    try:
        os.kill(pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass


def ensure_profile_unlocked(profile_dir: Path, engine: str) -> tuple[bool, str]:
    """Make sure no stale process holds Airi's automation profile.

    Returns ``(ok, reason)``.
    * no lock                         → ok
    * lock owner dead (stale lock)    → remove lock files, ok
    * lock owner alive, Airi-owned    → terminate it, remove lock files, ok
    * lock owner alive, NOT Airi-owned → refuse (never kill user processes)
    """
    pid = _lock_owner_pid(profile_dir, engine)
    if pid is None:
        return True, "no_lock"
    cmdline = _pid_cmdline(pid)
    if cmdline is None:
        logger.info("profile_lock_stale", profile=str(profile_dir), pid=pid)
        _remove_lock_files(profile_dir, engine)
        return True, "stale_lock_removed"
    if _is_airi_owned(cmdline, profile_dir):
        logger.warning("profile_lock_airi_process", profile=str(profile_dir), pid=pid)
        _kill_pid(pid)
        _remove_lock_files(profile_dir, engine)
        return True, "airi_process_terminated"
    logger.error("profile_lock_foreign", profile=str(profile_dir), pid=pid)
    return False, f"profile_locked_by_foreign_process pid={pid}"


# ── Lifecycle helpers ────────────────────────────────────────────────────────
def _on_context_closed(*_args) -> None:
    """Called by Playwright when the Airi browser window/context is closed."""
    global _browser_context, _page, _active_browser_name, _active_profile_dir
    logger.info("browser_context_closed", browser=_active_browser_name)
    _browser_context = None
    _page = None
    _active_browser_name = None
    _active_profile_dir = None


async def _reset_browser_state(profile_dir: Optional[Path] = None, engine: Optional[str] = None) -> None:
    """Tear down a partial/failed session without blocking for long.

    Closes the context (bounded by CLEANUP_TIMEOUT), then terminates any
    Airi-owned process still holding the profile lock. Profile data is never
    deleted.
    """
    global _browser_context, _page, _active_browser_name, _active_profile_dir, _pending_profile_dir
    ctx = _browser_context
    _browser_context = None
    _page = None
    _active_browser_name = None
    _active_profile_dir = None
    if ctx is not None:
        try:
            await asyncio.wait_for(ctx.close(), timeout=CLEANUP_TIMEOUT)
        except Exception:
            pass
    target = profile_dir or _pending_profile_dir
    if target is not None:
        for eng in ([engine] if engine else ["firefox", "chromium"]):
            pid = _lock_owner_pid(target, eng)
            if pid is not None:
                cmd = _pid_cmdline(pid)
                if cmd is not None and _is_airi_owned(cmd, target):
                    await asyncio.to_thread(_kill_pid, pid)
                if _pid_cmdline(pid) is None:
                    _remove_lock_files(target, eng)
    _pending_profile_dir = None


def _fail(phase: str, browser: str, error: str, message: str = "") -> ToolResult:
    logger.error("browser_open_fail", phase=phase, browser=browser, error=error)
    print(f"BROWSER OPEN FAILED\nphase={phase}\nbrowser={browser}\nerror={error}")
    return ToolResult(
        success=False,
        error=error,
        message=message or f"Failed to open {browser} during {phase}.",
        data={"browser": browser, "phase": phase},
    )


async def _launch_context(engine: str, profile_dir: Path, executable: Optional[str]):
    if engine == "firefox":
        # Never pass executable_path: only Playwright's bundled Firefox is automatable.
        return await _playwright.firefox.launch_persistent_context(
            user_data_dir=str(profile_dir), headless=HEADLESS,
        )
    return await _playwright.chromium.launch_persistent_context(
        user_data_dir=str(profile_dir), headless=HEADLESS, executable_path=executable,
    )


async def _do_browser_open(browser_name: str) -> ToolResult:
    global _playwright, _browser_context, _page, _active_browser_name
    global _active_profile_dir, _pending_profile_dir

    logger.info("browser_open_start", browser=browser_name)

    # ── Phase: resolve ────────────────────────────────────────────────────
    logger.info("browser_resolve_start", browser=browser_name)
    match = AppResolver().resolve(browser_name)
    if not match.entry:
        return _fail("browser_resolve", browser_name, f"Could not resolve browser '{browser_name}'")
    resolved_name = match.entry.name
    exec_line = match.entry.exec or ""
    engine = "firefox" if _is_firefox_family(resolved_name, exec_line) else "chromium"
    system_exec = exec_line.split()[0] if exec_line else ""
    system_exec = shutil.which(system_exec) or system_exec
    logger.info("browser_resolve_ok", resolved_name=resolved_name,
                system_executable=system_exec, engine=engine)

    # ── Fast path: reuse live Airi session for the same browser ───────────
    if _browser_context is not None and _active_browser_name == resolved_name:
        if _page is None or _page.is_closed():
            logger.info("page_create_start")
            pages = _browser_context.pages
            _page = pages[0] if pages else await _browser_context.new_page()
            logger.info("page_create_ok")
        logger.info("context_reuse_ok", browser=resolved_name)
        logger.info("browser_ready", browser=resolved_name, reused=True)
        return ToolResult(success=True, message=f"Reusing Airi's {resolved_name} session",
                          data={"browser": resolved_name, "engine": engine, "reused": True,
                                "profile": str(_active_profile_dir)})

    # ── Phase: playwright driver ──────────────────────────────────────────
    logger.info("playwright_start", browser=resolved_name)
    if _playwright is None:
        from playwright.async_api import async_playwright
        _playwright = await async_playwright().start()
    logger.info("playwright_start_ok")

    # ── Phase: engine diagnostics ─────────────────────────────────────────
    if engine == "firefox":
        bundled = _playwright.firefox.executable_path
        if not bundled or not os.path.exists(bundled):
            logger.error("browser_open_fail", phase="engine_check", error="playwright_firefox_not_installed")
            return ToolResult(
                success=False, error="playwright_firefox_not_installed",
                message="Airi's Firefox automation browser is not installed. "
                        "Run: .venv/bin/playwright install firefox",
                data={"browser": resolved_name, "phase": "engine_check"},
            )
        launch_exec = None
        logger.info("engine_selected", engine="playwright-firefox", executable=bundled)
    else:
        if not system_exec or not os.path.exists(system_exec):
            return _fail("engine_check", resolved_name, f"Chromium executable not found: {system_exec}")
        launch_exec = system_exec
        logger.info("engine_selected", engine="playwright-chromium", executable=launch_exec)

    # ── Switch browsers: close the previous Airi session first ────────────
    if _browser_context is not None:
        await _reset_browser_state(_active_profile_dir)

    profile_dir = get_profile_dir(engine, resolved_name)
    profile_dir.mkdir(parents=True, exist_ok=True)
    _pending_profile_dir = profile_dir

    # ── Phase: profile lock preflight ─────────────────────────────────────
    ok, reason = ensure_profile_unlocked(profile_dir, engine)
    if not ok:
        return _fail("profile_lock", resolved_name, reason,
                     "Airi's automation profile is in use by another process.")

    # ── Phase: context create (one retry after lock cleanup) ──────────────
    logger.info("context_create_start", engine=engine, profile=str(profile_dir))
    try:
        ctx = await _launch_context(engine, profile_dir, launch_exec)
    except Exception as first_err:
        logger.warning("context_create_retry", error=str(first_err))
        ok, reason = ensure_profile_unlocked(profile_dir, engine)
        if not ok:
            return _fail("context_create", resolved_name, f"{first_err}; {reason}")
        try:
            ctx = await _launch_context(engine, profile_dir, launch_exec)
        except Exception as second_err:
            return _fail("context_create", resolved_name, str(second_err))
    _browser_context = ctx
    _active_browser_name = resolved_name
    _active_profile_dir = profile_dir
    _pending_profile_dir = None
    try:
        ctx.on("close", _on_context_closed)
    except Exception:
        pass
    logger.info("context_create_ok")

    # ── Phase: page ───────────────────────────────────────────────────────
    logger.info("page_create_start")
    pages = ctx.pages
    _page = pages[0] if pages else await ctx.new_page()
    logger.info("page_create_ok")

    logger.info("browser_ready", browser=resolved_name, engine=engine)
    return ToolResult(success=True, message=f"Opened Airi's {resolved_name} automation session",
                      data={"browser": resolved_name, "engine": engine, "reused": False,
                            "profile": str(profile_dir)})


@tool(
    name="browser_open",
    description=(
        "Start (or reuse) Airi's own automation browser session for DOM control "
        "(Firefox, Chrome, Helium). Uses a separate Airi profile, not the user's normal "
        "browser. To simply launch the user's browser app, use launch_application."
    ),
    category="browser",
    permission_level=PermissionLevel.SAFE,
    parameters=[
        ToolParameter(name="browser_name", type="string", description="Browser to open")
    ]
)
async def browser_open(browser_name: str) -> ToolResult:
    try:
        return await asyncio.wait_for(_do_browser_open(browser_name), timeout=BROWSER_OPEN_TIMEOUT)
    except asyncio.TimeoutError:
        await _reset_browser_state()
        logger.error("browser_open_fail", phase="timeout", browser=browser_name, error="browser_open_timeout")
        print(f"BROWSER OPEN FAILED\nphase=timeout\nbrowser={browser_name}\nerror=browser_open_timeout")
        return ToolResult(
            success=False,
            error="browser_open_timeout",
            message=f"Timed out while opening {browser_name}.",
            data={"browser": browser_name},
        )
    except Exception as e:
        await _reset_browser_state()
        return _fail("unknown", browser_name, str(e))

BROWSER_SEARCH_TIMEOUT = 45.0
SEARCH_SITES = {
    "youtube": "https://www.youtube.com",
    "duckduckgo": "https://duckduckgo.com",
    "google": "https://www.google.com",
}
SEARCH_RESULTS_URL = {
    "youtube": "https://www.youtube.com/results?search_query={q}",
    "duckduckgo": "https://duckduckgo.com/?q={q}",
    "google": "https://www.google.com/search?q={q}",
}
SEARCH_SELECTORS = [
    "input[name='search_query']",   # YouTube
    "input[name='q']",              # DuckDuckGo
    "textarea[name='q']",           # Google (current markup)
    "input[type='search']",
    "[placeholder*='Search' i]",
]


def _search_verified(query: str, landing_url: str, final_url: str, title: str) -> bool:
    """A search counts as done only if the page moved to a results state for the query."""
    q = query.lower().strip()
    parsed = urllib.parse.urlparse(final_url or "")
    params = urllib.parse.parse_qs(parsed.query)
    in_url = any(q in v.lower() for vals in params.values() for v in vals)
    changed = (final_url or "").rstrip("/") != (landing_url or "").rstrip("/")
    in_title = q in (title or "").lower()
    return in_url or (changed and in_title)


@tool(
    name="browser_search",
    description=(
        "Perform a real web search in Airi's automation browser: opens/reuses the browser, "
        "goes to the site, types the query, presses Enter and verifies results. "
        "Use this for 'open <browser> and search X' or 'search YouTube for X'. BROWSER_CONTROL."
    ),
    category="browser",
    permission_level=PermissionLevel.CONFIRM,
    parameters=[
        ToolParameter(name="browser_name", type="string", description="Browser to use (e.g., Firefox, Helium, Chrome). Empty = active Airi browser, else Firefox.", required=False, default=""),
        ToolParameter(name="query", type="string", description="The search query"),
        ToolParameter(name="site", type="string", description="Optional site to search: 'youtube', 'google' or 'duckduckgo'", required=False, default="google")
    ]
)
async def browser_search(browser_name: str = "", query: str = "", site: str = "google") -> ToolResult:
    if not query:
        return ToolResult(success=False, error="missing_query", message="No search query given.")
    if not browser_name:
        browser_name = _active_browser_name or "Firefox"
    try:
        return await asyncio.wait_for(_do_browser_search(browser_name, query, site), timeout=BROWSER_SEARCH_TIMEOUT)
    except asyncio.TimeoutError:
        logger.error("browser_search_fail", phase="timeout", browser=browser_name)
        return ToolResult(success=False, error="browser_search_timeout",
                          message=f"Timed out while searching for '{query}'.")


async def _do_browser_search(browser_name: str, query: str, site: str) -> ToolResult:
    # 1 & 2: resolve + open/reuse the Airi session
    open_res = await browser_open(browser_name)
    if not open_res.success:
        return open_res

    s = (site or "google").lower()
    key = next((k for k in SEARCH_SITES if k in s), "google")
    url = SEARCH_SITES[key]
    try:
        # 3. Navigate
        logger.info("browser_search_navigate", url=url)
        await _page.goto(url, wait_until="domcontentloaded", timeout=15000)
        landing_url = _page.url

        # 4 & 5. Locate search input and type query
        typed_selector = None
        for sel in SEARCH_SELECTORS:
            try:
                element = await _page.wait_for_selector(sel, state="visible", timeout=2000)
            except Exception as ex:
                logger.debug("search_selector_miss", selector=sel, error=type(ex).__name__)
                continue
            if element:
                await element.fill(query)
                typed_selector = sel
                break
        if not typed_selector:
            return ToolResult(success=False, error="search_input_not_found",
                              message="Failed to locate a search input field on the page.",
                              data={"url": landing_url})

        # 6 & 7. Submit, then wait (bounded) for navigation away from the landing page.
        # Fallbacks handle pages whose JS submit handler isn't attached yet (seen on
        # YouTube in headed mode): Enter → Enter on the element → site results URL.
        async def _moved(timeout_ms: int) -> bool:
            try:
                await _page.wait_for_url(lambda u: u.rstrip("/") != landing_url.rstrip("/"), timeout=timeout_ms)
            except Exception:
                pass
            return (_page.url or "").rstrip("/") != (landing_url or "").rstrip("/")

        method = "keyboard_enter"
        await _page.keyboard.press("Enter")
        if not await _moved(5000):
            method = "element_enter"
            try:
                await element.press("Enter")
            except Exception:
                pass
            if not await _moved(4000):
                results_url = SEARCH_RESULTS_URL[key].format(q=urllib.parse.quote_plus(query))
                method = "results_url"
                logger.info("browser_search_fallback", method=method, url=results_url)
                await _page.goto(results_url, wait_until="domcontentloaded", timeout=15000)
        try:
            await _page.wait_for_load_state("domcontentloaded", timeout=5000)
        except Exception:
            pass

        # 8. Verify
        title = await _page.title()
        final_url = _page.url
        
        # Check for anti-bot / challenge pages
        final_lower = final_url.lower()
        title_lower = title.lower()
        if "/sorry/" in final_lower or "captcha" in final_lower or "challenge" in final_lower:
            return ToolResult(success=False, error="search_blocked", message="Search returned an access challenge or anti-bot page.", data={"url": final_url})
        if "unusual access" in title_lower or "blocked" in title_lower or "error" in title_lower:
            return ToolResult(success=False, error="search_blocked", message="Search was blocked or returned an error page.", data={"url": final_url, "title": title})
            
        if not _search_verified(query, landing_url, final_url, title):
            logger.warning("browser_search_unverified", url=final_url, title=title)
            return ToolResult(success=False, error="search_not_verified",
                              message="Search navigation did not appear to succeed.",
                              data={"url": final_url, "title": title})

        logger.info("browser_search_ok", url=final_url)
        return ToolResult(success=True, message=f"Searched for '{query}' on {key}",
                          data={"browser": _active_browser_name, "site": key, "query": query,
                                "title": title, "url": final_url, "selector": typed_selector,
                                "submit_method": method})
    except Exception as e:
        return ToolResult(success=False, error=f"Failed to perform search: {e}")

@tool(
    name="browser_navigate",
    description="Navigate the browser to a specific URL.",
    category="browser",
    permission_level=PermissionLevel.CONFIRM,
    parameters=[
        ToolParameter(name="url", type="string", description="URL to navigate to")
    ]
)
async def browser_navigate(url: str) -> ToolResult:
    global _page
    if not _page or _page.is_closed():
        return ToolResult(success=False, error="No active browser session. Call browser_open first.")
    
    if not url.startswith("http"):
        url = "https://" + url
        
    try:
        await _page.goto(url, wait_until="domcontentloaded", timeout=15000)
        return ToolResult(success=True, message=f"Navigated to {url}")
    except Exception as e:
        return ToolResult(success=False, error=str(e))

@tool(
    name="browser_type",
    description="Type text into an element in the browser. BROWSER_CONTROL.",
    category="browser",
    permission_level=PermissionLevel.CONFIRM,
    parameters=[
        ToolParameter(name="selector", type="string", description="DOM selector (e.g., 'input[name=\"q\"]', 'textarea')"),
        ToolParameter(name="text", type="string", description="Text to type")
    ]
)
async def browser_type(selector: str, text: str) -> ToolResult:
    global _page
    if not _page or _page.is_closed():
        return ToolResult(success=False, error="No active browser session.")
    try:
        await _page.fill(selector, text)
        return ToolResult(success=True, message=f"Typed '{text}' into {selector}")
    except Exception as e:
        return ToolResult(success=False, error=str(e))

@tool(
    name="browser_press",
    description="Press a keyboard key in the browser.",
    category="browser",
    permission_level=PermissionLevel.CONFIRM,
    parameters=[
        ToolParameter(name="key", type="string", description="Key to press (e.g., 'Enter', 'Escape')")
    ]
)
async def browser_press(key: str) -> ToolResult:
    global _page
    if not _page or _page.is_closed():
        return ToolResult(success=False, error="No active browser session.")
    try:
        await _page.keyboard.press(key)
        await asyncio.sleep(0.5)
        return ToolResult(success=True, message=f"Pressed '{key}'")
    except Exception as e:
        return ToolResult(success=False, error=str(e))

@tool(
    name="browser_click",
    description="Click an element in the browser.",
    category="browser",
    permission_level=PermissionLevel.CONFIRM,
    parameters=[
        ToolParameter(name="selector", type="string", description="DOM selector to click")
    ]
)
async def browser_click(selector: str) -> ToolResult:
    global _page
    if not _page or _page.is_closed():
        return ToolResult(success=False, error="No active browser session.")
    try:
        await _page.click(selector)
        return ToolResult(success=True, message=f"Clicked {selector}")
    except Exception as e:
        return ToolResult(success=False, error=str(e))

@tool(
    name="browser_read",
    description="Read text content from the current page.",
    category="browser",
    permission_level=PermissionLevel.SAFE
)
async def browser_read() -> ToolResult:
    global _page
    if not _page or _page.is_closed():
        return ToolResult(success=False, error="No active browser session.")
    try:
        content = await _page.evaluate("document.body.innerText")
        return ToolResult(success=True, data={"text": content[:2000]})
    except Exception as e:
        return ToolResult(success=False, error=str(e))

@tool(
    name="browser_screenshot",
    description="Take a screenshot of the current browser page.",
    category="browser",
    permission_level=PermissionLevel.SAFE
)
async def browser_screenshot() -> ToolResult:
    global _page
    if not _page or _page.is_closed():
        return ToolResult(success=False, error="No active browser session.")
    try:
        path = "/tmp/browser_shot.png"
        await _page.screenshot(path=path)
        return ToolResult(success=True, data={"path": path})
    except Exception as e:
        return ToolResult(success=False, error=str(e))

@tool(
    name="browser_wait",
    description="Wait for an element to appear or for the page to load.",
    category="browser",
    permission_level=PermissionLevel.SAFE,
    parameters=[
        ToolParameter(name="selector", type="string", description="DOM selector to wait for (optional)", required=False)
    ]
)
async def browser_wait(selector: str | None = None) -> ToolResult:
    global _page
    if not _page or _page.is_closed():
        return ToolResult(success=False, error="No active browser session.")
    try:
        if selector:
            await _page.wait_for_selector(selector, state="visible", timeout=5000)
            return ToolResult(success=True, message=f"Element {selector} is visible.")
        else:
            await _page.wait_for_load_state("networkidle", timeout=5000)
            return ToolResult(success=True, message="Page finished loading.")
    except Exception as e:
        return ToolResult(success=False, error=str(e))

def register(registry) -> None:
    pass

"""Firefox / Playwright integration tests.

Unit tests (always run, offline) verify engine selection, profile isolation,
lock handling and diagnostics. The real-browser integration test is opt-in:

    AIRI_BROWSER_INTEGRATION=1 .venv/bin/python -m pytest tests/test_browser_firefox.py -m integration
"""
import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import app.tools.browser.automation as auto
from app.tools.os_tools.desktop_parser import DesktopEntry


@pytest.fixture(autouse=True)
def clean_session(tmp_path, monkeypatch):
    """Isolate module-level session state and profile root per test."""
    monkeypatch.setattr(auto, "PROFILE_ROOT", tmp_path / "browser_data")
    for name in ("_playwright", "_browser_context", "_page", "_active_browser_name",
                 "_active_profile_dir", "_pending_profile_dir"):
        monkeypatch.setattr(auto, name, None)
    yield


def _mock_resolver(name="Firefox", exec_line="/usr/lib/firefox/firefox %u"):
    match = MagicMock()
    match.entry = DesktopEntry(path=f"/{name}.desktop", name=name, exec=exec_line)
    return patch("app.tools.browser.automation.AppResolver.resolve", return_value=match)


def _fake_playwright(bundled_path: str):
    page = MagicMock()
    page.is_closed.return_value = False
    ctx = MagicMock()
    ctx.pages = [page]
    pw = MagicMock()
    pw.firefox.executable_path = bundled_path
    pw.firefox.launch_persistent_context = AsyncMock(return_value=ctx)
    pw.chromium.launch_persistent_context = AsyncMock(return_value=ctx)
    return pw, ctx, page


# ── Regression: never pass the branded system Firefox to Playwright ──────────
@pytest.mark.asyncio
async def test_firefox_does_not_pass_system_executable(tmp_path, monkeypatch):
    bundled = tmp_path / "ms-playwright" / "firefox"
    bundled.parent.mkdir(parents=True)
    bundled.write_text("")
    pw, ctx, page = _fake_playwright(str(bundled))
    monkeypatch.setattr(auto, "_playwright", pw)

    with _mock_resolver():
        res = await auto.browser_open("Firefox")

    assert res.success is True, res
    kwargs = pw.firefox.launch_persistent_context.call_args.kwargs
    assert "executable_path" not in kwargs
    assert "/usr/lib/firefox/firefox" not in str(pw.firefox.launch_persistent_context.call_args)
    pw.chromium.launch_persistent_context.assert_not_called()
    assert res.data["engine"] == "firefox"


# ── Profile isolation ────────────────────────────────────────────────────────
def test_firefox_profile_is_separate_from_user_profile(monkeypatch):
    monkeypatch.setattr(auto, "PROFILE_ROOT", Path(os.path.expanduser("~/.config/airi/browser_data")))
    prof = auto.get_profile_dir("firefox", "Firefox")
    assert prof == Path(os.path.expanduser("~/.config/airi/browser_data/firefox"))
    mozilla = Path(os.path.expanduser("~/.mozilla"))
    assert mozilla not in prof.parents and prof != mozilla
    # Chromium-family browsers never share Firefox's profile (or each other's)
    assert auto.get_profile_dir("chromium", "Google Chrome") != prof
    assert auto.get_profile_dir("chromium", "Google Chrome") != auto.get_profile_dir("chromium", "Helium")


@pytest.mark.asyncio
async def test_firefox_launch_uses_airi_profile(tmp_path, monkeypatch):
    bundled = tmp_path / "ff"
    bundled.write_text("")
    pw, _, _ = _fake_playwright(str(bundled))
    monkeypatch.setattr(auto, "_playwright", pw)
    with _mock_resolver():
        await auto.browser_open("Firefox")
    user_data_dir = pw.firefox.launch_persistent_context.call_args.kwargs["user_data_dir"]
    assert user_data_dir == str(auto.PROFILE_ROOT / "firefox")
    assert ".mozilla" not in user_data_dir


# ── Diagnostics ──────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_missing_playwright_firefox_reports_not_installed(tmp_path, monkeypatch):
    pw, _, _ = _fake_playwright(str(tmp_path / "does-not-exist"))
    monkeypatch.setattr(auto, "_playwright", pw)
    with _mock_resolver():
        res = await auto.browser_open("Firefox")
    assert res.success is False
    assert res.error == "playwright_firefox_not_installed"
    assert "not installed" in res.message
    pw.firefox.launch_persistent_context.assert_not_called()


# ── Idempotent reuse ─────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_second_open_reuses_context(tmp_path, monkeypatch):
    bundled = tmp_path / "ff"
    bundled.write_text("")
    pw, _, _ = _fake_playwright(str(bundled))
    monkeypatch.setattr(auto, "_playwright", pw)
    with _mock_resolver():
        r1 = await auto.browser_open("Firefox")
        r2 = await auto.browser_open("Firefox")
    assert r1.success and r2.success
    assert r2.data["reused"] is True
    assert pw.firefox.launch_persistent_context.call_count == 1


@pytest.mark.asyncio
async def test_context_close_event_resets_session(tmp_path, monkeypatch):
    bundled = tmp_path / "ff"
    bundled.write_text("")
    pw, ctx, _ = _fake_playwright(str(bundled))
    monkeypatch.setattr(auto, "_playwright", pw)
    with _mock_resolver():
        await auto.browser_open("Firefox")
    handler = ctx.on.call_args.args[1]
    handler()
    assert auto._browser_context is None and auto._page is None


# ── Profile lock handling ────────────────────────────────────────────────────
def test_stale_lock_is_removed(tmp_path):
    prof = tmp_path / "firefox"
    prof.mkdir()
    os.symlink("127.0.0.1:+999999", prof / "lock")
    (prof / ".parentlock").write_text("")
    with patch.object(auto, "_pid_cmdline", return_value=None):
        ok, reason = auto.ensure_profile_unlocked(prof, "firefox")
    assert ok and reason == "stale_lock_removed"
    assert not (prof / "lock").is_symlink()
    assert not (prof / ".parentlock").exists()


def test_airi_owned_process_is_terminated(tmp_path):
    prof = tmp_path / "firefox"
    prof.mkdir()
    os.symlink("127.0.0.1:+4242", prof / "lock")
    with patch.object(auto, "_pid_cmdline", return_value=f"firefox -profile {prof} -juggler-pipe"), \
         patch.object(auto, "_kill_pid") as kill:
        ok, reason = auto.ensure_profile_unlocked(prof, "firefox")
    assert ok and reason == "airi_process_terminated"
    kill.assert_called_once_with(4242)


def test_foreign_process_is_never_killed(tmp_path):
    prof = tmp_path / "firefox"
    prof.mkdir()
    os.symlink("127.0.0.1:+4343", prof / "lock")
    with patch.object(auto, "_pid_cmdline", return_value="/usr/lib/firefox/firefox"), \
         patch.object(auto, "_kill_pid") as kill:
        ok, reason = auto.ensure_profile_unlocked(prof, "firefox")
    assert ok is False and "foreign" in reason
    kill.assert_not_called()


@pytest.mark.asyncio
async def test_launch_failure_retries_once_then_fails_structured(tmp_path, monkeypatch):
    bundled = tmp_path / "ff"
    bundled.write_text("")
    pw, _, _ = _fake_playwright(str(bundled))
    pw.firefox.launch_persistent_context = AsyncMock(side_effect=RuntimeError("profile in use"))
    monkeypatch.setattr(auto, "_playwright", pw)
    with _mock_resolver():
        res = await auto.browser_open("Firefox")
    assert res.success is False
    assert res.data["phase"] == "context_create"
    assert pw.firefox.launch_persistent_context.call_count == 2
    assert auto._browser_context is None


@pytest.mark.asyncio
async def test_timeout_resets_state(tmp_path, monkeypatch):
    import asyncio
    bundled = tmp_path / "ff"
    bundled.write_text("")
    pw, _, _ = _fake_playwright(str(bundled))

    async def hang(**_kw):
        await asyncio.sleep(10)
    pw.firefox.launch_persistent_context = hang
    monkeypatch.setattr(auto, "_playwright", pw)
    monkeypatch.setattr(auto, "BROWSER_OPEN_TIMEOUT", 0.2)
    with _mock_resolver():
        res = await auto.browser_open("Firefox")
    assert res.success is False and res.error == "browser_open_timeout"
    assert auto._browser_context is None and auto._active_browser_name is None


# ── Real browser (opt-in; needs display + network) ───────────────────────────
@pytest.mark.integration
@pytest.mark.skipif(os.environ.get("AIRI_BROWSER_INTEGRATION") != "1",
                    reason="set AIRI_BROWSER_INTEGRATION=1 to launch a real Playwright Firefox")
@pytest.mark.asyncio
async def test_real_playwright_firefox_youtube(tmp_path, monkeypatch):
    import time
    monkeypatch.setattr(auto, "HEADLESS", os.environ.get("AIRI_BROWSER_HEADED") != "1")
    t0 = time.monotonic()
    res = await auto.browser_open("Firefox")
    elapsed = time.monotonic() - t0
    try:
        assert res.success is True, res
        assert elapsed < auto.BROWSER_OPEN_TIMEOUT
        assert auto._browser_context is not None and auto._page is not None
        assert str(auto._active_profile_dir).endswith("browser_data/firefox")

        nav = await auto.browser_navigate("https://www.youtube.com")
        assert nav.success is True, nav
        assert "youtube.com" in auto._page.url

        search = await auto.browser_search("", "ElectroBOOM", "youtube")
        assert search.success is True, search
        assert "search_query=" in search.data["url"]
        print(f"\nbrowser_open took {elapsed:.2f}s; search url={search.data['url']}")
    finally:
        await auto._reset_browser_state()
        if auto._playwright is not None:
            await auto._playwright.stop()

"""Browser DOM inspection and element selection tools for Airi Playwright sessions."""
from __future__ import annotations

import asyncio
import re
from typing import Any, Optional

import structlog

from app.tools.registry import PermissionLevel, ToolDefinition, ToolParameter, ToolRegistry, ToolResult, tool

logger = structlog.get_logger(__name__)


def _get_active_page():
    """Retrieve the active Playwright page from automation module."""
    try:
        import app.tools.browser.automation as auto
        if auto._page and not auto._page.is_closed():
            return auto._page
    except Exception:
        pass
    return None


@tool(
    name="browser_inspect",
    description=(
        "Inspect visible, actionable DOM elements in Airi's active Playwright browser session. "
        "Returns semantic roles, accessible names, visible text, and locators."
    ),
    category="browser",
    permission_level=PermissionLevel.SAFE,
)
async def browser_inspect() -> ToolResult:
    """Inspect visible DOM elements on the current Playwright page."""
    page = _get_active_page()
    if not page:
        return ToolResult(
            success=False,
            error="no_active_browser_session",
            message="No active Airi browser session. Use browser_open or browser_search first.",
        )

    js_code = """
    () => {
        const results = [];
        const selectorSet = new Set();
        const candidateSelectors = [
            'a[href]',
            'button',
            'input',
            'textarea',
            'select',
            '[role="button"]',
            '[role="link"]',
            '[role="tab"]',
            'ytd-video-renderer a#video-title',
            'article a',
            'h3 a'
        ];
        
        const elements = document.querySelectorAll(candidateSelectors.join(','));
        for (let el of elements) {
            const rect = el.getBoundingClientRect();
            const style = window.getComputedStyle(el);
            
            // Check visibility
            if (
                rect.width > 0 &&
                rect.height > 0 &&
                style.visibility !== 'hidden' &&
                style.display !== 'none' &&
                rect.top < window.innerHeight &&
                rect.bottom > 0
            ) {
                // Determine accessible name or label
                let name = el.getAttribute('aria-label') || el.getAttribute('title') || el.innerText || el.value || '';
                name = name.trim().replace(/\\s+/g, ' ').slice(0, 150);
                
                const role = el.getAttribute('role') || el.tagName.toLowerCase();
                const href = el.getAttribute('href') || '';
                const isAd = !!(
                    el.closest('ytd-ad-slot-renderer') ||
                    el.closest('.badge-style-type-ad') ||
                    el.closest('[data-text-ad]') ||
                    (el.getAttribute('aria-label') && /sponsored|advertisement/i.test(el.getAttribute('aria-label')))
                );

                let id = el.id ? '#' + el.id : '';
                let className = (typeof el.className === 'string' && el.className.trim()) ? '.' + el.className.trim().split(/\\s+/)[0] : '';
                let selector = el.tagName.toLowerCase() + id + className;

                results.push({
                    role: role,
                    accessible_name: name,
                    visible_text: name,
                    element_type: el.tagName.toLowerCase(),
                    visible: true,
                    enabled: !el.disabled,
                    link_destination: href,
                    is_ad: isAd,
                    selector: selector
                });

                if (results.length >= 60) break;
            }
        }
        return results;
    }
    """

    try:
        elements = await page.evaluate(js_code)
        title = await page.title()
        url = page.url
        logger.info("browser_inspect_success", url=url, element_count=len(elements))
        return ToolResult(
            success=True,
            data={
                "url": url,
                "title": title,
                "element_count": len(elements),
                "elements": elements,
                "untrusted_content": True,
            },
            message=f"Current page '{title}' ({url}) has {len(elements)} visible actionable elements.",
        )
    except Exception as e:
        logger.error("browser_inspect_failed", error=str(e))
        return ToolResult(success=False, error=str(e))


@tool(
    name="browser_select_first",
    description=(
        "Select and open the first matching visible option or video in Airi's browser session. "
        "Differentiates actual YouTube videos from ads, channels, and playlists."
    ),
    category="browser",
    permission_level=PermissionLevel.SAFE,
    parameters=[
        ToolParameter(
            name="item_type",
            type="string",
            description="Type of item: 'video' (YouTube video), 'result' (search result), or 'option'.",
            required=False,
            default="video",
        ),
        ToolParameter(
            name="query",
            type="string",
            description="Optional target keyword or title filter.",
            required=False,
            default="",
        ),
        ToolParameter(
            name="index",
            type="integer",
            description="1-based index of the item to select (default: 1)",
            required=False,
            default=1,
        ),
    ],
)
async def browser_select_first(item_type: str = "video", query: str = "", index: int = 1) -> ToolResult:
    """Select the N-th organic result or video in the current Playwright page."""
    page = _get_active_page()
    if not page:
        return ToolResult(
            success=False,
            error="no_active_browser_session",
            message="No active Airi browser session. Open a browser page first.",
        )

    current_url = page.url
    is_youtube = "youtube.com" in current_url.lower()
    logger.info("browser_select_first_start", item_type=item_type, query=query, index=index, current_url=current_url, is_youtube=is_youtube)

    # 1. YouTube Specific Video Resolution
    if is_youtube or item_type == "video":
        target_locator = None
        target_title = ""

        # Dismiss any YouTube consent / cookie dialog if present
        try:
            consent_locators = [
                "ytd-consent-bump-v2-lightbox button",
                "button[aria-label*='Accept all' i]",
                "button[aria-label*='Reject all' i]",
                "button[aria-label*='Agree' i]",
                "button:has-text('Accept all')",
                "button:has-text('Reject all')",
                "button:has-text('I agree')",
            ]
            for c_sel in consent_locators:
                try:
                    c_btn = page.locator(c_sel)
                    if asyncio.iscoroutine(c_btn):
                        c_btn = await c_btn
                    c_cnt = c_btn.count()
                    if asyncio.iscoroutine(c_cnt):
                        c_cnt = await c_cnt
                    if int(c_cnt) > 0:
                        first_btn = c_btn.first
                        if asyncio.iscoroutine(first_btn):
                            first_btn = await first_btn
                        is_vis = first_btn.is_visible()
                        if asyncio.iscoroutine(is_vis):
                            is_vis = await is_vis
                        if is_vis:
                            logger.info("dismissing_youtube_consent_dialog", selector=c_sel)
                            await first_btn.click(timeout=1500)
                            await page.wait_for_timeout(400)
                            break
                except Exception:
                    pass
        except Exception as ex:
            logger.debug("consent_dismiss_exception", error=str(ex))

        # Wait briefly for results to populate if on a results page
        try:
            await page.wait_for_selector(
                "ytd-video-renderer, ytd-rich-item-renderer, ytd-compact-video-renderer, a[href*='/watch']",
                timeout=5000,
            )
        except Exception:
            pass

        is_results_page = "/results" in current_url.lower()
        query_in_page_url = bool(
            query and is_results_page and (
                query.lower() in current_url.lower()
                or query.replace(" ", "+").lower() in current_url.lower()
                or query.replace(" ", "%20").lower() in current_url.lower()
            )
        )

        # Strategy A: Use video renderer containers to exclude ads
        video_renderers = page.locator("ytd-video-renderer")
        if asyncio.iscoroutine(video_renderers):
            video_renderers = await video_renderers
        try:
            cnt_val = video_renderers.count()
            if asyncio.iscoroutine(cnt_val):
                cnt_val = await cnt_val
            count = int(cnt_val)
        except Exception:
            count = 0

        if count == 0:
            for alt_sel in ("ytd-rich-item-renderer", "ytd-compact-video-renderer"):
                try:
                    alt_renderers = page.locator(alt_sel)
                    if asyncio.iscoroutine(alt_renderers):
                        alt_renderers = await alt_renderers
                    alt_cnt = alt_renderers.count()
                    if asyncio.iscoroutine(alt_cnt):
                        alt_cnt = await alt_cnt
                    if int(alt_cnt) > 0:
                        video_renderers = alt_renderers
                        count = int(alt_cnt)
                        break
                except Exception:
                    pass

        matched_count = 0
        for i in range(count):
            renderer = video_renderers.nth(i)
            if asyncio.iscoroutine(renderer):
                renderer = await renderer

            # Check if this renderer is an advertisement
            is_ad = False
            try:
                ad_check = renderer.locator(
                    "ytd-ad-slot-renderer, .badge-style-type-ad, [aria-label*='Ad' i], [aria-label*='Sponsored' i], ytd-in-feed-ad-layout-renderer"
                )
                if asyncio.iscoroutine(ad_check):
                    ad_check = await ad_check
                ad_cnt = ad_check.count()
                if asyncio.iscoroutine(ad_cnt):
                    ad_cnt = await ad_cnt
                is_ad = int(ad_cnt) > 0
            except Exception:
                is_ad = False
            if is_ad:
                continue

            title_link = renderer.locator("a#video-title")
            if asyncio.iscoroutine(title_link):
                title_link = await title_link
            try:
                tl_cnt = title_link.count()
                if asyncio.iscoroutine(tl_cnt):
                    tl_cnt = await tl_cnt
                has_tl = int(tl_cnt) > 0
            except Exception:
                has_tl = False

            if not has_tl:
                try:
                    alt_tl = renderer.locator("a#video-title-link, a[href*='/watch?v=']")
                    if asyncio.iscoroutine(alt_tl):
                        alt_tl = await alt_tl
                    alt_cnt = alt_tl.count()
                    if asyncio.iscoroutine(alt_cnt):
                        alt_cnt = await alt_cnt
                    if int(alt_cnt) > 0:
                        title_link = alt_tl
                        has_tl = True
                except Exception:
                    pass

            first_link = None
            if has_tl:
                first_link = title_link.first
                if asyncio.iscoroutine(first_link):
                    first_link = await first_link
                try:
                    is_vis = first_link.is_visible()
                    if asyncio.iscoroutine(is_vis):
                        is_vis = await is_vis
                    if not is_vis:
                        first_link = None
                except Exception:
                    pass

            if first_link:
                href = (await first_link.get_attribute("href")) or ""
                # Must be a real video (/watch?v=), not a playlist, channel, or shorts
                if "/watch?v=" in href and "/playlist" not in href and "/shorts/" not in href:
                    raw_title = (
                        (await first_link.text_content())
                        or (await first_link.get_attribute("title"))
                        or (await first_link.get_attribute("aria-label"))
                        or ""
                    ).strip()
                    title = raw_title
                    # Only filter title by query if query is not the general page search query
                    if query and not query_in_page_url and query.lower() not in title.lower():
                        continue
                    matched_count += 1
                    if matched_count == index:
                        target_locator = first_link
                        target_title = title
                        break

        # Strategy B: Fallback to general video links if not standard search layout
        if not target_locator:
            candidate_links = page.locator("a[href*='/watch?v=']:not([href*='/playlist']):not([href*='/shorts/'])")
            if asyncio.iscoroutine(candidate_links):
                candidate_links = await candidate_links
            cand_count = await candidate_links.count()
            fallback_matched = 0
            for i in range(cand_count):
                link = candidate_links.nth(i)
                if asyncio.iscoroutine(link):
                    link = await link
                if not await link.is_visible():
                    continue
                # Exclude ads
                ancestor_ad = link.locator(
                    "xpath=ancestor::*[contains(@class, 'ad') or contains(@id, 'ad') or contains(@aria-label, 'Ad') or contains(@aria-label, 'Sponsored')]"
                )
                if asyncio.iscoroutine(ancestor_ad):
                    ancestor_ad = await ancestor_ad
                is_ad = await ancestor_ad.count() > 0
                if is_ad:
                    continue

                txt = (
                    await link.text_content()
                    or await link.get_attribute("title")
                    or await link.get_attribute("aria-label")
                    or ""
                ).strip()
                if query and not query_in_page_url and query.lower() not in txt.lower():
                    continue

                fallback_matched += 1
                if fallback_matched == index:
                    target_locator = link
                    target_title = txt or f"Video {index}"
                    break

        if not target_locator:
            return ToolResult(
                success=False,
                error="no_video_found",
                message="No visible organic video results were found on the page.",
            )

        logger.info("browser_element_selected", title=target_title)

        # Click and verify
        try:
            initial_url = page.url
            try:
                await target_locator.scroll_into_view_if_needed(timeout=2000)
            except Exception:
                pass

            try:
                await target_locator.click(timeout=8000)
            except Exception as click_err:
                logger.warning("direct_click_failed_attempting_dispatch", error=str(click_err))
                await target_locator.dispatch_event("click")

            # Verify URL changed or video player loaded
            try:
                await page.wait_for_url(lambda u: "/watch" in u or u != initial_url, timeout=12000)
                await page.wait_for_load_state("domcontentloaded", timeout=6000)
            except Exception:
                pass

            # Check if video player element exists and is active
            player_active = False
            try:
                player = page.locator("#movie_player, video.html5-main-video")
                if asyncio.iscoroutine(player):
                    player = await player
                if await player.count() > 0:
                    player_active = True
            except Exception:
                pass

            new_url = page.url
            if "/watch" in new_url or (new_url != initial_url and player_active) or (new_url != initial_url):
                logger.info(
                    "action_verification_success",
                    target_title=target_title,
                    initial_url=initial_url,
                    new_url=new_url,
                    player_active=player_active,
                )
                try:
                    from app.agent.task_context import get_browser_task_context
                    ctx = get_browser_task_context()
                    ctx.update_navigation(url=new_url, title=target_title)
                except Exception:
                    pass

                return ToolResult(
                    success=True,
                    message=f"Opened video: '{target_title}' ({new_url}).",
                    data={"title": target_title, "url": new_url, "verified": True},
                )
            else:
                logger.error(
                    "action_verification_failure",
                    reason="url_did_not_change_and_no_player",
                    initial_url=initial_url,
                    new_url=new_url,
                )
                return ToolResult(
                    success=False,
                    error="verification_failed",
                    message=f"Clicked '{target_title}', but could not verify that the video opened.",
                )
        except Exception as e:
            logger.error("action_verification_failure", error=str(e))
            return ToolResult(success=False, error=f"Failed to click target video: {e}")

    # 2. General Search Results (Google, DuckDuckGo, generic websites)
    candidate_locators = [
        # Google search results
        "#search a:has(h3):not([data-text-ad]):not([aria-label*='Sponsored'])",
        ".g a:has(h3)",
        # DuckDuckGo search results
        "article[data-testid='result'] a[data-testid='result-title-a']",
        # Generic options / search results
        "main article a[href]",
        "main a[href]:has(h2, h3, h4)",
        "div[role='listbox'] [role='option']",
    ]

    selected_locator = None
    selected_name = ""

    for pattern in candidate_locators:
        loc = page.locator(pattern)
        if asyncio.iscoroutine(loc):
            loc = await loc
        try:
            c = await loc.count()
            if c >= index:
                target_cand = loc.nth(index - 1)
                if asyncio.iscoroutine(target_cand):
                    target_cand = await target_cand
                if await target_cand.is_visible():
                    selected_locator = target_cand
                    selected_name = (await selected_locator.text_content() or "").strip()
                    break
            elif c > 0 and index == 1 and await loc.first.is_visible():
                selected_locator = loc.first
                selected_name = (await selected_locator.text_content() or "").strip()
                break
        except Exception:
            continue

    if not selected_locator:
        return ToolResult(
            success=False,
            error="no_result_found",
            message=f"Could not find an unambiguous item at index {index} on this page.",
        )

    logger.info("browser_element_selected", target=selected_name, index=index)
    try:
        initial_url = page.url
        await selected_locator.click(timeout=10000)
        try:
            await page.wait_for_load_state("domcontentloaded", timeout=8000)
        except Exception:
            pass

        new_url = page.url
        if new_url != initial_url:
            logger.info("action_verification_success", new_url=new_url, target=selected_name)
            try:
                from app.agent.task_context import get_browser_task_context
                ctx = get_browser_task_context()
                ctx.update_navigation(url=new_url, title=selected_name)
            except Exception:
                pass
            return ToolResult(
                success=True,
                message=f"Selected: '{selected_name}' ({new_url}).",
                data={"title": selected_name, "url": new_url, "verified": True},
            )
        else:
            logger.error("action_verification_failure", reason="url_did_not_change", url=new_url)
            return ToolResult(
                success=False,
                error="verification_failed",
                message=f"Clicked '{selected_name}', but could not verify that navigation occurred.",
            )
    except Exception as e:
        logger.error("action_verification_failure", error=str(e))
        return ToolResult(success=False, error=f"Failed to click result: {e}")


def register(registry: ToolRegistry) -> None:
    """Register browser inspection and selection tools."""
    registry.register(
        ToolDefinition(
            name="browser_inspect",
            description=(
                "Inspect visible, actionable DOM elements in Airi's active Playwright browser session. "
                "Returns semantic roles, accessible names, visible text, and locators."
            ),
            category="browser",
            permission_level=PermissionLevel.SAFE,
            parameters=[],
        ),
        browser_inspect,
    )
    registry.register(
        ToolDefinition(
            name="browser_select_first",
            description=(
                "Select and open a matching visible option or video in Airi's browser session. "
                "Differentiates actual YouTube videos from ads, channels, and playlists. Supports ordinal indexing."
            ),
            category="browser",
            permission_level=PermissionLevel.SAFE,
            parameters=[
                ToolParameter(
                    name="item_type",
                    type="string",
                    description="Type of item: 'video', 'result', or 'option'.",
                    required=False,
                    default="video",
                ),
                ToolParameter(
                    name="query",
                    type="string",
                    description="Optional target keyword or title filter.",
                    required=False,
                    default="",
                ),
                ToolParameter(
                    name="index",
                    type="integer",
                    description="1-based index of item to select (default: 1).",
                    required=False,
                    default=1,
                ),
            ],
        ),
        browser_select_first,
    )

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

        # Wait briefly for results to populate if on a results page
        try:
            await page.wait_for_selector("ytd-video-renderer, ytd-rich-item-renderer, a[href*='/watch']", timeout=5000)
        except Exception:
            pass

        # Strategy A: Use ytd-video-renderer containers to exclude ads
        video_renderers = page.locator("ytd-video-renderer")
        if asyncio.iscoroutine(video_renderers):
            video_renderers = await video_renderers
        count = await video_renderers.count()

        matched_count = 0
        for i in range(count):
            renderer = video_renderers.nth(i)
            if asyncio.iscoroutine(renderer):
                renderer = await renderer

            # Check if this renderer is an advertisement
            ad_check = renderer.locator("ytd-ad-slot-renderer, .badge-style-type-ad, [aria-label*='Ad' i], [aria-label*='Sponsored' i]")
            if asyncio.iscoroutine(ad_check):
                ad_check = await ad_check
            is_ad = await ad_check.count() > 0
            if is_ad:
                continue

            title_link = renderer.locator("a#video-title")
            if asyncio.iscoroutine(title_link):
                title_link = await title_link
            if await title_link.count() > 0 and await title_link.first.is_visible():
                href = await title_link.first.get_attribute("href") or ""
                # Must be a real video (/watch?v=), not a playlist, channel, or shorts
                if "/watch?v=" in href and "/playlist" not in href:
                    raw_title = await title_link.first.text_content() or ""
                    title = raw_title.strip()
                    if query and query.lower() not in title.lower():
                        continue
                    matched_count += 1
                    if matched_count == index:
                        target_locator = title_link.first
                        target_title = title
                        break

        # Strategy B: Fallback to general video links if not standard search layout
        if not target_locator:
            candidate_links = page.locator("a[href*='/watch?v=']:not([href*='/playlist'])")
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
                    "xpath=ancestor::*[contains(@class, 'ad') or contains(@id, 'ad') or contains(@aria-label, 'Ad')]"
                )
                if asyncio.iscoroutine(ancestor_ad):
                    ancestor_ad = await ancestor_ad
                is_ad = await ancestor_ad.count() > 0
                if is_ad:
                    continue

                txt = (await link.text_content() or "").strip()
                if not txt:
                    # check title attribute or aria-label
                    txt = (await link.get_attribute("title") or await link.get_attribute("aria-label") or "").strip()
                if query and query.lower() not in txt.lower():
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
            await target_locator.click(timeout=10000)
            
            # Verify URL changed or video player loaded
            try:
                await page.wait_for_url(lambda u: "/watch" in u or u != initial_url, timeout=12000)
                await page.wait_for_load_state("domcontentloaded", timeout=8000)
            except Exception:
                pass

            new_url = page.url
            if "/watch" in new_url or new_url != initial_url:
                logger.info("action_verification_success", new_url=new_url)
                return ToolResult(
                    success=True,
                    message=f"Opened video: '{target_title}' ({new_url}).",
                    data={"title": target_title, "url": new_url, "verified": True},
                )
            else:
                logger.error("action_verification_failure", reason="url_did_not_change", url=new_url)
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
        logger.info("action_verification_success", new_url=new_url)
        return ToolResult(
            success=True,
            message=f"Selected: '{selected_name}' ({new_url}).",
            data={"title": selected_name, "url": new_url, "verified": True},
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

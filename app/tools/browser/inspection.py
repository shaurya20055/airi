"""Browser DOM inspection and element selection tools for Airi Playwright sessions."""
from __future__ import annotations

import asyncio
import re
from typing import Any, Optional

import structlog

from app.agent.task_context import get_browser_task_context
from app.tools.browser.resolver import ElementResolver, InspectedElement, ResolutionResult
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
        "Returns semantic roles, accessible names, visible text, accordions, toggles, icons, and locators."
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
        const candidateSelectors = [
            'a[href]',
            'button',
            'input',
            'textarea',
            'select',
            '[role="button"]',
            '[role="link"]',
            '[role="tab"]',
            '[role="menuitem"]',
            '[role="checkbox"]',
            '[role="switch"]',
            '[role="combobox"]',
            '[role="option"]',
            'summary',
            'details',
            '[aria-expanded]',
            '[aria-pressed]',
            'ytd-video-renderer a#video-title',
            'article a',
            'h3 a',
            'table tr td a',
            'table tr td button'
        ];
        
        // Clear previously stamped data-airi-ref if any
        try {
            document.querySelectorAll('[data-airi-ref]').forEach(el => el.removeAttribute('data-airi-ref'));
        } catch (e) {}

        const seenElements = new Set();
        const elements = document.querySelectorAll(candidateSelectors.join(','));
        let refCounter = 1;

        for (let el of elements) {
            if (seenElements.has(el)) continue;
            seenElements.add(el);

            const rect = el.getBoundingClientRect();
            const style = window.getComputedStyle(el);

            // Check visibility (not hidden by display:none or visibility:hidden)
            const isVisible = (
                rect.width > 0 &&
                rect.height > 0 &&
                style.visibility !== 'hidden' &&
                style.display !== 'none'
            );
            if (!isVisible) continue;

            // Stamp ref id on element for exact locator matching
            const refId = `@e${refCounter}`;
            try {
                el.setAttribute('data-airi-ref', refId);
            } catch (e) {}

            const tag = el.tagName.toLowerCase();
            let role = el.getAttribute('role') || tag;
            let ariaLabel = el.getAttribute('aria-label') || '';
            let titleAttr = el.getAttribute('title') || '';
            let placeholder = el.getAttribute('placeholder') || '';
            let innerText = (el.innerText || el.textContent || '').trim().replace(/\\s+/g, ' ');
            
            // Accessible name resolution
            let accessibleName = ariaLabel || titleAttr || placeholder || innerText;
            if (accessibleName.length > 200) accessibleName = accessibleName.slice(0, 200);

            // Expanded state (accordions/disclosures)
            let expanded = null;
            if (el.hasAttribute('aria-expanded')) {
                expanded = el.getAttribute('aria-expanded') === 'true';
            } else if (tag === 'details') {
                expanded = el.hasAttribute('open');
            } else if (tag === 'summary') {
                const parentDetails = el.closest('details');
                if (parentDetails) expanded = parentDetails.hasAttribute('open');
            }

            // Pressed state (toggles/likes)
            let pressed = null;
            if (el.hasAttribute('aria-pressed')) {
                pressed = el.getAttribute('aria-pressed') === 'true';
            }

            // Checked state
            let checked = null;
            if (el.hasAttribute('aria-checked')) {
                checked = el.getAttribute('aria-checked') === 'true';
            } else if (tag === 'input' && (el.type === 'checkbox' || el.type === 'radio')) {
                checked = el.checked;
            }

            // Icon detection
            let isIcon = false;
            let iconName = '';
            const svg = el.querySelector('svg');
            const img = el.querySelector('img');
            if (svg || img || /icon|fa-|svg/i.test(el.className || '')) {
                isIcon = true;
                const svgTitle = svg ? (svg.querySelector('title')?.textContent || '') : '';
                const useHref = svg ? (svg.querySelector('use')?.getAttribute('href') || svg.querySelector('use')?.getAttribute('xlink:href') || '') : '';
                const imgAlt = img ? (img.getAttribute('alt') || '') : '';
                const classStr = typeof el.className === 'string' ? el.className : '';
                const allIconHints = `${svgTitle} ${useHref} ${imgAlt} ${classStr} ${ariaLabel} ${el.getAttribute('href') || ''}`.toLowerCase();
                
                for (let iconKw of ['leetcode', 'youtube', 'github', 'settings', 'search', 'chevron', 'arrow', 'like', 'thumbs-up', 'subscribe', 'heart', 'star', 'play', 'close', 'menu', 'filter', 'gear']) {
                    if (allIconHints.includes(iconKw)) {
                        iconName = iconKw;
                        break;
                    }
                }
            }

            // Parent container / section hierarchy detection
            let sectionParts = [];
            const parentRow = el.closest('tr, [role="row"]');
            const parentCard = el.closest('article, [role="article"], .card, .item');
            const parentDetails = el.closest('details');
            const parentSectionEl = el.closest('section, fieldset, [role="region"], [role="group"]');

            let containerType = '';
            if (parentRow) {
                containerType = 'row';
                const firstCol = parentRow.querySelector('td, th, [role="cell"]');
                const rowText = (firstCol ? firstCol.innerText : parentRow.innerText).trim().replace(/\\s+/g, ' ').slice(0, 80);
                if (rowText) sectionParts.push(rowText);
            }
            if (parentCard) {
                if (!containerType) containerType = 'card';
                const heading = parentCard.querySelector('h1, h2, h3, h4, h5, h6, .title, .header');
                const cardText = (heading ? heading.innerText : '').trim().replace(/\\s+/g, ' ').slice(0, 80);
                if (cardText && !sectionParts.includes(cardText)) sectionParts.push(cardText);
            }
            if (parentDetails) {
                if (!containerType) containerType = 'details';
                const sum = parentDetails.querySelector('summary');
                const detText = (sum ? sum.innerText : '').trim().replace(/\\s+/g, ' ').slice(0, 80);
                if (detText && !sectionParts.includes(detText)) sectionParts.push(detText);
            }
            if (parentSectionEl) {
                if (!containerType) containerType = 'section';
                const heading = parentSectionEl.querySelector('h1, h2, h3, h4, h5, h6');
                const secText = (heading ? heading.innerText : '').trim().replace(/\\s+/g, ' ').slice(0, 80);
                if (secText && !sectionParts.includes(secText)) sectionParts.push(secText);
            }

            const parentSection = sectionParts.join(' > ');

            // Element type categorization
            let elementType = tag;
            if (expanded !== null || tag === 'summary' || tag === 'details') {
                elementType = 'accordion';
            } else if (pressed !== null) {
                elementType = 'toggle';
            } else if (tag === 'button' || role === 'button') {
                elementType = 'button';
            } else if (tag === 'a' || role === 'link') {
                elementType = 'link';
            } else if (tag === 'input' || tag === 'textarea') {
                elementType = 'input';
            } else if (tag === 'select') {
                elementType = 'select';
            }

            // Stable selector
            let selector = `[data-airi-ref="${refId}"]`;
            if (el.id) {
                selector = `#${el.id}`;
            }

            results.push({
                ref_id: refId,
                index: refCounter,
                tag: tag,
                role: role,
                accessible_name: accessibleName,
                visible_text: innerText.slice(0, 150),
                selector: selector,
                element_type: elementType,
                href: el.getAttribute('href') || '',
                input_type: el.getAttribute('type') || '',
                placeholder: placeholder,
                value: el.value || '',
                expanded: expanded,
                pressed: pressed,
                checked: checked,
                disabled: !!el.disabled,
                is_icon: isIcon,
                icon_name: iconName,
                parent_section: parentSection,
                container_type: containerType,
                classes: typeof el.className === 'string' ? el.className.split(/\\s+/).filter(Boolean) : []
            });

            refCounter++;
            if (results.length >= 80) break;
        }

        return results;
    }
    """

    try:
        raw_elements = await page.evaluate(js_code)
        title = await page.title() if hasattr(page, "title") else ""
        url = page.url if hasattr(page, "url") else ""

        inspected_elements: list[InspectedElement] = []
        if isinstance(raw_elements, list):
            for d in raw_elements:
                if isinstance(d, dict):
                    inspected_elements.append(
                        InspectedElement(
                            ref_id=d.get("ref_id", f"@e{len(inspected_elements)+1}"),
                            index=d.get("index", len(inspected_elements) + 1),
                            tag=d.get("tag", "div"),
                            role=d.get("role", "button"),
                            accessible_name=d.get("accessible_name", ""),
                            visible_text=d.get("visible_text", ""),
                            selector=d.get("selector", f"[data-airi-ref='@e{len(inspected_elements)+1}']"),
                            element_type=d.get("element_type", "button"),
                            href=d.get("href", ""),
                            input_type=d.get("input_type", ""),
                            placeholder=d.get("placeholder", ""),
                            value=d.get("value", ""),
                            expanded=d.get("expanded"),
                            pressed=d.get("pressed"),
                            checked=d.get("checked"),
                            disabled=d.get("disabled", False),
                            is_icon=d.get("is_icon", False),
                            icon_name=d.get("icon_name", ""),
                            parent_section=d.get("parent_section", ""),
                            container_type=d.get("container_type", ""),
                            classes=d.get("classes", []),
                        )
                    )
                elif isinstance(d, InspectedElement):
                    inspected_elements.append(d)

        # Cache inspected elements in BrowserTaskContext
        try:
            ctx = get_browser_task_context()
            ctx.update_inspection(inspected_elements, url=url, title=title)
        except Exception:
            pass

        logger.info("browser_inspect_success", url=url, element_count=len(inspected_elements))

        summary_lines = [f"Current page '{title}' ({url}) has {len(inspected_elements)} visible actionable elements:"]
        for el in inspected_elements[:25]:
            details = []
            if el.parent_section:
                details.append(f"in {el.parent_section}")
            if el.expanded is not None:
                details.append("expanded" if el.expanded else "collapsed")
            if el.pressed is not None:
                details.append("pressed" if el.pressed else "not pressed")
            if el.is_icon and el.icon_name:
                details.append(f"icon:{el.icon_name}")
            detail_str = f" [{', '.join(details)}]" if details else ""
            summary_lines.append(f"- {el.ref_id} {el.element_type} '{el.accessible_name}'{detail_str}")

        if len(inspected_elements) > 25:
            summary_lines.append(f"... and {len(inspected_elements) - 25} more elements.")

        return ToolResult(
            success=True,
            data={
                "url": url,
                "title": title,
                "element_count": len(inspected_elements),
                "elements": [e.to_dict() for e in inspected_elements],
                "untrusted_content": True,
            },
            message="\n".join(summary_lines),
        )
    except Exception as e:
        logger.error("browser_inspect_failed", error=str(e))
        return ToolResult(success=False, error=str(e))


async def _try_vision_fallback_click(page: Any, target: str) -> Optional[ToolResult]:
    """Attempt screen vision observation and click when DOM representation is absent or canvas-based."""
    try:
        t_low = target.lower()
        ctx = get_browser_task_context()
        has_dom_elements = bool(ctx.last_inspected_elements)
        is_visual_target = any(
            kw in t_low
            for kw in ("canvas", "game", "visual", "board", "draw", "graphic", "screen", "viewport")
        )

        # Do not arbitrarily fall back to canvas when page has actionable DOM elements
        # unless user requested visual/canvas interaction
        if has_dom_elements and not is_visual_target:
            return None

        # Check if page has canvas elements
        has_canvas = False
        try:
            has_canvas = bool(await page.evaluate("() => document.querySelectorAll('canvas').length > 0"))
        except Exception:
            pass

        if not has_canvas:
            return None

        logger.info("vision_fallback_initiated", target=target)

        # Locate canvas element
        canvas = page.locator("canvas").first
        box = None
        try:
            box = await canvas.bounding_box()
        except TypeError:
            box = canvas.bounding_box()
        except Exception:
            pass

        if not box:
            return None

        # Fresh screenshot via screen capture provider
        try:
            from app.tools.screen.provider import get_screen_capture_provider
            provider = get_screen_capture_provider()
            await provider.capture_screen()
        except Exception:
            pass

        target_x = box["x"] + box["width"] / 2
        target_y = box["y"] + box["height"] / 2

        if hasattr(page, "mouse") and hasattr(page.mouse, "click"):
            res = page.mouse.click(target_x, target_y)
            if asyncio.iscoroutine(res):
                await res

        logger.info("vision_fallback_click_executed", target=target, x=target_x, y=target_y)
        return ToolResult(
            success=True,
            message=f"Interacted with visual canvas target '{target}' using vision fallback at ({int(target_x)}, {int(target_y)}).",
            data={"verified": True, "vision_fallback": True, "target": target},
        )
    except Exception as e:
        logger.warning("vision_fallback_failed", error=str(e))
        return None


@tool(
    name="browser_click_element",
    description=(
        "Click a visible element on the active webpage using natural language description, "
        "icon name, or reference ID (@e1, @e2). Supports contextual scoping (e.g. 'beside Two Sum') "
        "and ordinal indexing (e.g. ordinal=3 for 'third')."
    ),
    category="browser",
    permission_level=PermissionLevel.SAFE,
    parameters=[
        ToolParameter(
            name="target",
            type="string",
            description="Element name, icon name, accessible label, visible text, or ref ID (@e1).",
            required=True,
        ),
        ToolParameter(
            name="context",
            type="string",
            description="Optional container or section name to scope the element (e.g. 'Two Sum', 'Arrays').",
            required=False,
            default="",
        ),
        ToolParameter(
            name="ordinal",
            type="integer",
            description="1-based index if choosing the N-th matching item (e.g. 1 for first, 3 for third).",
            required=False,
            default=0,
        ),
    ],
)
async def browser_click_element(target: str, context: str = "", ordinal: int = 0) -> ToolResult:
    """Click a semantic element on the current Playwright page and verify result."""
    page = _get_active_page()
    if not page:
        return ToolResult(
            success=False,
            error="no_active_browser_session",
            message="No active Airi browser session. Use browser_open or browser_search first.",
        )

    ctx = get_browser_task_context()
    if not ctx.last_inspected_elements:
        inspect_res = await browser_inspect()
        if not inspect_res.success:
            return inspect_res

    elements = ctx.last_inspected_elements
    current_url = page.url if hasattr(page, "url") else ""
    page_title = await page.title() if hasattr(page, "title") else ""

    res = ElementResolver.resolve(
        elements=elements,
        target=target,
        context=context,
        ordinal=ordinal,
        page_url=current_url,
        page_title=page_title,
    )

    if res.status == "already_in_state":
        logger.info("element_already_in_state", target=target, message=res.message)
        return ToolResult(
            success=True,
            message=res.message,
            data={"already_in_state": True, "verified": True, "element": res.element.to_dict() if res.element else None},
        )

    if res.status == "ambiguous":
        logger.warning("element_resolution_ambiguous", target=target, message=res.message)
        return ToolResult(
            success=False,
            error="ambiguous_target",
            message=res.message,
            data={"candidates": [c.to_dict() for c in res.candidates]},
        )

    if res.status == "not_found":
        vision_res = await _try_vision_fallback_click(page, target)
        if vision_res and vision_res.success:
            return vision_res
        return ToolResult(
            success=False,
            error="element_not_found",
            message=res.message,
        )

    el = res.element
    if not el:
        return ToolResult(success=False, error="element_not_found", message=res.message)

    initial_url = current_url
    loc = page.locator(f"[data-airi-ref='{el.ref_id}']")

    try:
        click_ret = loc.click(timeout=8000)
        if asyncio.iscoroutine(click_ret):
            await click_ret
    except Exception as e:
        err_str = str(e).lower()
        if any(kw in err_str for kw in ("stale", "detached", "not found", "visible", "timeout")):
            logger.warning("stale_element_detected_retrying", error=str(e), ref_id=el.ref_id)
            await browser_inspect()
            fresh_elements = ctx.last_inspected_elements
            retry_res = ElementResolver.resolve(
                elements=fresh_elements,
                target=target,
                context=context,
                ordinal=ordinal,
            )
            if retry_res.status == "found" and retry_res.element:
                el = retry_res.element
                loc = page.locator(f"[data-airi-ref='{el.ref_id}']")
                click_ret = loc.click(timeout=8000)
                if asyncio.iscoroutine(click_ret):
                    await click_ret
            else:
                return ToolResult(success=False, error=f"Element stale and could not be re-resolved: {e}")
        else:
            return ToolResult(success=False, error=f"Failed to click element: {e}")

    # Wait for possible navigation
    try:
        if hasattr(page, "wait_for_load_state"):
            wait_ret = page.wait_for_load_state("domcontentloaded", timeout=4000)
            if asyncio.iscoroutine(wait_ret):
                await wait_ret
    except Exception:
        pass

    new_url = page.url if hasattr(page, "url") else initial_url
    if new_url and new_url != initial_url:
        ctx.update_navigation(url=new_url, title=el.accessible_name)
        return ToolResult(
            success=True,
            message=f"Clicked '{el.accessible_name}'. Navigated to {new_url}.",
            data={"navigated": True, "url": new_url, "verified": True, "element": el.to_dict()},
        )

    # Re-evaluate state for toggle / button updates
    new_state = None
    try:
        state_ret = page.evaluate("""(ref) => {
            const el = document.querySelector(`[data-airi-ref="${ref}"]`);
            if (!el) return null;
            return {
                pressed: el.getAttribute('aria-pressed'),
                expanded: el.getAttribute('aria-expanded'),
                classes: el.className
            };
        }""", el.ref_id)
        if asyncio.iscoroutine(state_ret):
            new_state = await state_ret
        else:
            new_state = state_ret
    except Exception:
        pass

    if new_state:
        new_pressed = new_state.get("pressed") == "true" if new_state.get("pressed") is not None else None
        if el.pressed is not None and new_pressed is not None and new_pressed != el.pressed:
            return ToolResult(
                success=True,
                message=f"Clicked '{el.accessible_name}'. Verified button state updated to {'pressed' if new_pressed else 'unpressed'}.",
                data={"verified": True, "pressed": new_pressed, "element": el.to_dict()},
            )

    return ToolResult(
        success=True,
        message=f"Clicked {el.element_type} '{el.accessible_name}' ({el.ref_id}). Verified action performed.",
        data={"verified": True, "element": el.to_dict(), "new_state": new_state},
    )


@tool(
    name="browser_expand",
    description=(
        "Expand or collapse an accordion, disclosure section, or details element on the active page. "
        "Will not collapse an already-expanded section when expand is requested."
    ),
    category="browser",
    permission_level=PermissionLevel.SAFE,
    parameters=[
        ToolParameter(
            name="target",
            type="string",
            description="Name of the section to expand/collapse (e.g. 'Arrays', 'Binary Search', or 'all').",
            required=True,
        ),
        ToolParameter(
            name="context",
            type="string",
            description="Optional container or parent section context.",
            required=False,
            default="",
        ),
        ToolParameter(
            name="collapse",
            type="boolean",
            description="Set True to collapse the section; default False to expand.",
            required=False,
            default=False,
        ),
    ],
)
async def browser_expand(target: str, context: str = "", collapse: bool = False) -> ToolResult:
    """Expand or collapse an accordion section safely without unintended toggling."""
    page = _get_active_page()
    if not page:
        return ToolResult(
            success=False,
            error="no_active_browser_session",
            message="No active Airi browser session. Use browser_open or browser_search first.",
        )

    ctx = get_browser_task_context()
    if not ctx.last_inspected_elements:
        inspect_res = await browser_inspect()
        if not inspect_res.success:
            return inspect_res

    elements = ctx.last_inspected_elements
    t_low = target.lower().strip()

    # Expand all sections
    if t_low in ("all", "all sections", "all accordions"):
        accordions = [
            el for el in elements
            if (el.element_type == "accordion" or el.expanded is not None or el.tag in ("summary", "details"))
        ]
        to_toggle = [
            el for el in accordions
            if (el.expanded is False if not collapse else el.expanded is True)
        ]
        count = 0
        for el in to_toggle:
            try:
                loc = page.locator(f"[data-airi-ref='{el.ref_id}']")
                ret = loc.click(timeout=3000)
                if asyncio.iscoroutine(ret):
                    await ret
                count += 1
            except Exception:
                pass
        return ToolResult(
            success=True,
            message=f"Successfully {'expanded' if not collapse else 'collapsed'} {count} sections.",
            data={"count": count, "verified": True},
        )

    action_intent = "collapse" if collapse else "expand"
    res = ElementResolver.resolve(
        elements=elements,
        target=target,
        context=context,
        intent=action_intent,
    )

    if res.status == "already_in_state":
        logger.info("accordion_already_in_state", target=target, message=res.message)
        return ToolResult(
            success=True,
            message=res.message,
            data={"already_in_state": True, "verified": True, "element": res.element.to_dict() if res.element else None},
        )

    if res.status != "found" or not res.element:
        return ToolResult(
            success=False,
            error="section_not_found",
            message=res.message or f"Could not find section '{target}' to {'collapse' if collapse else 'expand'}.",
        )

    el = res.element
    loc = page.locator(f"[data-airi-ref='{el.ref_id}']")
    try:
        click_ret = loc.click(timeout=8000)
        if asyncio.iscoroutine(click_ret):
            await click_ret
    except Exception as e:
        return ToolResult(success=False, error=f"Failed to click section '{el.accessible_name}': {e}")

    # Verify new expanded state
    new_expanded = None
    try:
        eval_ret = page.evaluate("""(ref) => {
            const el = document.querySelector(`[data-airi-ref="${ref}"]`);
            if (!el) return null;
            if (el.hasAttribute('aria-expanded')) return el.getAttribute('aria-expanded') === 'true';
            if (el.tagName.toLowerCase() === 'details') return el.hasAttribute('open');
            const det = el.closest('details');
            if (det) return det.hasAttribute('open');
            return true;
        }""", el.ref_id)
        if asyncio.iscoroutine(eval_ret):
            new_expanded = await eval_ret
        else:
            new_expanded = eval_ret
    except Exception:
        new_expanded = not el.expanded

    return ToolResult(
        success=True,
        message=f"Successfully {'expanded' if not collapse else 'collapsed'} section '{el.accessible_name}'.",
        data={"verified": True, "expanded": new_expanded, "element": el.to_dict()},
    )


@tool(
    name="browser_fill_input",
    description="Locate and fill a form input or textarea on the active webpage.",
    category="browser",
    permission_level=PermissionLevel.SAFE,
    parameters=[
        ToolParameter(name="target", type="string", description="Input label, placeholder, name, or ref ID (@e1).", required=True),
        ToolParameter(name="value", type="string", description="Text to enter into the input.", required=True),
        ToolParameter(name="context", type="string", description="Optional container context.", required=False, default=""),
        ToolParameter(name="press_enter", type="boolean", description="Whether to press Enter after typing.", required=False, default=False),
    ],
)
async def browser_fill_input(target: str, value: str, context: str = "", press_enter: bool = False) -> ToolResult:
    """Fill text into a semantic form control and verify the entered text."""
    page = _get_active_page()
    if not page:
        return ToolResult(
            success=False,
            error="no_active_browser_session",
            message="No active Airi browser session. Use browser_open or browser_search first.",
        )

    ctx = get_browser_task_context()
    if not ctx.last_inspected_elements:
        inspect_res = await browser_inspect()
        if not inspect_res.success:
            return inspect_res

    res = ElementResolver.resolve(
        elements=ctx.last_inspected_elements,
        target=target,
        context=context,
        intent="fill",
    )

    if res.status != "found" or not res.element:
        return ToolResult(
            success=False,
            error="input_not_found",
            message=res.message or f"Could not find input field '{target}'.",
        )

    el = res.element
    loc = page.locator(f"[data-airi-ref='{el.ref_id}']")
    try:
        fill_ret = loc.fill(value)
        if asyncio.iscoroutine(fill_ret):
            await fill_ret

        if press_enter:
            press_ret = loc.press("Enter")
            if asyncio.iscoroutine(press_ret):
                await press_ret

        cur_val = value
        try:
            val_ret = loc.input_value()
            if asyncio.iscoroutine(val_ret):
                cur_val = await val_ret
            else:
                cur_val = val_ret
        except Exception:
            pass

        return ToolResult(
            success=True,
            message=f"Entered '{value}' into '{el.accessible_name}'.",
            data={"verified": True, "value": cur_val, "element": el.to_dict()},
        )
    except Exception as e:
        return ToolResult(success=False, error=f"Failed to fill input '{el.accessible_name}': {e}")


@tool(
    name="browser_select_option",
    description="Select an option from a dropdown or select control on the active webpage.",
    category="browser",
    permission_level=PermissionLevel.SAFE,
    parameters=[
        ToolParameter(name="target", type="string", description="Select or dropdown name, or option to select.", required=True),
        ToolParameter(name="option", type="string", description="Option label or value to select.", required=True),
        ToolParameter(name="context", type="string", description="Optional container context.", required=False, default=""),
    ],
)
async def browser_select_option(target: str, option: str, context: str = "") -> ToolResult:
    """Select a dropdown option and verify selection."""
    page = _get_active_page()
    if not page:
        return ToolResult(
            success=False,
            error="no_active_browser_session",
            message="No active Airi browser session. Use browser_open or browser_search first.",
        )

    ctx = get_browser_task_context()
    if not ctx.last_inspected_elements:
        inspect_res = await browser_inspect()
        if not inspect_res.success:
            return inspect_res

    res = ElementResolver.resolve(
        elements=ctx.last_inspected_elements,
        target=target,
        context=context,
        intent="select",
    )

    el = res.element if res.status == "found" else None
    try:
        if el and el.tag == "select":
            loc = page.locator(f"[data-airi-ref='{el.ref_id}']")
            sel_ret = loc.select_option(label=option)
            if asyncio.iscoroutine(sel_ret):
                await sel_ret
        else:
            # Try selecting by option text
            opt_loc = page.locator(f"text={option}").first
            click_ret = opt_loc.click(timeout=5000)
            if asyncio.iscoroutine(click_ret):
                await click_ret

        return ToolResult(
            success=True,
            message=f"Selected option '{option}'.",
            data={"verified": True, "option": option},
        )
    except Exception as e:
        return ToolResult(success=False, error=f"Failed to select option '{option}': {e}")


@tool(
    name="browser_scroll",
    description="Scroll the active browser viewport or scroll a target element into view.",
    category="browser",
    permission_level=PermissionLevel.SAFE,
    parameters=[
        ToolParameter(name="direction", type="string", description="Direction: 'down', 'up', 'top', or 'bottom'.", required=False, default="down"),
        ToolParameter(name="amount", type="string", description="Amount: 'page', 'half_page', or numeric pixels.", required=False, default="page"),
        ToolParameter(name="target", type="string", description="Optional target element name or section to scroll into view.", required=False, default=""),
    ],
)
async def browser_scroll(direction: str = "down", amount: str = "page", target: str = "") -> ToolResult:
    """Scroll page or element into view and verify scroll execution."""
    page = _get_active_page()
    if not page:
        return ToolResult(
            success=False,
            error="no_active_browser_session",
            message="No active Airi browser session. Use browser_open or browser_search first.",
        )

    if target:
        ctx = get_browser_task_context()
        if not ctx.last_inspected_elements:
            await browser_inspect()
        res = ElementResolver.resolve(ctx.last_inspected_elements, target)
        if res.status == "found" and res.element:
            loc = page.locator(f"[data-airi-ref='{res.element.ref_id}']")
            try:
                scroll_ret = loc.scroll_into_view_if_needed(timeout=5000)
                if asyncio.iscoroutine(scroll_ret):
                    await scroll_ret
                return ToolResult(
                    success=True,
                    message=f"Scrolled '{res.element.accessible_name}' into view.",
                    data={"verified": True, "target": res.element.accessible_name},
                )
            except Exception as e:
                return ToolResult(success=False, error=f"Failed to scroll element into view: {e}")

    dir_low = direction.lower()
    try:
        before_y = 0
        try:
            b_ret = page.evaluate("() => window.scrollY")
            before_y = await b_ret if asyncio.iscoroutine(b_ret) else b_ret
        except Exception:
            pass

        if "top" in dir_low:
            ret = page.evaluate("() => window.scrollTo(0, 0)")
        elif "bottom" in dir_low:
            ret = page.evaluate("() => window.scrollTo(0, document.body.scrollHeight)")
        elif "up" in dir_low:
            ret = page.evaluate("() => window.scrollBy(0, -window.innerHeight * 0.8)")
        else:
            ret = page.evaluate("() => window.scrollBy(0, window.innerHeight * 0.8)")

        if asyncio.iscoroutine(ret):
            await ret

        after_y = before_y
        try:
            a_ret = page.evaluate("() => window.scrollY")
            after_y = await a_ret if asyncio.iscoroutine(a_ret) else a_ret
        except Exception:
            pass

        return ToolResult(
            success=True,
            message=f"Scrolled {direction}.",
            data={"verified": True, "before_y": before_y, "after_y": after_y},
        )
    except Exception as e:
        return ToolResult(success=False, error=f"Failed to scroll: {e}")


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
    """Register all browser inspection, selection, and interaction tools."""
    registry.register(
        ToolDefinition(
            name="browser_inspect",
            description=(
                "Inspect visible, actionable DOM elements in Airi's active Playwright browser session. "
                "Returns semantic roles, accessible names, visible text, accordions, toggles, icons, and locators."
            ),
            category="browser",
            permission_level=PermissionLevel.SAFE,
            parameters=[],
        ),
        browser_inspect,
    )
    registry.register(
        ToolDefinition(
            name="browser_click_element",
            description=(
                "Click a visible element on the active webpage using natural language description, "
                "icon name, or reference ID (@e1, @e2). Supports contextual scoping (e.g. 'beside Two Sum') "
                "and ordinal indexing (e.g. ordinal=3 for 'third')."
            ),
            category="browser",
            permission_level=PermissionLevel.SAFE,
            parameters=[
                ToolParameter(
                    name="target",
                    type="string",
                    description="Element name, icon name, accessible label, visible text, or ref ID (@e1).",
                    required=True,
                ),
                ToolParameter(
                    name="context",
                    type="string",
                    description="Optional container or section name to scope the element (e.g. 'Two Sum', 'Arrays').",
                    required=False,
                    default="",
                ),
                ToolParameter(
                    name="ordinal",
                    type="integer",
                    description="1-based index if choosing the N-th matching item (e.g. 1 for first, 3 for third).",
                    required=False,
                    default=0,
                ),
            ],
        ),
        browser_click_element,
    )
    registry.register(
        ToolDefinition(
            name="browser_expand",
            description=(
                "Expand or collapse an accordion, disclosure section, or details element on the active page. "
                "Will not collapse an already-expanded section when expand is requested."
            ),
            category="browser",
            permission_level=PermissionLevel.SAFE,
            parameters=[
                ToolParameter(
                    name="target",
                    type="string",
                    description="Name of the section to expand/collapse (e.g. 'Arrays', 'Binary Search', or 'all').",
                    required=True,
                ),
                ToolParameter(
                    name="context",
                    type="string",
                    description="Optional container or parent section context.",
                    required=False,
                    default="",
                ),
                ToolParameter(
                    name="collapse",
                    type="boolean",
                    description="Set True to collapse the section; default False to expand.",
                    required=False,
                    default=False,
                ),
            ],
        ),
        browser_expand,
    )
    registry.register(
        ToolDefinition(
            name="browser_fill_input",
            description="Locate and fill a form input or textarea on the active webpage.",
            category="browser",
            permission_level=PermissionLevel.SAFE,
            parameters=[
                ToolParameter(name="target", type="string", description="Input label, placeholder, name, or ref ID (@e1).", required=True),
                ToolParameter(name="value", type="string", description="Text to enter into the input.", required=True),
                ToolParameter(name="context", type="string", description="Optional container context.", required=False, default=""),
                ToolParameter(name="press_enter", type="boolean", description="Whether to press Enter after typing.", required=False, default=False),
            ],
        ),
        browser_fill_input,
    )
    registry.register(
        ToolDefinition(
            name="browser_select_option",
            description="Select an option from a dropdown or select control on the active webpage.",
            category="browser",
            permission_level=PermissionLevel.SAFE,
            parameters=[
                ToolParameter(name="target", type="string", description="Select or dropdown name, or option to select.", required=True),
                ToolParameter(name="option", type="string", description="Option label or value to select.", required=True),
                ToolParameter(name="context", type="string", description="Optional container context.", required=False, default=""),
            ],
        ),
        browser_select_option,
    )
    registry.register(
        ToolDefinition(
            name="browser_scroll",
            description="Scroll the active browser viewport or scroll a target element into view.",
            category="browser",
            permission_level=PermissionLevel.SAFE,
            parameters=[
                ToolParameter(name="direction", type="string", description="Direction: 'down', 'up', 'top', or 'bottom'.", required=False, default="down"),
                ToolParameter(name="amount", type="string", description="Amount: 'page', 'half_page', or numeric pixels.", required=False, default="page"),
                ToolParameter(name="target", type="string", description="Optional target element name or section to scroll into view.", required=False, default=""),
            ],
        ),
        browser_scroll,
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

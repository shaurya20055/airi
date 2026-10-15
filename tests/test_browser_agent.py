"""Comprehensive regression and integration tests for Airi's General-Purpose Browser Agent.

Covers the 16 core requirements:
1. Clicking a semantic button by accessible name.
2. Clicking a button with an icon and no visible text.
3. Expanding a collapsed accordion.
4. Leaving an already-expanded accordion open.
5. Selecting an item inside the correct parent section.
6. Clicking the correct link within a problem row/card.
7. Selecting the correct ordinal item within a list.
8. Handling duplicate button names through contextual resolution.
9. Handling missing targets without arbitrary clicks.
10. Detecting stale element references and reinspecting.
11. Verifying button/toggle state after an interaction.
12. Refusing to claim success when operation fails or verification fails.
13. Preserving browser context across voice turns.
14. Registering every required tool in the real voice/CLI runtime.
15. Keeping existing YouTube search and first-video selection functional.
16. Handling a website with no useful accessible labels through vision fallback.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from playwright.async_api import async_playwright

from app.agent.orchestrator import AgentOrchestrator
from app.agent.task_context import (
    BrowserTaskContext,
    get_browser_task_context,
    is_browser_interaction_command,
    parse_browser_interaction,
    set_browser_task_context,
)
from app.ai.providers.local.provider import LocalProvider
from app.ai.router import AIRouter
from app.ai.schemas import AIResponse, ToolCall
from app.core.events.bus import EventBus
from app.core.permissions.browser_policy import BrowserPolicy
from app.core.permissions.levels import PermissionLevel as CorePermissionLevel
from app.core.permissions.manager import PermissionManager
from app.memory.store import MemoryStore
from app.tools import register_all_tools
from app.tools.browser.inspection import (
    browser_click_element,
    browser_expand,
    browser_fill_input,
    browser_inspect,
    browser_scroll,
    browser_select_first,
    browser_select_option,
)
from app.tools.browser.resolver import ElementResolver, InspectedElement
from app.tools.registry import ToolRegistry, ToolResult


HTML_FIXTURE = """<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>Airi Test Suite Dashboard</title>
</head>
<body>
  <header>
    <h1>Problem Sheet</h1>
    <!-- Toggle Buttons -->
    <button id="like-btn" aria-label="Like this video" aria-pressed="false" onclick="this.setAttribute('aria-pressed', this.getAttribute('aria-pressed')==='true'?'false':'true')">Like</button>
    <button id="sub-btn" aria-label="Subscribe to this channel" aria-pressed="false" onclick="this.setAttribute('aria-pressed', this.getAttribute('aria-pressed')==='true'?'false':'true')">Subscribe</button>
    <!-- Icon Button without visible text -->
    <button id="settings-btn" title="Settings" class="icon-settings" onclick="window.settingsClicked = true">
      <svg><title>settings</title></svg>
    </button>
  </header>

  <main>
    <!-- Section 1: Accordion (Arrays) - Collapsed -->
    <details id="sec-arrays" class="accordion">
      <summary id="sum-arrays">Arrays</summary>
      <div class="content">
        <table id="tbl-arrays">
          <tr id="row-two-sum">
            <td>Two Sum</td>
            <td><button class="solve-btn" id="solve-two-sum" onclick="window.solvedProblem='Two Sum'">Solve</button></td>
            <td>
              <a href="https://leetcode.com/problems/two-sum" class="leetcode-link" title="LeetCode">
                <svg><title>leetcode</title></svg>
              </a>
            </td>
          </tr>
          <tr id="row-three-sum">
            <td>3Sum</td>
            <td><button class="solve-btn" id="solve-three-sum" onclick="window.solvedProblem='3Sum'">Solve</button></td>
            <td>
              <a href="https://leetcode.com/problems/3sum" class="leetcode-link" title="LeetCode">
                <svg><title>leetcode</title></svg>
              </a>
            </td>
          </tr>
          <tr id="row-four-sum">
            <td>4Sum</td>
            <td><button class="solve-btn" id="solve-four-sum" onclick="window.solvedProblem='4Sum'">Solve</button></td>
            <td>
              <a href="https://leetcode.com/problems/4sum" class="leetcode-link" title="LeetCode">
                <svg><title>leetcode</title></svg>
              </a>
            </td>
          </tr>
        </table>
      </div>
    </details>

    <!-- Section 2: Accordion (Binary Search) - Already Expanded -->
    <details id="sec-bs" class="accordion" open>
      <summary id="sum-bs">Binary Search</summary>
      <div class="content">
        <div class="card" id="card-search-rotated">
          <h3>Search in Rotated Sorted Array</h3>
          <button class="solve-btn" id="solve-bs" onclick="window.solvedProblem='Binary Search'">Solve</button>
          <a href="https://leetcode.com/problems/search-in-rotated-sorted-array" class="leetcode-link" title="LeetCode">
            <svg><title>leetcode</title></svg>
          </a>
        </div>
      </div>
    </details>

    <!-- Section 3: Forms and Selects -->
    <section id="sec-forms">
      <h2>Preferences</h2>
      <select id="lang-select" aria-label="Programming Language">
        <option value="python">Python</option>
        <option value="java">Java</option>
        <option value="cpp">C++</option>
      </select>
      <input type="text" id="query-input" placeholder="Search problems" />
    </section>

    <!-- Section 4: Canvas Interface (No DOM buttons) -->
    <section id="sec-canvas">
      <h2>Visual Canvas Playground</h2>
      <canvas id="game-canvas" width="400" height="300"></canvas>
    </section>
  </main>
</body>
</html>
"""


@pytest.fixture(autouse=True)
def reset_browser_context():
    """Reset browser context before and after each test."""
    ctx = BrowserTaskContext()
    set_browser_task_context(ctx)
    yield ctx
    set_browser_task_context(BrowserTaskContext())


@pytest.fixture
async def real_playwright_page():
    """Launch a real headless Playwright Firefox browser with the deterministic HTML fixture."""
    async with async_playwright() as p:
        browser = await p.firefox.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()
        await page.set_content(HTML_FIXTURE)
        yield page
        await browser.close()


# ==============================================================================
# REAL BROWSER TESTS (Executed against real Playwright Firefox session)
# ==============================================================================

@pytest.mark.asyncio
async def test_1_click_semantic_button_by_accessible_name(real_playwright_page):
    """1. Click a semantic button by its accessible name (REAL BROWSER)."""
    with patch("app.tools.browser.inspection._get_active_page", return_value=real_playwright_page):
        # Inspect page first
        inspect_res = await browser_inspect()
        assert inspect_res.success
        assert inspect_res.data["element_count"] > 0

        # Click the Like button
        result = await browser_click_element(target="Like this video")
        assert result.success
        assert result.data["verified"] is True
        assert "Like" in result.message


@pytest.mark.asyncio
async def test_2_click_icon_button_no_visible_text(real_playwright_page):
    """2. Click a button with an icon and no visible text (REAL BROWSER)."""
    with patch("app.tools.browser.inspection._get_active_page", return_value=real_playwright_page):
        await browser_inspect()
        result = await browser_click_element(target="Settings")
        assert result.success
        assert result.data["verified"] is True
        clicked = await real_playwright_page.evaluate("() => !!window.settingsClicked")
        assert clicked is True


@pytest.mark.asyncio
async def test_3_expand_collapsed_accordion(real_playwright_page):
    """3. Expand a collapsed accordion (REAL BROWSER)."""
    with patch("app.tools.browser.inspection._get_active_page", return_value=real_playwright_page):
        await browser_inspect()
        # Verify initial collapsed state
        init_open = await real_playwright_page.evaluate("() => document.querySelector('#sec-arrays').hasAttribute('open')")
        assert init_open is False

        # Expand Arrays section
        res = await browser_expand(target="Arrays", collapse=False)
        assert res.success
        assert res.data["verified"] is True
        assert res.data["expanded"] is True

        # Verify page state
        now_open = await real_playwright_page.evaluate("() => document.querySelector('#sec-arrays').hasAttribute('open')")
        assert now_open is True


@pytest.mark.asyncio
async def test_4_leave_already_expanded_accordion_open(real_playwright_page):
    """4. Leaving an already-expanded accordion open (no accidental toggle) (REAL BROWSER)."""
    with patch("app.tools.browser.inspection._get_active_page", return_value=real_playwright_page):
        await browser_inspect()
        # Binary Search is already expanded (open=True)
        init_open = await real_playwright_page.evaluate("() => document.querySelector('#sec-bs').hasAttribute('open')")
        assert init_open is True

        res = await browser_expand(target="Binary Search", collapse=False)
        assert res.success
        assert res.data["already_in_state"] is True
        assert "already expanded" in res.message

        # Verify still open!
        still_open = await real_playwright_page.evaluate("() => document.querySelector('#sec-bs').hasAttribute('open')")
        assert still_open is True


@pytest.mark.asyncio
async def test_5_select_item_inside_correct_parent_section(real_playwright_page):
    """5. Selecting an item inside the correct parent section (REAL BROWSER)."""
    with patch("app.tools.browser.inspection._get_active_page", return_value=real_playwright_page):
        # Open arrays so buttons are visible
        await real_playwright_page.evaluate("() => document.querySelector('#sec-arrays').setAttribute('open', '')")
        await browser_inspect()

        # Click Solve inside Binary Search
        res = await browser_click_element(target="Solve", context="Binary Search")
        assert res.success
        assert res.data["verified"] is True

        solved = await real_playwright_page.evaluate("() => window.solvedProblem")
        assert solved == "Binary Search"


@pytest.mark.asyncio
async def test_6_click_link_within_problem_row(real_playwright_page):
    """6. Clicking the correct link within a problem row/card (REAL BROWSER)."""
    with patch("app.tools.browser.inspection._get_active_page", return_value=real_playwright_page):
        # Open arrays
        await real_playwright_page.evaluate("() => document.querySelector('#sec-arrays').setAttribute('open', '')")
        await browser_inspect()

        # Target the LeetCode icon specifically for Two Sum
        res = await browser_click_element(target="LeetCode icon beside Two Sum")
        assert res.success
        # Destination is leetcode.com/problems/two-sum
        assert "two-sum" in res.data["element"]["href"] or "two-sum" in res.data.get("url", "")


@pytest.mark.asyncio
async def test_7_select_ordinal_item_within_list(real_playwright_page):
    """7. Selecting the correct ordinal item within a list (REAL BROWSER)."""
    with patch("app.tools.browser.inspection._get_active_page", return_value=real_playwright_page):
        await real_playwright_page.evaluate("() => document.querySelector('#sec-arrays').setAttribute('open', '')")
        await browser_inspect()

        # Solve the third problem in this section (4Sum)
        res = await browser_click_element(target="Solve", ordinal=3)
        assert res.success
        solved = await real_playwright_page.evaluate("() => window.solvedProblem")
        assert solved == "4Sum"


@pytest.mark.asyncio
async def test_8_handle_duplicate_button_names_via_context(real_playwright_page):
    """8. Handling duplicate button names through contextual resolution (REAL BROWSER)."""
    with patch("app.tools.browser.inspection._get_active_page", return_value=real_playwright_page):
        await real_playwright_page.evaluate("() => document.querySelector('#sec-arrays').setAttribute('open', '')")
        await browser_inspect()

        # Solve button for 3Sum specifically
        res = await browser_click_element(target="Solve", context="3Sum")
        assert res.success
        solved = await real_playwright_page.evaluate("() => window.solvedProblem")
        assert solved == "3Sum"


@pytest.mark.asyncio
async def test_9_handle_missing_target_without_arbitrary_clicks(real_playwright_page):
    """9. Handling missing targets without arbitrary clicks (REAL BROWSER)."""
    with patch("app.tools.browser.inspection._get_active_page", return_value=real_playwright_page):
        await browser_inspect()

        res = await browser_click_element(target="NonExistentSuperButton12345")
        assert res.success is False
        assert res.error == "element_not_found"

        # Verify no solve button was clicked
        solved = await real_playwright_page.evaluate("() => window.solvedProblem || null")
        assert solved is None


@pytest.mark.asyncio
async def test_10_detect_stale_element_and_reinspect(real_playwright_page):
    """10. Detecting stale element references and reinspecting (REAL BROWSER)."""
    with patch("app.tools.browser.inspection._get_active_page", return_value=real_playwright_page):
        # Initial inspect
        await browser_inspect()
        ctx = get_browser_task_context()
        assert len(ctx.last_inspected_elements) > 0

        # Corrupt cached ref id to simulate stale element
        ctx.last_inspected_elements[0].ref_id = "@e_stale_invalid"

        # Click element - should recover by reinspecting
        res = await browser_click_element(target="Settings")
        assert res.success is True
        assert res.data["verified"] is True


@pytest.mark.asyncio
async def test_11_verify_toggle_button_state_after_interaction(real_playwright_page):
    """11. Verifying button/toggle state after an interaction (REAL BROWSER)."""
    with patch("app.tools.browser.inspection._get_active_page", return_value=real_playwright_page):
        await browser_inspect()

        # Initially Like button has aria-pressed="false"
        init_pressed = await real_playwright_page.evaluate("() => document.querySelector('#like-btn').getAttribute('aria-pressed')")
        assert init_pressed == "false"

        res = await browser_click_element(target="Like this video")
        assert res.success is True
        assert res.data["verified"] is True
        assert res.data["pressed"] is True

        # Verify DOM state
        new_pressed = await real_playwright_page.evaluate("() => document.querySelector('#like-btn').getAttribute('aria-pressed')")
        assert new_pressed == "true"


@pytest.mark.asyncio
async def test_16_screen_vision_fallback_for_canvas_or_unlabeled(real_playwright_page):
    """16. Handling visual canvas element with vision fallback (REAL BROWSER)."""
    with patch("app.tools.browser.inspection._get_active_page", return_value=real_playwright_page):
        await browser_inspect()

        with patch("app.tools.screen.provider.get_screen_capture_provider") as mock_provider:
            mock_provider.return_value.capture_screen = AsyncMock(return_value="/tmp/test.png")
            res = await browser_click_element(target="game canvas target")
            assert res.success is True
            assert res.data["vision_fallback"] is True
            assert "vision fallback" in res.message


@pytest.mark.asyncio
async def test_17_browser_fill_input_and_select_option(real_playwright_page):
    """Form controls: input typing and option selection (REAL BROWSER)."""
    with patch("app.tools.browser.inspection._get_active_page", return_value=real_playwright_page):
        await browser_inspect()

        # Fill input
        fill_res = await browser_fill_input(target="Search problems", value="sliding window")
        assert fill_res.success is True
        assert fill_res.data["value"] == "sliding window"

        input_val = await real_playwright_page.evaluate("() => document.querySelector('#query-input').value")
        assert input_val == "sliding window"

        # Select option
        sel_res = await browser_select_option(target="Programming Language", option="Java")
        assert sel_res.success is True
        sel_val = await real_playwright_page.evaluate("() => document.querySelector('#lang-select').value")
        assert sel_val == "java"


# ==============================================================================
# MOCKED AGENT ROUTING & ANTI-HALLUCINATION TESTS
# ==============================================================================

@pytest.mark.asyncio
async def test_12_refuse_success_on_failure_or_unverified(tmp_path):
    """12. Refusing to claim success when the operation fails or verification fails (MOCK)."""
    registry = ToolRegistry()
    register_all_tools(registry)
    event_bus = EventBus()
    permission_manager = PermissionManager(event_bus, cli_mode=True)
    permission_manager.request_permission = AsyncMock(return_value=True)
    memory = MemoryStore(str(tmp_path / "test_mem.db"))
    local_provider = LocalProvider()
    router = AIRouter(local_provider, cloud_provider=None)
    orchestrator = AgentOrchestrator(router, registry, memory, event_bus, permission_manager)

    # Set active browser context
    ctx = get_browser_task_context()
    ctx.update_navigation(url="https://example.com", title="Example")

    # Mock browser_click_element in registry to return verification failure
    def_tool, _ = registry.get_tool("browser_click_element")
    registry.register(
        def_tool,
        AsyncMock(return_value=ToolResult(success=False, error="verification_failed", message="Could not verify click.")),
    )

    resp = await orchestrator.process_input("Click the Settings button")
    # Must not report success or task completed
    assert "task completed" not in resp.lower()
    assert "error" in resp.lower() or "could not verify" in resp.lower()


@pytest.mark.asyncio
async def test_13_preserve_browser_context_across_turns(tmp_path):
    """13. Preserving browser context across multiple turns (MOCK)."""
    ctx = get_browser_task_context()
    ctx.update_search(
        browser_name="Firefox",
        query="Two Sum",
        site="leetcode",
        url="https://leetcode.com/problemset/all/",
        title="LeetCode",
    )
    assert ctx.has_active_session() is True

    # Turn 1: Check natural command recognizes active session
    assert is_browser_interaction_command("Expand the Arrays section") is True
    parsed = parse_browser_interaction("Expand the Arrays section")
    assert parsed["tool_name"] == "browser_expand"
    assert parsed["tool_args"]["target"] == "Arrays"

    # Turn 2: Check like command recognized
    assert is_browser_interaction_command("Like this video") is True
    parsed2 = parse_browser_interaction("Like this video")
    assert parsed2["tool_name"] == "browser_click_element"
    assert parsed2["tool_args"]["target"] == "like"

    # Turn 3: Context remains active
    assert ctx.current_url == "https://leetcode.com/problemset/all/"
    assert ctx.has_active_session() is True


def test_14_registry_has_all_browser_tools():
    """14. Registering every required tool in the real runtime."""
    registry = ToolRegistry()
    register_all_tools(registry)

    required_tools = [
        "browser_inspect",
        "browser_click_element",
        "browser_expand",
        "browser_fill_input",
        "browser_select_option",
        "browser_scroll",
        "browser_select_first",
        "browser_search_page",
        "browser_new_tab",
    ]

    registered = [t.name for t in registry.list_tools()]
    for tool_name in required_tools:
        assert tool_name in registered, f"Missing tool in ToolRegistry: {tool_name}"


@pytest.mark.asyncio
async def test_15_existing_youtube_search_and_select_first_functional():
    """15. Keeping existing YouTube search and first-video selection functional (MOCK)."""
    mock_page = AsyncMock()
    mock_page.url = "https://www.youtube.com/results?search_query=ElectroBOOM"

    video_renderers = AsyncMock()
    video_renderers.count.return_value = 1
    renderer = AsyncMock()
    ad_check = AsyncMock()
    ad_check.count.return_value = 0
    title_link = AsyncMock()
    title_link.count.return_value = 1
    first_link = AsyncMock()
    first_link.is_visible.return_value = True
    first_link.get_attribute.return_value = "/watch?v=123"
    first_link.text_content.return_value = "ElectroBOOM Video"
    title_link.first = first_link

    def rend_loc(sel):
        if "ad" in sel:
            return ad_check
        if sel == "a#video-title":
            return title_link
        return AsyncMock()

    renderer.locator.side_effect = rend_loc
    video_renderers.nth.return_value = renderer
    mock_page.locator.return_value = video_renderers

    async def mock_wait_url(pred, timeout=None):
        mock_page.url = "https://www.youtube.com/watch?v=123"

    mock_page.wait_for_url.side_effect = mock_wait_url

    with patch("app.tools.browser.inspection._get_active_page", return_value=mock_page):
        res = await browser_select_first(item_type="video", query="ElectroBOOM", index=1)
        assert res.success is True
        assert res.data["verified"] is True
        assert "ElectroBOOM Video" in res.message


def test_18_browser_policy_sensitive_operations():
    """18. BrowserPolicy correctly identifies sensitive actions requiring CONFIRM."""
    # Safe operations
    lvl, _ = BrowserPolicy.classify("browser_click_element", {"target": "Settings"})
    assert lvl == CorePermissionLevel.SAFE

    lvl, _ = BrowserPolicy.classify("browser_fill_input", {"target": "Search", "value": "python"})
    assert lvl == CorePermissionLevel.SAFE

    # Sensitive operations
    lvl, msg = BrowserPolicy.classify("browser_click_element", {"target": "Checkout and Pay Now"})
    assert lvl == CorePermissionLevel.CONFIRM
    assert "sensitive" in msg.lower()

    lvl, msg = BrowserPolicy.classify("browser_fill_input", {"target": "Password", "value": "secret123"})
    assert lvl == CorePermissionLevel.CONFIRM
    assert "sensitive" in msg.lower()


# ==============================================================================
# TESTS FOR FIXES: ISSUES 1 - 5 AND ANTI-HALLUCINATION INVARIANT
# ==============================================================================

@pytest.mark.asyncio
async def test_issue1_search_page_submits_query_and_verifies():
    """Issue 1: Search enters text into search field and submits via Enter."""
    from app.tools.browser.inspection import browser_search_page

    mock_page = AsyncMock()
    mock_page.url = "https://www.youtube.com"
    mock_page.title.return_value = "YouTube"

    search_input = AsyncMock()
    search_input.count.return_value = 1
    search_input.is_visible.return_value = True

    submit_btn = AsyncMock()
    submit_btn.count.return_value = 1
    submit_btn.is_visible.return_value = True

    def mock_locator(sel):
        if "input" in sel:
            m = AsyncMock()
            m.first = search_input
            m.count.return_value = 1
            return m
        if "button" in sel:
            m = AsyncMock()
            m.first = submit_btn
            m.count.return_value = 1
            return m
        m = AsyncMock()
        m.count.return_value = 0
        return m

    mock_page.locator.side_effect = mock_locator

    with patch("app.tools.browser.inspection._get_active_page", return_value=mock_page):
        res = await browser_search_page(query="ElectroBOOM")
        assert res.success is True
        assert res.data["verified"] is True
        assert res.data["query"] == "ElectroBOOM"
        search_input.fill.assert_called_with("ElectroBOOM")
        search_input.press.assert_called_with("Enter")


def test_issue2_like_dislike_disambiguation():
    """Issue 2: Like and Dislike buttons are not ambiguous and resolve accurately."""
    like_el = InspectedElement(
        ref_id="@e1", index=1, tag="button", role="button",
        accessible_name="Like this video", visible_text="Like",
        selector="button#like", element_type="button", pressed=False
    )
    dislike_el = InspectedElement(
        ref_id="@e2", index=2, tag="button", role="button",
        accessible_name="Dislike this video", visible_text="Dislike",
        selector="button#dislike", element_type="button", pressed=False
    )
    elements = [like_el, dislike_el]

    # Resolving "like this video" must return like_el and NEVER dislike_el
    res_like = ElementResolver.resolve(elements, target="like this video")
    assert res_like.status == "found"
    assert res_like.element.ref_id == "@e1"
    assert res_like.element.accessible_name == "Like this video"

    # Resolving "dislike this video" must return dislike_el
    res_dislike = ElementResolver.resolve(elements, target="dislike this video")
    assert res_dislike.status == "found"
    assert res_dislike.element.ref_id == "@e2"
    assert res_dislike.element.accessible_name == "Dislike this video"


def test_issue2_already_liked_returns_already_in_state():
    """Issue 2: Clicking Like on an already liked video returns already_in_state."""
    already_liked = InspectedElement(
        ref_id="@e1", index=1, tag="button", role="button",
        accessible_name="Like this video", visible_text="Like",
        selector="button#like", element_type="button", pressed=True
    )
    elements = [already_liked]

    res = ElementResolver.resolve(elements, target="like this video")
    assert res.status == "already_in_state"
    assert res.already_in_state is True


def test_issue3_share_button_discovery_and_noise_stripping():
    """Issue 3: 'share button' query strips noise words and resolves Share button."""
    clean, ctx_scope, ord_idx, intent = ElementResolver.parse_query("share button")
    assert clean == "share"
    assert intent == "share"

    share_el = InspectedElement(
        ref_id="@e5", index=5, tag="button", role="button",
        accessible_name="Share", visible_text="Share",
        selector="button#share", element_type="button", is_icon=True, icon_name="share"
    )
    other_el = InspectedElement(
        ref_id="@e6", index=6, tag="button", role="button",
        accessible_name="Download", visible_text="Download",
        selector="button#download", element_type="button"
    )

    res = ElementResolver.resolve([other_el, share_el], target="share button")
    assert res.status == "found"
    assert res.element.ref_id == "@e5"
    assert res.element.accessible_name == "Share"


@pytest.mark.asyncio
async def test_issue3_share_dialog_verification():
    """Issue 3: Clicking Share button verifies that share dialog opened."""
    mock_page = AsyncMock()
    mock_page.url = "https://www.youtube.com/watch?v=123"

    share_loc = AsyncMock()
    share_dialog = AsyncMock()
    share_dialog.count.return_value = 1

    def mock_loc(sel):
        if "@e1" in sel:
            return share_loc
        if "dialog" in sel or "share-target" in sel:
            return share_dialog
        m = AsyncMock()
        m.count.return_value = 0
        return m

    mock_page.locator.side_effect = mock_loc
    mock_page.evaluate.return_value = None

    share_el = InspectedElement(
        ref_id="@e1", index=1, tag="button", role="button",
        accessible_name="Share", visible_text="Share",
        selector="button#share", element_type="button", is_icon=True, icon_name="share"
    )

    ctx = get_browser_task_context()
    ctx.last_inspected_elements = [share_el]

    with patch("app.tools.browser.inspection._get_active_page", return_value=mock_page):
        res = await browser_click_element(target="Share")
        assert res.success is True
        assert res.data["verified"] is True
        assert res.data.get("dialog_open") is True


def test_issue4_sidebar_recommendation_resolution():
    """Issue 4: Recommended videos in YouTube sidebar are discovered and resolved."""
    rec_el = InspectedElement(
        ref_id="@e10", index=10, tag="a", role="link",
        accessible_name="How NOT to make an electric guitar",
        visible_text="How NOT to make an electric guitar",
        href="/watch?v=abc456",
        selector="ytd-compact-video-renderer a#video-title",
        element_type="link",
        parent_section="Sidebar > Recommendations",
        container_type="sidebar_recommendation"
    )
    elements = [rec_el]

    res = ElementResolver.resolve(elements, target="How NOT to make an electric guitar")
    assert res.status == "found"
    assert res.element.ref_id == "@e10"
    assert res.element.parent_section == "Sidebar > Recommendations"


def test_issue5_domain_aliases_normalization():
    """Issue 5: High-confidence domain phonetic aliases are accurately corrected."""
    from app.tools.browser.domain_aliases import normalize_domain_url

    url1, c1 = normalize_domain_url("leadcode.com")
    assert url1 == "https://leetcode.com"
    assert c1 is True

    url2, c2 = normalize_domain_url("you tube")
    assert url2 == "https://youtube.com"
    assert c2 is True

    url3, c3 = normalize_domain_url("git hub.com")
    assert url3 == "https://github.com"
    assert c3 is True

    # Arbitrary domains must not be altered
    url4, c4 = normalize_domain_url("unknownsite12345.org")
    assert url4 == "https://unknownsite12345.org"
    assert c4 is False


def test_issue5_new_tab_speech_intent_routing():
    """Issue 5: Spoken requests like 'In the new tab, open leadcode.com' route to browser_navigate with new_tab=True."""
    provider = LocalProvider()

    intent1 = provider.classify_intent("In the new tab, open leadcode.com")
    assert intent1.tool_name == "browser_navigate"
    assert intent1.tool_args["url"] == "https://leetcode.com"
    assert intent1.tool_args["new_tab"] is True

    intent2 = provider.classify_intent("open leadcode.com in a new tab")
    assert intent2.tool_name == "browser_navigate"
    assert intent2.tool_args["url"] == "https://leetcode.com"
    assert intent2.tool_args["new_tab"] is True

    intent3 = provider.classify_intent("open a new tab")
    assert intent3.tool_name == "browser_new_tab"


@pytest.mark.asyncio
async def test_antihallucination_rejects_conversational_claims():
    """Cross-cutting invariant: Orchestrator rejects model claims of action without tool execution."""
    registry = ToolRegistry()
    register_all_tools(registry)
    event_bus = EventBus()
    perm_mgr = PermissionManager(event_bus=event_bus)
    store = MemoryStore(":memory:")

    mock_router = AsyncMock()
    # Model generates pure conversational text claiming it navigated to a tab
    mock_router.process.return_value = AIResponse(
        text="Opened a new tab and navigating to leadcode.com.",
        tool_calls=[],
        finish_reason="stop",
    )

    orchestrator = AgentOrchestrator(
        router=mock_router,
        tool_registry=registry,
        memory=store,
        event_bus=event_bus,
        permission_manager=perm_mgr,
    )

    res = await orchestrator.process_input("In the new tab, open leadcode.com")
    # Must refuse to return the hallucinated completion message and report error
    assert "no tool was executed" in res.lower() or "unable to complete" in res.lower()


@pytest.mark.asyncio
async def test_antihallucination_rejects_inspection_only_action_claims():
    """Orchestrator rejects 'Task completed' when user asked for an action but only inspection was executed."""
    registry = ToolRegistry()
    register_all_tools(registry)
    event_bus = EventBus()
    perm_mgr = PermissionManager(event_bus=event_bus)
    store = MemoryStore(":memory:")

    mock_router = AsyncMock()
    mock_router.is_cloud_available = AsyncMock(return_value=True)
    # Step 0: inspects page. Step 1: claims completion without performing click. Step 2: fallback message.
    mock_router.process.side_effect = [
        AIResponse(
            text="",
            tool_calls=[ToolCall(id="c1", name="browser_inspect", arguments={})],
            finish_reason="tool_calls",
        ),
        AIResponse(
            text="Task completed. I clicked on the first video.",
            tool_calls=[],
            finish_reason="stop",
        ),
        AIResponse(
            text="I could not click the element.",
            tool_calls=[],
            finish_reason="stop",
        ),
    ]

    orchestrator = AgentOrchestrator(
        router=mock_router,
        tool_registry=registry,
        memory=store,
        event_bus=event_bus,
        permission_manager=perm_mgr,
    )

    # Patch browser_inspect execution to return success
    orchestrator.executor.execute = AsyncMock(return_value=ToolResult(success=True, message="Inspected 5 elements."))

    res = await orchestrator.process_input("Click the first video")
    # Must have looped to reject the inspection-only claim
    messages = orchestrator.context.get_messages()
    assert any("Action tool call required" in m.content for m in messages if m.role == "user")


@pytest.mark.asyncio
async def test_antihallucination_rejects_failed_tool_completion_claims():
    """Orchestrator halts loop and returns error when the executed tool failed, never claiming completion."""
    registry = ToolRegistry()
    register_all_tools(registry)
    event_bus = EventBus()
    perm_mgr = PermissionManager(event_bus=event_bus)
    store = MemoryStore(":memory:")

    mock_router = AsyncMock()
    # Step 0: calls click element (which fails).
    mock_router.process.side_effect = [
        AIResponse(
            text="",
            tool_calls=[ToolCall(id="c1", name="browser_click_element", arguments={"target": "Like"})],
            finish_reason="tool_calls",
        ),
        AIResponse(
            text="Task completed. I clicked the Like button.",
            tool_calls=[],
            finish_reason="stop",
        ),
    ]

    orchestrator = AgentOrchestrator(
        router=mock_router,
        tool_registry=registry,
        memory=store,
        event_bus=event_bus,
        permission_manager=perm_mgr,
    )

    # Mock tool executor to return a failed result
    orchestrator.executor.execute = AsyncMock(return_value=ToolResult(success=False, error="element_not_found"))

    res = await orchestrator.process_input("Like this video")
    assert "error" in res.lower()
    assert "element_not_found" in res.lower()
    assert "task completed" not in res.lower()


@pytest.mark.asyncio
async def test_ollama_runtime_timeout_error_handling():
    """OllamaRuntime handles httpx.TimeoutException gracefully with non-empty error message."""
    import httpx
    from app.ai.providers.local.ollama_runtime import OllamaRuntime
    from app.ai.schemas import Message

    runtime = OllamaRuntime(timeout=1.0)
    with patch("httpx.AsyncClient.post", side_effect=httpx.ReadTimeout("")):
        res = await runtime.respond(messages=[Message(role="user", content="hello")])
        assert res.finish_reason == "error"
        assert "timed out after 1 seconds" in res.text
        assert len(res.text) > 10


@pytest.mark.asyncio
async def test_ollama_runtime_connect_error_handling():
    """OllamaRuntime handles httpx.ConnectError gracefully with non-empty error message."""
    import httpx
    from app.ai.providers.local.ollama_runtime import OllamaRuntime
    from app.ai.schemas import Message

    runtime = OllamaRuntime(timeout=1.0)
    with patch("httpx.AsyncClient.post", side_effect=httpx.ConnectError("Connection refused")):
        res = await runtime.respond(messages=[Message(role="user", content="hello")])
        assert res.finish_reason == "error"
        assert "Could not connect to the local Ollama server" in res.text



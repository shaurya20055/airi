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

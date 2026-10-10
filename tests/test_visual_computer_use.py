"""Unit and integration tests for Phase 2: Visual Computer Use and Browser DOM Interaction."""
from __future__ import annotations

import asyncio
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.tools.screen.interaction import screen_click, screen_type, screen_press, screen_scroll
from app.tools.screen.provider import MonitorInfo, ActiveWindowInfo, ScreenCaptureProvider, set_screen_capture_provider, get_screen_capture_provider
from app.tools.browser.inspection import browser_inspect, browser_select_first


@pytest.fixture
def mock_screen_provider():
    """Mock provider with monitor scale 1.25 and 1920x1080 dimensions."""
    provider = ScreenCaptureProvider()
    provider.get_monitor_info = AsyncMock(return_value=[
        MonitorInfo(id=0, name="eDP-1", width=1920, height=1080, x=0, y=0, scale=1.25, focused=True)
    ])
    provider.get_active_window = AsyncMock(return_value=ActiveWindowInfo(
        address="0xabc", title="Browser Window", app_class="firefox", pid=999
    ))
    old = get_screen_capture_provider()
    set_screen_capture_provider(provider)
    yield provider
    set_screen_capture_provider(old)


# ── Screen Interaction Fallback Tests ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_coordinate_boundary_validation(mock_screen_provider):
    """Verify screen_click rejects coordinates outside monitor bounds."""
    # Out of bounds X (> 1920)
    res = await screen_click(x=2500, y=500, monitor=0)
    assert res.success is False
    assert "coordinates_out_of_bounds" in res.error

    # Negative Y (< 0)
    res2 = await screen_click(x=100, y=-50, monitor=0)
    assert res2.success is False
    assert "coordinates_out_of_bounds" in res2.error


@pytest.mark.asyncio
async def test_screen_click_scale_mapping(mock_screen_provider):
    """Verify coordinate scaling accounts for monitor scale factor (1.25)."""
    with patch("app.tools.screen.interaction._run_command") as mock_cmd, \
         patch("shutil.which", return_value="/usr/bin/ydotool"):
        mock_cmd.return_value = (0, "ok", "")

        # Target (1000, 500) physical pixels on 1.25x scaled display:
        # logical_x = int(1000 / 1.25) = 800
        # logical_y = int(500 / 1.25) = 400
        res = await screen_click(x=1000, y=500, monitor=0)
        assert res.success is True
        assert res.data["logical_x"] == 800
        assert res.data["logical_y"] == 400

        # Check ydotool command arguments
        first_call_args = mock_cmd.call_args_list[0][0][0]
        assert "mousemove" in first_call_args
        assert "800" in first_call_args
        assert "400" in first_call_args


@pytest.mark.asyncio
async def test_screen_type_wtype():
    """Verify screen_type invokes wtype with specified text."""
    with patch("app.tools.screen.interaction._run_command") as mock_cmd, \
         patch("shutil.which", return_value="/usr/bin/wtype"):
        mock_cmd.return_value = (0, "", "")

        res = await screen_type("echo 'hello airi'")
        assert res.success is True
        mock_cmd.assert_called_once_with(["wtype", "echo 'hello airi'"])


@pytest.mark.asyncio
async def test_screen_press_key_normalization():
    """Verify screen_press normalizes common key aliases to valid XKB key names."""
    with patch("app.tools.screen.interaction._run_command") as mock_cmd, \
         patch("shutil.which", return_value="/usr/bin/wtype"):
        mock_cmd.return_value = (0, "", "")

        # "enter" -> "Return"
        res = await screen_press("enter")
        assert res.success is True
        mock_cmd.assert_called_with(["wtype", "-k", "Return"])

        # "esc" -> "Escape"
        res2 = await screen_press("esc")
        assert res2.success is True
        mock_cmd.assert_called_with(["wtype", "-k", "Escape"])


# ── Browser DOM Inspection & First Result Resolution Tests ─────────────────────

@pytest.mark.asyncio
async def test_browser_inspect_no_active_session():
    """Verify browser_inspect fails gracefully if no Playwright session is open."""
    with patch("app.tools.browser.inspection._get_active_page", return_value=None):
        res = await browser_inspect()
        assert res.success is False
        assert "no_active_browser_session" in res.error


@pytest.mark.asyncio
async def test_browser_inspect_returns_structured_elements():
    """Verify browser_inspect extracts accessible names, roles, and selectors."""
    mock_page = AsyncMock()
    mock_page.title.return_value = "Search Results - Example"
    mock_page.url = "https://example.com/search"
    mock_page.evaluate.return_value = [
        {
            "role": "link",
            "accessible_name": "First Result Title",
            "visible_text": "First Result Title",
            "element_type": "a",
            "visible": True,
            "enabled": True,
            "link_destination": "https://example.com/item1",
            "is_ad": False,
            "selector": "a#item1",
        },
        {
            "role": "button",
            "accessible_name": "Submit",
            "visible_text": "Submit",
            "element_type": "button",
            "visible": True,
            "enabled": True,
            "link_destination": "",
            "is_ad": False,
            "selector": "button.submit",
        },
    ]

    with patch("app.tools.browser.inspection._get_active_page", return_value=mock_page):
        res = await browser_inspect()
        assert res.success is True
        assert res.data["element_count"] == 2
        assert res.data["elements"][0]["accessible_name"] == "First Result Title"
        assert res.data["untrusted_content"] is True


@pytest.mark.asyncio
async def test_browser_select_first_youtube_excludes_ads():
    """Verify browser_select_first filters out advertised items and clicks organic video."""
    mock_page = AsyncMock()
    mock_page.url = "https://www.youtube.com/results?search_query=electroboom"

    # Mock ytd-video-renderer items:
    # Item 0: Advertisement
    # Item 1: Organic video
    ad_item = AsyncMock()
    ad_locator = AsyncMock()
    ad_locator.count.return_value = 1  # has ad marker
    ad_item.locator.return_value = ad_locator

    organic_item = AsyncMock()
    # Ad check returns count = 0
    ad_check = AsyncMock()
    ad_check.count.return_value = 0

    # Title link mock
    title_link = AsyncMock()
    title_link.count.return_value = 1
    title_link_first = AsyncMock()
    title_link_first.is_visible.return_value = True
    title_link_first.get_attribute.return_value = "/watch?v=dQw4w9WgXcQ"
    title_link_first.text_content.return_value = "ElectroBOOM Funniest Moments"
    title_link_first.click = AsyncMock()
    title_link.first = title_link_first

    def item_locator_side_effect(selector):
        if "ad" in selector:
            return ad_check
        if selector == "a#video-title":
            return title_link
        return AsyncMock()

    organic_item.locator.side_effect = item_locator_side_effect

    renderers = AsyncMock()
    renderers.count.return_value = 2
    renderers.nth.side_effect = [ad_item, organic_item]

    def page_locator_side_effect(selector):
        if selector == "ytd-video-renderer":
            return renderers
        return AsyncMock()

    mock_page.locator.side_effect = page_locator_side_effect

    async def mock_wait_url(pred, timeout=None):
        mock_page.url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"

    mock_page.wait_for_url.side_effect = mock_wait_url

    with patch("app.tools.browser.inspection._get_active_page", return_value=mock_page):
        res = await browser_select_first(item_type="video")
        assert res.success is True
        assert "ElectroBOOM Funniest Moments" in res.message
        assert res.data["verified"] is True
        title_link_first.click.assert_called_once()


@pytest.mark.asyncio
async def test_browser_select_first_navigation_timeout():
    """Verify tool reports failure when target link is clicked but navigation fails to verify."""
    mock_page = AsyncMock()
    mock_page.url = "https://www.youtube.com/results?search_query=test"

    organic_item = AsyncMock()
    ad_check = AsyncMock()
    ad_check.count.return_value = 0

    title_link = AsyncMock()
    title_link.count.return_value = 1
    title_link_first = AsyncMock()
    title_link_first.is_visible.return_value = True
    title_link_first.get_attribute.return_value = "/watch?v=123"
    title_link_first.text_content.return_value = "Sample Video"
    title_link_first.click = AsyncMock()
    title_link.first = title_link_first

    def item_locator(sel):
        if "ad" in sel:
            return ad_check
        return title_link
    organic_item.locator.side_effect = item_locator

    renderers = AsyncMock()
    renderers.count.return_value = 1
    renderers.nth.return_value = organic_item

    mock_page.locator.return_value = renderers
    # URL does not change (e.g. click was blocked or navigation failed)
    mock_page.wait_for_url.side_effect = asyncio.TimeoutError()

    with patch("app.tools.browser.inspection._get_active_page", return_value=mock_page):
        res = await browser_select_first(item_type="video")
        assert res.success is False
        assert "verification_failed" in res.error


@pytest.mark.asyncio
async def test_browser_select_first_empty_results():
    """Verify handling when no search results or videos match the query."""
    mock_page = AsyncMock()
    mock_page.url = "https://www.youtube.com/results?search_query=nonexistent123"

    empty_renderers = AsyncMock()
    empty_renderers.count.return_value = 0
    mock_page.locator.return_value = empty_renderers

    with patch("app.tools.browser.inspection._get_active_page", return_value=mock_page):
        res = await browser_select_first(item_type="video", query="nonexistent123")
        assert res.success is False
        assert "no_video_found" in res.error


# ── Opt-in Browser Playwright Integration Test ────────────────────────────────

@pytest.mark.asyncio
async def test_real_browser_playwright_integration():
    """Opt-in real browser integration test using Airi Playwright context."""
    if not os.environ.get("AIRI_REAL_BROWSER_TEST"):
        pytest.skip("Skipping real browser integration test: AIRI_REAL_BROWSER_TEST not set")

    from app.tools.browser.automation import browser_open, _page
    open_res = await browser_open(browser_name="Firefox")
    assert open_res.success is True

    inspect_res = await browser_inspect()
    assert inspect_res.success is True
    assert "elements" in inspect_res.data

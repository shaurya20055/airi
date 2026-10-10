import pytest
from unittest.mock import patch, MagicMock
from app.tools.browser.automation import (
    browser_open, browser_navigate, browser_type, 
    browser_press, browser_click, browser_read
)
from app.tools.os_tools.desktop_parser import DesktopEntry
from app.tools.registry import ToolResult

class AsyncMock(MagicMock):
    async def __call__(self, *args, **kwargs):
        return super(AsyncMock, self).__call__(*args, **kwargs)

@pytest.fixture
def mock_app_resolver():
    with patch('app.tools.os_tools.app_resolver.AppResolver.resolve') as mock_resolve:
        mock_match = MagicMock()
        mock_match.entry = DesktopEntry(path="/firefox.desktop", name="Firefox", exec="firefox")
        mock_resolve.return_value = mock_match
        yield mock_resolve

@pytest.mark.asyncio
@patch('app.tools.browser.automation._do_browser_open', new_callable=AsyncMock)
async def test_browser_open(mock_do, mock_app_resolver):
    mock_do.return_value = ToolResult(success=True, message="Opened and connected to Firefox")
    result = await browser_open("Firefox")
    assert result.success is True
    assert "Firefox" in result.message
    mock_do.assert_called_once_with("Firefox")

@pytest.mark.asyncio
@patch('app.tools.browser.automation._do_browser_open', new_callable=AsyncMock)
async def test_browser_open_timeout(mock_do, mock_app_resolver):
    import asyncio
    mock_do.side_effect = asyncio.TimeoutError()
    result = await browser_open("Firefox")
    assert result.success is False
    assert "browser_open_timeout" in result.error

@pytest.mark.asyncio
@patch('app.tools.browser.automation._page')
async def test_browser_navigate(mock_page):
    mock_page.is_closed.return_value = False
    mock_page.goto = AsyncMock()
    result = await browser_navigate("google.com")
    assert result.success is True
    mock_page.goto.assert_called_with("https://google.com", wait_until="domcontentloaded", timeout=15000)

@pytest.mark.asyncio
@patch('app.tools.browser.automation._page')
async def test_browser_type(mock_page):
    mock_page.is_closed.return_value = False
    mock_page.fill = AsyncMock()
    result = await browser_type("input[name='q']", "dog")
    assert result.success is True
    mock_page.fill.assert_called_with("input[name='q']", "dog")

@pytest.mark.asyncio
@patch('app.tools.browser.automation._page')
async def test_browser_press(mock_page):
    mock_page.is_closed.return_value = False
    mock_page.keyboard.press = AsyncMock()
    result = await browser_press("Enter")
    assert result.success is True
    mock_page.keyboard.press.assert_called_with("Enter")

@pytest.mark.asyncio
@patch('app.tools.browser.automation._page', None)
async def test_browser_failed_no_page():
    result = await browser_navigate("google.com")
    assert result.success is False
    assert "No active browser session" in result.error

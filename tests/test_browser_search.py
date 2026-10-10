import pytest
from unittest.mock import patch, MagicMock
from app.tools.browser.automation import (
    browser_search, browser_open, browser_navigate, browser_type
)
from app.tools.os_tools.desktop_parser import DesktopEntry
from app.tools.os_tools.app_resolver import AppResolver

class AsyncMock(MagicMock):
    async def __call__(self, *args, **kwargs):
        return super(AsyncMock, self).__call__(*args, **kwargs)

@pytest.fixture
def mock_app_resolver():
    with patch('app.tools.os_tools.app_resolver.AppResolver.resolve') as mock_resolve:
        mock_match = MagicMock()
        mock_match.entry = DesktopEntry(path="/helium.desktop", name="Helium", exec="helium-browser", keywords=["browser"])
        mock_resolve.return_value = mock_match
        yield mock_resolve

@pytest.mark.asyncio
@patch('app.tools.browser.automation._do_browser_open', new_callable=AsyncMock)
@patch('app.tools.browser.automation._page')
async def test_browser_search_helium_youtube(mock_page, mock_init, mock_app_resolver):
    mock_init.return_value = MagicMock(success=True)
    mock_page.title = AsyncMock(return_value="dog - YouTube")
    mock_init.return_value = MagicMock(success=True)
    mock_page.goto = AsyncMock()
    mock_page.wait_for_load_state = AsyncMock()
    mock_page.url = "https://www.youtube.com/"
    
    mock_element = MagicMock()
    mock_element.fill = AsyncMock()
    mock_page.wait_for_selector = AsyncMock(return_value=mock_element)
    async def _submit(*_a, **_k):
        mock_page.url = "https://www.youtube.com/results?search_query=dog"
    mock_page.keyboard.press = _submit
    
    result = await browser_search("Helium", "dog", "youtube")
    assert result.success is True
    assert "Helium" in mock_init.call_args[0][0]
    mock_page.goto.assert_called_once()
    assert "youtube.com" in mock_page.goto.call_args[0][0]
    mock_element.fill.assert_called_with("dog")
    assert "search_query=dog" in result.data["url"]
    assert result.data["submit_method"] == "keyboard_enter"

@pytest.mark.asyncio
@patch('app.tools.browser.automation._do_browser_open', new_callable=AsyncMock)
@patch('app.tools.browser.automation._page')
async def test_browser_search_firefox_dog(mock_page, mock_init, mock_app_resolver):
    mock_match = MagicMock()
    mock_match.entry = DesktopEntry(path="/firefox.desktop", name="Firefox", exec="firefox")
    mock_app_resolver.return_value = mock_match

    mock_init.return_value = MagicMock(success=True)
    mock_page.title = AsyncMock(return_value="dog - Google Search")
    mock_init.return_value = MagicMock(success=True)
    mock_page.goto = AsyncMock()
    mock_page.wait_for_load_state = AsyncMock()
    mock_page.url = "https://www.google.com/"
    
    mock_element = MagicMock()
    mock_element.fill = AsyncMock()
    mock_page.wait_for_selector = AsyncMock(return_value=mock_element)
    async def _submit(*_a, **_k):
        mock_page.url = "https://www.google.com/search?q=dog"
    mock_page.keyboard.press = _submit
    
    result = await browser_search("Firefox", "dog")
    assert result.success is True
    assert "Firefox" in mock_init.call_args[0][0]
    mock_page.goto.assert_called_once()
    assert "google.com" in mock_page.goto.call_args[0][0]
    mock_element.fill.assert_called_with("dog")

@pytest.mark.asyncio
@patch('app.tools.browser.automation._do_browser_open', new_callable=AsyncMock)
@patch('app.tools.browser.automation._page')
async def test_browser_session_reuse(mock_page, mock_init, mock_app_resolver):
    mock_page.is_closed.return_value = False
    mock_init.return_value = MagicMock(success=True)
    res_open = await browser_open("Helium")
    assert res_open.success is True
    
    mock_page.goto = AsyncMock()
    res_nav = await browser_navigate("google.com")
    assert res_nav.success is True
    
    mock_page.fill = AsyncMock()
    res_type = await browser_type("input", "hello")
    assert res_type.success is True

@pytest.mark.asyncio
async def test_failed_browser_open_no_session():
    import app.tools.browser.automation as auto
    auto._page = None
    
    res = await browser_navigate("google.com")
    assert res.success is False
    assert "No active browser session" in res.error

@pytest.mark.asyncio
@patch('app.tools.browser.automation._do_browser_open', new_callable=AsyncMock)
@patch('app.tools.browser.automation._page')
async def test_browser_search_verification_failure(mock_page, mock_init, mock_app_resolver):
    # Test J: model cannot claim browser action succeeded when verification failed
    mock_init.return_value = MagicMock(success=True)
    mock_page.goto = AsyncMock()
    mock_page.wait_for_load_state = AsyncMock()
    
    mock_element = MagicMock()
    mock_element.fill = AsyncMock()
    mock_page.wait_for_selector = AsyncMock(return_value=mock_element)
    mock_page.keyboard.press = AsyncMock()
    
    # URL didn't change and title doesn't contain query
    mock_page.url = "https://www.youtube.com"
    mock_page.title = AsyncMock(return_value="YouTube")
    
    result = await browser_search("Helium", "dog", "youtube")
    assert result.success is False
    assert result.error == "search_not_verified"

def test_chrome_resolution():
    resolver = AppResolver()
    resolver.entries = [
        DesktopEntry(path="/google-chrome.desktop", name="Google Chrome", exec="/opt/google/chrome/google-chrome", keywords=["browser"])
    ]
    resolver._initialized = True
    
    match = resolver.resolve("Chrome")
    assert match.entry is not None
    assert match.entry.name == "Google Chrome"
    
    match = resolver.resolve("Google Chrome")
    assert match.entry is not None
    assert match.entry.name == "Google Chrome"
    
    match = resolver.resolve("Chrome browser")
    assert match.entry is not None
    assert match.entry.name == "Google Chrome"

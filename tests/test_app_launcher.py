import pytest
from app.tools.os_tools.desktop_parser import DesktopEntry
from app.tools.os_tools.app_resolver import AppResolver

@pytest.fixture
def mock_resolver():
    resolver = AppResolver()
    resolver.entries = [
        DesktopEntry(path="/usr/share/applications/firefox.desktop", name="Firefox", exec="firefox %u", keywords=["browser", "web", "internet"]),
        DesktopEntry(path="/usr/share/applications/google-chrome.desktop", name="Google Chrome", exec="google-chrome-stable %U", keywords=["browser", "web"]),
        DesktopEntry(path="/usr/share/applications/helium.desktop", name="Helium", exec="helium-browser", keywords=["browser", "lightweight"]),
        DesktopEntry(path="/usr/share/applications/vlc.desktop", name="VLC media player", exec="vlc %U", keywords=["video", "audio", "player"]),
        DesktopEntry(path="/usr/share/applications/code.desktop", name="Visual Studio Code", exec="code", keywords=["editor", "ide"]),
        DesktopEntry(path="/usr/share/applications/code-insiders.desktop", name="Visual Studio Code Insiders", exec="code-insiders", keywords=["editor", "ide"])
    ]
    resolver._initialized = True
    return resolver

def test_exact_name(mock_resolver):
    match = mock_resolver.resolve("Firefox")
    assert match.entry is not None
    assert match.entry.name == "Firefox"
    assert match.is_ambiguous is False

def test_natural_language_variants(mock_resolver):
    match = mock_resolver.resolve("open firefox browser")
    assert match.entry is not None
    assert match.entry.name == "Firefox"

    match = mock_resolver.resolve("launch Google Chrome")
    assert match.entry is not None
    assert match.entry.name == "Google Chrome"

    match = mock_resolver.resolve("start chrome browser")
    assert match.entry is not None
    assert match.entry.name == "Google Chrome"

def test_asr_corrections(mock_resolver):
    match = mock_resolver.resolve("launch helm browser")
    assert match.entry is not None
    assert match.entry.name == "Helium"

    match = mock_resolver.resolve("open helim")
    assert match.entry is not None
    assert match.entry.name == "Helium"
    
    match = mock_resolver.resolve("launch helium browser")
    assert match.entry is not None
def test_ambiguous_application(mock_resolver):
    match = mock_resolver.resolve("Web Browser")
    assert match.is_ambiguous is True
    assert "Firefox" in match.ambiguous_candidates
    assert "Google Chrome" in match.ambiguous_candidates

def test_category_only_clarification(mock_resolver):
    match = mock_resolver.resolve("open browser")
    assert match.is_ambiguous is True
    assert match.entry is None
    
    match = mock_resolver.resolve("open a browser")
    assert match.is_ambiguous is True
    assert match.entry is None

def test_nonexistent_app(mock_resolver):
    match = mock_resolver.resolve("launch completelyfakeappthatdoesntexist")
    assert match.entry is None
    assert match.is_ambiguous is False

def test_helium_regression(mock_resolver):
    # Ensure 'helm browser' does not fall back to Firefox just because it has the 'browser' keyword
    match = mock_resolver.resolve("helm browser")
    assert match.entry is not None
    assert match.entry.name == "Helium"
    assert match.entry.name != "Firefox"

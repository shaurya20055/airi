import pytest
from app.tools.os_tools.app_resolver import AppResolver

def test_helium_resolution():
    resolver = AppResolver()
    # It requires entries, let's inject a fake one
    from app.tools.os_tools.desktop_parser import DesktopEntry
    resolver.entries = [
        DesktopEntry(path="/tmp", name="Helium", exec="/usr/bin/helium", generic_name="Browser", keywords=[], try_exec=None),
        DesktopEntry(path="/tmp", name="Firefox", exec="/usr/bin/firefox", generic_name="Web Browser", keywords=["browser"], try_exec=None),
    ]
    resolver._initialized = True
    
    assert resolver.resolve("helm browser").entry.name == "Helium"
    assert resolver.resolve("helium rouse").entry.name == "Helium"
    assert resolver.resolve("shillium browser").entry.name == "Helium"
    assert resolver.resolve("firefox").entry.name == "Firefox"

import pytest
from unittest.mock import patch, MagicMock
from app.tools.system.visible_terminal import (
    terminal_open, terminal_focus, terminal_type, terminal_press
)
from app.tools.os_tools.desktop_parser import DesktopEntry

class AsyncMock(MagicMock):
    async def __call__(self, *args, **kwargs):
        return super(AsyncMock, self).__call__(*args, **kwargs)

@pytest.mark.asyncio
@patch('app.tools.os_tools.app_resolver.AppResolver.resolve')
@patch('subprocess.Popen')
async def test_terminal_open(mock_popen, mock_resolve):
    mock_match = MagicMock()
    mock_match.entry = DesktopEntry(path="/kitty.desktop", name="Kitty", exec="kitty")
    mock_resolve.return_value = mock_match
    
    result = await terminal_open("Kitty")
    assert result.success is True
    assert "Kitty" in result.message
    mock_popen.assert_called_once_with(["kitty"], stdout=-3, stderr=-3) # -3 is DEVNULL

@pytest.mark.asyncio
@patch('asyncio.create_subprocess_exec')
async def test_terminal_focus(mock_exec):
    mock_proc = AsyncMock()
    mock_proc.communicate.return_value = (b"", b"")
    mock_proc.returncode = 0
    mock_exec.return_value = mock_proc
    
    result = await terminal_focus()
    assert result.success is True

@pytest.mark.asyncio
@patch('asyncio.create_subprocess_exec')
async def test_terminal_type(mock_exec):
    mock_proc = AsyncMock()
    mock_proc.communicate.return_value = (b"", b"")
    mock_proc.returncode = 0
    mock_exec.return_value = mock_proc
    
    result = await terminal_type("echo hello")
    assert result.success is True
    mock_exec.assert_called_with("wtype", "echo hello", stdout=-1, stderr=-1)

@pytest.mark.asyncio
@patch('asyncio.create_subprocess_exec')
async def test_terminal_press(mock_exec):
    mock_proc = AsyncMock()
    mock_proc.communicate.return_value = (b"", b"")
    mock_proc.returncode = 0
    mock_exec.return_value = mock_proc
    
    result = await terminal_press("Return")
    assert result.success is True
    mock_exec.assert_called_with("wtype", "-k", "return", stdout=-1, stderr=-1)

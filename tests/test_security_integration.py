import pytest
from unittest.mock import AsyncMock
from app.core.permissions.manager import PermissionManager, PermissionLevel, PermissionDecision
from app.core.events.bus import EventBus
from app.tools.system.terminal import execute_command, execute_shell

@pytest.fixture
def permission_manager():
    bus = EventBus()
    pm = PermissionManager(bus, cli_mode=False)
    # Mock prompter to deny everything by default to simulate "required confirmation" blocking
    pm._prompter.ask = AsyncMock(return_value=PermissionDecision.DENY)
    return pm

@pytest.mark.asyncio
async def test_policy_cannot_be_bypassed_safe(permission_manager):
    # Safe command like "echo" should be allowed without prompt
    allowed = await permission_manager.request_permission("execute_command", {"command": "echo hello"}, PermissionLevel.SAFE)
    assert allowed is True
    permission_manager._prompter.ask.assert_not_called()

@pytest.mark.asyncio
async def test_policy_cannot_be_bypassed_dangerous(permission_manager):
    # Dangerous command like "rm" should trigger a prompt, which we mocked to DENY
    allowed = await permission_manager.request_permission("execute_command", {"command": "rm file.txt"}, PermissionLevel.SAFE)
    assert allowed is False
    permission_manager._prompter.ask.assert_called_once()
    
@pytest.mark.asyncio
async def test_policy_cannot_be_bypassed_shell_meta(permission_manager):
    allowed = await permission_manager.request_permission("execute_command", {"command": "echo | ls"}, PermissionLevel.SAFE)
    assert allowed is False
    permission_manager._prompter.ask.assert_called_once()
    
@pytest.mark.asyncio
async def test_execute_shell_always_requires_confirmation(permission_manager):
    allowed = await permission_manager.request_permission("execute_shell", {"command": "echo hello"}, PermissionLevel.SAFE)
    assert allowed is False
    permission_manager._prompter.ask.assert_called_once()

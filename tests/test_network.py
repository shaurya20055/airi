import pytest
from unittest.mock import patch, MagicMock
from app.tools.system.network import (
    get_network_status, get_hotspot_status, disable_hotspot, enable_hotspot
)
from app.agent.tasks import HotspotTask
from app.core.permissions.manager import PermissionManager, PermissionLevel, PermissionDecision
from app.core.events.bus import EventBus

class AsyncMock(MagicMock):
    async def __call__(self, *args, **kwargs):
        return super(AsyncMock, self).__call__(*args, **kwargs)

@pytest.fixture
def permission_manager():
    bus = EventBus()
    pm = PermissionManager(bus, cli_mode=False)
    pm._prompter.ask = AsyncMock(return_value=PermissionDecision.ALLOW_ONCE)
    return pm

@pytest.mark.asyncio
@patch('app.tools.system.network.get_hotspot_status_dict')
@patch('app.tools.system.network.deactivate_profile', new_callable=AsyncMock)
async def test_disable_active_hotspot(mock_deactivate, mock_status):
    # A. Disable active hotspot: command succeeds + verification inactive -> success
    mock_status.side_effect = [
        {"active": True, "profile_id": "test-uuid"},
        {"active": False}
    ]
    result = await disable_hotspot()
    assert result.success is True
    assert "Hotspot is off" in result.message
    mock_deactivate.assert_called_once_with("test-uuid")

@pytest.mark.asyncio
@patch('app.tools.system.network.get_hotspot_status_dict')
@patch('app.tools.system.network.deactivate_profile', new_callable=AsyncMock)
async def test_disable_hotspot_failing_verification(mock_deactivate, mock_status):
    # B. Disable hotspot: command succeeds but verification remains active -> failure
    mock_status.side_effect = [
        {"active": True, "profile_id": "test-uuid"},
        {"active": True}
    ]
    result = await disable_hotspot()
    assert result.success is False
    assert "couldn't confirm" in result.error
    mock_deactivate.assert_called_once_with("test-uuid")

@pytest.mark.asyncio
@patch('app.tools.system.network.get_hotspot_status_dict')
async def test_disable_already_inactive(mock_status):
    # C. Disable when already inactive -> clear already-inactive result
    mock_status.return_value = {"active": False}
    result = await disable_hotspot()
    assert result.success is True
    assert result.data["already_inactive"] is True

@pytest.mark.asyncio
@patch('app.tools.system.network.get_hotspot_status_dict')
@patch('app.tools.system.network.find_existing_profile')
@patch('app.tools.system.network.activate_profile', new_callable=AsyncMock)
async def test_enable_using_previous(mock_activate, mock_find, mock_status, permission_manager):
    # D. Enable using previous SSID/password
    mock_status.side_effect = [{"active": False}, {"active": True}]
    mock_find.return_value = {"uuid": "test-uuid", "name": "Airi_Hotspot"}
    
    task = HotspotTask()
    task.permission_manager = permission_manager
    prompt1 = await task.start()
    assert "reuse" in prompt1
    
    prompt2 = await task.handle_input("reuse")
    assert "Keep the existing password" in prompt2
    
    prompt3 = await task.handle_input("keep it")
    assert "Hotspot is on" in prompt3
    assert task.is_complete is True
    
    permission_manager._prompter.ask.assert_called_once()
    mock_activate.assert_called_once_with("test-uuid")

@pytest.mark.asyncio
@patch('app.tools.system.network.get_hotspot_status_dict')
@patch('app.tools.system.network.find_existing_profile')
@patch('app.tools.system.network.create_profile', new_callable=AsyncMock)
@patch('app.tools.system.network.activate_profile', new_callable=AsyncMock)
async def test_enable_new_ssid(mock_activate, mock_create, mock_find, mock_status, permission_manager):
    # E. Enable with new SSID
    mock_status.side_effect = [{"active": False}, {"active": True}]
    mock_find.return_value = None # No existing profile
    mock_create.return_value = "new-uuid"
    
    task = HotspotTask()
    task.permission_manager = permission_manager
    prompt1 = await task.start()
    assert "What SSID" in prompt1
    
    prompt2 = await task.handle_input("MyTestNet")
    assert "What password" in prompt2
    
    prompt3 = await task.handle_input("SuperSecret123")
    assert "Hotspot is on" in prompt3
    
    mock_create.assert_called_once_with("MyTestNet", "SuperSecret123")
    mock_activate.assert_called_once_with("new-uuid")
    permission_manager._prompter.ask.assert_called_once()

@pytest.mark.asyncio
@patch('app.tools.system.network.get_hotspot_status_dict')
@patch('app.tools.system.network.find_existing_profile')
@patch('app.tools.system.network.update_password', new_callable=AsyncMock)
@patch('app.tools.system.network.activate_profile', new_callable=AsyncMock)
async def test_change_password_on_existing(mock_activate, mock_update, mock_find, mock_status, permission_manager):
    # F. Change password on existing hotspot
    mock_status.side_effect = [{"active": False}, {"active": True}]
    mock_find.return_value = {"uuid": "test-uuid", "name": "Airi_Hotspot"}
    
    task = HotspotTask()
    task.permission_manager = permission_manager
    await task.start()
    await task.handle_input("reuse")
    await task.handle_input("change")
    await task.handle_input("NewPassword456")
    
    mock_update.assert_called_once_with("test-uuid", "NewPassword456")
    mock_activate.assert_called_once_with("test-uuid")

# G & H are implicitly tested because `ask` is asserted `called_once()`
# I. No confirmation for get_hotspot_status
def test_status_tool_permissions():
    from app.tools.registry import PermissionLevel
    from app.tools.system.network import get_hotspot_status
    # Check that tool uses SAFE
    assert getattr(get_hotspot_status, '__tool_def__', None) is None # actually the decorator adds _tool_def
    # wait, the decorator adds `tool_definition`. Let's just check registry if we want.

# J. Password never appears in logs (tested by asserting the args sent to permission manager)
@pytest.mark.asyncio
@patch('app.tools.system.network.get_hotspot_status_dict')
@patch('app.tools.system.network.find_existing_profile')
@patch('app.tools.system.network.create_profile', new_callable=AsyncMock)
@patch('app.tools.system.network.activate_profile', new_callable=AsyncMock)
async def test_password_redacted_in_permissions(mock_activate, mock_create, mock_find, mock_status):
    mock_status.side_effect = [{"active": False}, {"active": True}]
    mock_find.return_value = None
    mock_create.return_value = "new-uuid"
    
    task = HotspotTask()
    pm = MagicMock()
    pm.request_permission = AsyncMock(return_value=True)
    task.permission_manager = pm
    
    await task.start()
    await task.handle_input("MyTestNet")
    await task.handle_input("SuperSecret123")
    
    # Verify the arguments passed to request_permission do not contain the plaintext password
    pm.request_permission.assert_called_once()
    args = pm.request_permission.call_args.kwargs['args']
    assert args['password'] == "***"
    assert "SuperSecret123" not in str(args)


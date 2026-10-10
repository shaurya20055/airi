"""Tests for the Airi personality configuration system."""
from __future__ import annotations

import yaml
from pathlib import Path
import pytest
from unittest.mock import patch, AsyncMock

from app.agent.context import AgentContext
from app.agent.orchestrator import AgentOrchestrator
from app.ai.router import AIRouter
from app.ai.schemas import AIResponse, Message, IntentType, ClassifiedIntent
from app.core.config.settings import Settings, get_settings
from app.core.events.bus import EventBus
from app.core.permissions.manager import PermissionManager
from app.memory.store import MemoryStore
from app.tools.registry import ToolRegistry, ToolDefinition, PermissionLevel

@pytest.fixture
def temp_persona(tmp_path):
    """Create a temporary personality yaml."""
    config_path = tmp_path / "test_personality.yaml"
    config_data = {
        "name": "TestAiri",
        "description": "A very specific test persona.",
        "traits": ["Trait 1", "Trait 2"],
        "guidelines": ["Guideline 1", "Guideline 2"]
    }
    with config_path.open("w") as f:
        yaml.dump(config_data, f)
    return config_path


@pytest.fixture
def mock_settings(temp_persona, monkeypatch):
    """Override settings to use the temp persona."""
    import app.core.config.settings as mod
    mod._settings_instance = None
    monkeypatch.setenv("PERSONALITY_PATH", str(temp_persona))
    s = get_settings()
    yield s
    mod._settings_instance = None


def test_agent_context_loads_persona(mock_settings, temp_persona):
    """Test that AgentContext reads the yaml and includes it in the system prompt."""
    context = AgentContext()
    system_msg = context.messages[0].content
    
    assert "You are TestAiri." in system_msg
    assert "A very specific test persona." in system_msg
    assert "Trait 1" in system_msg
    assert "Guideline 2" in system_msg
    assert "SYSTEM RESPONSE RULES:" in system_msg


def test_agent_context_missing_persona_fallback(monkeypatch):
    """Test that missing yaml falls back gracefully."""
    import app.core.config.settings as mod
    mod._settings_instance = None
    monkeypatch.setenv("PERSONALITY_PATH", "/does/not/exist.yaml")
    
    context = AgentContext()
    system_msg = context.messages[0].content
    
    assert "You are Airi, a helpful desktop AI assistant running locally." in system_msg
    assert "SYSTEM RESPONSE RULES:" in system_msg
    
    mod._settings_instance = None


@pytest.mark.asyncio
async def test_persona_does_not_override_tool_failures(mock_settings):
    """Test that the orchestrator truthfully reports tool failures."""
    from app.ai.schemas import ToolCall
    router = AsyncMock(spec=AIRouter)
    router.process.return_value = AIResponse(
        text="",
        tool_calls=[ToolCall(id="call_123", name="failing_tool", arguments={})]
    )

    registry = ToolRegistry()
    defn = ToolDefinition(
        name="failing_tool", description="Fails", category="Test",
        permission_level=PermissionLevel.SAFE
    )
    def fail_fn():
        raise RuntimeError("Disk error!")
    registry.register(defn, fail_fn)

    event_bus = EventBus()
    permission_manager = AsyncMock(spec=PermissionManager)
    permission_manager.request_permission.return_value = True
    memory = AsyncMock(spec=MemoryStore)

    orchestrator = AgentOrchestrator(
        router=router, tool_registry=registry, memory=memory,
        event_bus=event_bus, permission_manager=permission_manager
    )

    response = await orchestrator.process_input("Do the thing.")
    
    assert "Error:" in response
    assert "Disk error!" in response
    
    tool_msgs = [m for m in orchestrator.context.messages if m.role == "tool"]
    assert len(tool_msgs) == 1
    assert tool_msgs[0].tool_results[0].success is False


@pytest.mark.asyncio
async def test_persona_does_not_bypass_permissions(mock_settings):
    """Test that persona instructions don't let tools bypass permissions."""
    from app.ai.schemas import ToolCall
    router = AsyncMock(spec=AIRouter)
    router.process.return_value = AIResponse(
        text="",
        tool_calls=[ToolCall(id="call_1", name="dangerous_tool", arguments={})]
    )

    registry = ToolRegistry()
    defn = ToolDefinition(
        name="dangerous_tool", description="Danger", category="Test",
        permission_level=PermissionLevel.DANGEROUS
    )
    registry.register(defn, lambda: "Explosion")

    event_bus = EventBus()
    permission_manager = AsyncMock(spec=PermissionManager)
    permission_manager.request_permission.return_value = False
    memory = AsyncMock(spec=MemoryStore)

    orchestrator = AgentOrchestrator(
        router=router, tool_registry=registry, memory=memory,
        event_bus=event_bus, permission_manager=permission_manager
    )

    response = await orchestrator.process_input("Do dangerous thing.")
    
    assert "Permission denied" in response
    assert "Explosion" not in response

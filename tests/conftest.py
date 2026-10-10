"""Shared pytest fixtures for the Airi test suite."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock

from app.core.events.bus import EventBus
from app.core.permissions.manager import PermissionManager
from app.core.permissions.levels import PermissionLevel
from app.tools.registry import (
    ToolDefinition,
    ToolParameter,
    ToolRegistry,
    ToolResult,
)
from app.memory.store import MemoryStore
from app.ai.providers.local.provider import LocalProvider
from app.ai.schemas import AIResponse


@pytest.fixture
def event_bus():
    return EventBus()


@pytest.fixture
def tool_registry():
    """Provide a clean ToolRegistry with one mock tool registered."""
    import app.tools.registry as mod
    old_tools = dict(mod.registry._tools)
    mod.registry._tools.clear()
    
    # Register manually to avoid decorator binding issues
    defn = ToolDefinition(
        name="mock_tool",
        description="A mock tool for testing",
        category="test",
        permission_level=PermissionLevel.SAFE,
        parameters=[
            ToolParameter(name="param1", type="string", description="A test param")
        ]
    )
    
    async def mock_tool_fn(param1: str = "default") -> ToolResult:
        return ToolResult(success=True, data=f"Mocked {param1}", message="OK")
        
    mod.registry.register(defn, mock_tool_fn)
    yield mod.registry
    mod.registry._tools.clear()
    mod.registry._tools.update(old_tools)


@pytest.fixture
async def memory_store(tmp_path):
    """Provide a MemoryStore backed by a temp SQLite database."""
    db_path = str(tmp_path / "test_memory.db")
    store = MemoryStore(db_path=db_path)
    await store.initialize()
    yield store
    await store.close()


@pytest.fixture
def permission_manager(event_bus):
    return PermissionManager(event_bus=event_bus, cli_mode=False)


@pytest.fixture
def local_provider():
    return LocalProvider()


@pytest.fixture
def mock_cloud_provider():
    mock = AsyncMock(spec=["respond", "respond_stream", "vision",
                           "is_available", "supports_vision", "supports_tools", "name"])
    mock.is_available.return_value = True
    mock.supports_vision.return_value = True
    mock.supports_tools.return_value = True
    mock.name = "mock_cloud"
    async def async_respond(*args, **kwargs):
        return AIResponse(
            text="Cloud response",
            tool_calls=[],
            finish_reason="stop",
        )
    mock.respond = AsyncMock(side_effect=async_respond)
    return mock

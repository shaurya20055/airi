"""Tests for app.agent — context, executor, orchestrator."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock

from app.agent.context import AgentContext
from app.agent.executor import ToolExecutor
from app.agent.orchestrator import AgentOrchestrator
from app.ai.providers.local.provider import LocalProvider
from app.ai.router import AIRouter
from app.ai.schemas import Message
from app.core.events.bus import EventBus
from app.memory.store import MemoryStore
from app.core.permissions.manager import PermissionManager
from app.tools.registry import ToolRegistry


# --- AgentContext ---

def test_context_starts_with_system_prompt():
    ctx = AgentContext()
    msgs = ctx.get_messages()
    assert len(msgs) >= 1
    assert msgs[0].role == "system"


def test_context_add_user_message():
    ctx = AgentContext()
    ctx.add_user_message("hello")
    msgs = ctx.get_messages()
    assert any(m.role == "user" and m.content == "hello" for m in msgs)


def test_context_add_assistant_message():
    ctx = AgentContext()
    ctx.add_assistant_message("hi there")
    msgs = ctx.get_messages()
    assert any(m.role == "assistant" and m.content == "hi there" for m in msgs)


def test_context_clear():
    ctx = AgentContext()
    ctx.add_user_message("hello")
    ctx.add_assistant_message("hi")
    ctx.clear()
    msgs = ctx.get_messages()
    # After clear, should only have the system prompt
    assert len(msgs) == 1
    assert msgs[0].role == "system"


def test_context_trim_history():
    ctx = AgentContext(max_history=5)
    for i in range(20):
        ctx.add_user_message(f"msg {i}")
    msgs = ctx.get_messages()
    assert len(msgs) <= 5


def test_context_add_tool_result():
    ctx = AgentContext()
    ctx.add_tool_result("call_123", "Volume set to 40%", True)
    msgs = ctx.get_messages()
    assert any(m.role == "tool" for m in msgs)


# --- ToolExecutor ---

@pytest.mark.asyncio
async def test_executor_runs_tool(tool_registry, event_bus):
    executor = ToolExecutor(tool_registry, event_bus)
    result = await executor.execute("mock_tool", {"param1": "test"})
    assert result.success


@pytest.mark.asyncio
async def test_executor_handles_missing_tool(tool_registry, event_bus):
    executor = ToolExecutor(tool_registry, event_bus)
    result = await executor.execute("nonexistent", {})
    assert not result.success


# --- AgentOrchestrator ---

@pytest.mark.asyncio
async def test_orchestrator_tool_call(tool_registry, event_bus, tmp_path):
    local_provider = LocalProvider()
    router = AIRouter(local_provider=local_provider)
    pm = PermissionManager(event_bus, cli_mode=False)

    memory = MemoryStore(str(tmp_path / "test.db"))
    await memory.initialize()

    orch = AgentOrchestrator(
        router=router,
        tool_registry=tool_registry,
        memory=memory,
        event_bus=event_bus,
        permission_manager=pm,
    )

    # "set volume to 50" matches local provider → tool call
    # But set_volume isn't in the mock registry, so it'll fail gracefully
    response = await orch.process_input("set volume to 50", source="cli")
    assert isinstance(response, str)
    await memory.close()


@pytest.mark.asyncio
async def test_orchestrator_unknown_command(tool_registry, event_bus, tmp_path):
    local_provider = LocalProvider()
    router = AIRouter(local_provider=local_provider)
    pm = PermissionManager(event_bus, cli_mode=False)

    memory = MemoryStore(str(tmp_path / "test2.db"))
    await memory.initialize()

    orch = AgentOrchestrator(
        router=router,
        tool_registry=tool_registry,
        memory=memory,
        event_bus=event_bus,
        permission_manager=pm,
    )

    response = await orch.process_input("what is the meaning of life?", source="cli")
    assert isinstance(response, str)
    # Should indicate cloud needed or provide fallback
    assert len(response) > 0
    await memory.close()

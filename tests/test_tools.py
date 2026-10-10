"""Tests for app.tools — registry, decorator, execution."""
from __future__ import annotations

import pytest
from app.tools.registry import (
    PermissionLevel,
    ToolDefinition,
    ToolParameter,
    ToolRegistry,
    ToolResult,
    tool,
)


def test_registry_has_mock_tool(tool_registry):
    """The conftest registers a mock_tool."""
    t = tool_registry.get_tool("mock_tool")
    assert t is not None
    defn, func = t
    assert defn.name == "mock_tool"


def test_list_tools(tool_registry):
    tools = tool_registry.list_tools()
    names = [t.name for t in tools]
    assert "mock_tool" in names


def test_list_by_category(tool_registry):
    tools = tool_registry.list_by_category("test")
    assert len(tools) == 1
    assert tools[0].name == "mock_tool"


def test_list_by_category_empty(tool_registry):
    tools = tool_registry.list_by_category("nonexistent")
    assert tools == []


@pytest.mark.asyncio
async def test_execute_valid_tool(tool_registry):
    result = await tool_registry.execute("mock_tool", {"param1": "hello"})
    assert isinstance(result, ToolResult)
    assert result.success
    assert result.data == "Mocked hello"


@pytest.mark.asyncio
async def test_execute_missing_tool(tool_registry):
    result = await tool_registry.execute("nonexistent", {})
    assert not result.success
    assert "unknown" in result.error.lower() or "not found" in result.error.lower()


@pytest.mark.asyncio
async def test_execute_disabled_tool(tool_registry):
    defn, func = tool_registry.get_tool("mock_tool")
    defn.enabled = False
    result = await tool_registry.execute("mock_tool", {"param1": "test"})
    assert not result.success
    assert "disabled" in result.error.lower()
    defn.enabled = True  # restore


def test_to_openai_tools_format(tool_registry):
    openai_tools = tool_registry.to_openai_tools()
    assert len(openai_tools) >= 1
    t = openai_tools[0]
    assert t["type"] == "function"
    assert "name" in t["function"]
    assert "parameters" in t["function"]
    assert t["function"]["parameters"]["type"] == "object"


def test_get_tool_descriptions(tool_registry):
    desc = tool_registry.get_tool_descriptions()
    assert "mock_tool" in desc


def test_tool_result_model():
    r = ToolResult(success=True, data=42, message="ok")
    assert r.success
    assert r.data == 42

    r2 = ToolResult(success=False, error="fail")
    assert not r2.success
    assert r2.error == "fail"


def test_tool_definition_model():
    td = ToolDefinition(
        name="test",
        description="desc",
        category="cat",
        permission_level=PermissionLevel.SAFE,
    )
    assert td.name == "test"
    assert td.enabled is True


def test_permission_levels():
    assert PermissionLevel.SAFE.value == "safe"
    assert PermissionLevel.CONFIRM.value == "confirm"
    assert PermissionLevel.DANGEROUS.value == "dangerous"
    assert PermissionLevel.BLOCKED.value == "blocked"

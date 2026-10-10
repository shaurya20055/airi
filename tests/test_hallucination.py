import pytest
import copy
from unittest.mock import MagicMock, AsyncMock
from app.agent.orchestrator import AgentOrchestrator
from app.ai.schemas import AIResponse, ToolCall
from app.agent.context import AgentContext
from app.tools.registry import ToolResult, ToolDefinition

@pytest.mark.asyncio
async def test_hallucinated_tool_success_rejected():
    router = AsyncMock()
    # Mock LLM to hallucinate on first step, then output correct tool on second step
    router.process.side_effect = [
        AIResponse(text="browser_search succeeded.", tool_calls=[]),
        AIResponse(text="Okay, I will do it.", tool_calls=[ToolCall(id="123", name="browser_search", arguments={"browser_name": "Helium", "query": "test", "site": "google"})]),
        AIResponse(text="Done now.", tool_calls=[])
    ]
    
    registry = MagicMock()
    # Create a real-looking definition for get_tool to return
    def_mock = MagicMock()
    def_mock.permission_level.value = "safe"
    
    # We need to simulate registry.get_tool returning (definition, func)
    registry.get_tool.return_value = (def_mock, AsyncMock())
    
    # And list_tools needs to return something that has .name
    list_tool_mock = MagicMock()
    list_tool_mock.name = "browser_search"
    registry.list_tools.return_value = [list_tool_mock]
    
    # And registry.execute needs to return a ToolResult
    registry.execute = AsyncMock(return_value=ToolResult(success=True))
    
    perm_mgr = AsyncMock()
    perm_mgr.request_permission.return_value = True

    orchestrator = AgentOrchestrator(router, registry, AsyncMock(), AsyncMock(), perm_mgr)
    
    # Must patch ToolExecutor internal registry reference to our mock registry
    orchestrator.executor.registry = registry
    
    # Run
    await orchestrator.process_input("search")
    
    # It should have looped twice
    assert router.process.call_count == 3
    
    # The context should have the rejection message
    messages = orchestrator.context.get_messages()
    assert any("Tool call required" in m.content for m in messages if m.role == "user")

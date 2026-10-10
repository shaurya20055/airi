import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from app.agent.orchestrator import AgentOrchestrator
from app.ai.schemas import AIResponse, ToolCall
import json

@pytest.fixture
def mock_dependencies():
    class Deps:
        router = AsyncMock()
        tool_registry = MagicMock()
        tool_registry.to_openai_tools.return_value = []
        memory = AsyncMock()
        event_bus = AsyncMock()
        permission_manager = AsyncMock()
        permission_manager.request_permission.return_value = True
    return Deps()

@pytest.mark.asyncio
async def test_multistep_orchestrator(mock_dependencies):
    orchestrator = AgentOrchestrator(
        router=mock_dependencies.router,
        tool_registry=mock_dependencies.tool_registry,
        memory=mock_dependencies.memory,
        event_bus=mock_dependencies.event_bus,
        permission_manager=mock_dependencies.permission_manager
    )
    
    # We want router to return a tool call on step 1, a tool call on step 2, and text on step 3.
    tc1 = ToolCall(id="1", name="dummy_tool1", arguments={})
    tc2 = ToolCall(id="2", name="dummy_tool2", arguments={})
    
    mock_dependencies.router.process.side_effect = [
        AIResponse(text="", tool_calls=[tc1]),
        AIResponse(text="", tool_calls=[tc2]),
        AIResponse(text="Final answer", tool_calls=[])
    ]
    
    # Mock executor
    orchestrator.executor.execute = AsyncMock()
    mock_res = MagicMock()
    mock_res.success = True
    mock_res.message = "Success"
    mock_res.data = None
    mock_res.task = None
    orchestrator.executor.execute.return_value = mock_res
    
    # Mock registry
    mock_dependencies.tool_registry.get_tool.return_value = (MagicMock(permission_level=MagicMock(value="safe")), None)
    
    final_text = await orchestrator.process_input("Do a 3 step thing")
    
    assert final_text == "Final answer"
    assert mock_dependencies.router.process.call_count == 3
    assert orchestrator.executor.execute.call_count == 2
    
    # H. tool loop terminates after task completion (called 3 times, not MAX_AGENT_STEPS)

@pytest.mark.asyncio
async def test_multistep_limit(mock_dependencies):
    orchestrator = AgentOrchestrator(
        router=mock_dependencies.router,
        tool_registry=mock_dependencies.tool_registry,
        memory=mock_dependencies.memory,
        event_bus=mock_dependencies.event_bus,
        permission_manager=mock_dependencies.permission_manager
    )
    
    tc1 = ToolCall(id="1", name="dummy_tool1", arguments={})
    # Infinite loop of tool calls
    mock_dependencies.router.process.return_value = AIResponse(text="", tool_calls=[tc1])
    
    orchestrator.executor.execute = AsyncMock()
    mock_res = MagicMock()
    mock_res.success = True
    mock_res.message = "Success"
    mock_res.data = None
    mock_res.task = None
    orchestrator.executor.execute.return_value = mock_res
    
    mock_dependencies.tool_registry.get_tool.return_value = (MagicMock(permission_level=MagicMock(value="safe")), None)
    
    final_text = await orchestrator.process_input("Do infinite loop")
    
    assert "maximum number of steps" in final_text
    assert mock_dependencies.router.process.call_count == 10  # MAX_AGENT_STEPS

"""Offline integration tests for Airi AI assistant."""
from __future__ import annotations

import asyncio
from pathlib import Path

from app.__main__ import _import_all_tools
from app.agent.orchestrator import AgentOrchestrator
from app.ai.providers.local.ollama_runtime import OllamaRuntime
from app.ai.providers.local.provider import LocalProvider
from app.ai.router import AIRouter
from app.core.config.settings import get_settings
from app.core.events.bus import EventBus
from app.core.events.events import ToolExecutionStarted
from app.core.permissions.manager import PermissionManager
from app.memory.store import MemoryStore
from app.tools.registry import ToolRegistry


async def run_offline_integration() -> None:
    print("=" * 60)
    print("  Airi Offline Integration Test")
    print("=" * 60)

    # 1. Setup
    _import_all_tools()
    settings = get_settings()
    event_bus = EventBus()
    registry = ToolRegistry()

    # Create dummy database for tests
    db_path = Path("data/test_memory.db")
    if db_path.exists():
        db_path.unlink()
    db_path.parent.mkdir(exist_ok=True)
    memory = MemoryStore(str(db_path))
    await memory.initialize()

    # Permission Manager allowing SAFE natively, denying others by default in non-interactive
    class TestPermissionManager(PermissionManager):
        async def request_permission(self, tool_name: str, args: dict, level: str) -> bool:
            print(f"    [Permission] Requested for {tool_name} (level: {level})")
            if level == "safe":
                return True
            return False  # Deny confirmations in automated tests
            
    permission_manager = TestPermissionManager(event_bus, cli_mode=False)

    # Force fully offline mode
    runtime = OllamaRuntime(model="qwen3-vl:4b-instruct", timeout=10.0)
    local_provider = LocalProvider(runtime=runtime)
    
    # We do NOT pass a cloud provider to router
    router = AIRouter(local_provider, cloud_provider=None)

    orchestrator = AgentOrchestrator(
        router=router,
        tool_registry=registry,
        memory=memory,
        event_bus=event_bus,
        permission_manager=permission_manager,
    )

    tests = [
        {
            "name": "Deterministic Match (Volume)",
            "input": "set my volume to 40",
            "expected_tool": "set_volume"
        },
        {
            "name": "Deterministic Match (Screenshot)",
            "input": "take a screenshot",
            "expected_tool": "take_screenshot"
        },
        {
            "name": "Offline LLM Conversation",
            "input": "Hey Airi, tell me a short joke.",
            "expected_tool": None
        },
        {
            "name": "Offline LLM Reasoning",
            "input": "What is 27 * 43? Think step by step.",
            "expected_tool": None
        },
        {
            "name": "Internet Required Tool Rejection",
            "input": "Open YouTube and subscribe to ElectroBOOM.",
            "expected_tool": None
        }
    ]
    
    for i, test in enumerate(tests, 1):
        print(f"\nTest {i}: {test['name']}")
        print(f"Input: \"{test['input']}\"")
        
        # We hook into events to check if a tool was executed
        executed_tool = None
        async def on_tool(event):
            nonlocal executed_tool
            executed_tool = event.tool_name
            
        event_bus.subscribe(ToolExecutionStarted, on_tool)
        
        try:
            response = await orchestrator.process_input(test["input"], source="cli")
            print(f"Airi: {response}")
            if test["expected_tool"]:
                if executed_tool == test["expected_tool"]:
                    print("✅ Success: Expected tool was executed.")
                else:
                    print(f"❌ Failed: Expected {test['expected_tool']}, got {executed_tool}")
            else:
                if executed_tool:
                    print(f"⚠ Note: Unexpectedly executed tool: {executed_tool}")
                else:
                    print("✅ Success: Handled via conversational response.")
        except Exception as e:
            print(f"❌ Error during test: {e}")
            
        event_bus.unsubscribe(ToolExecutionStarted, on_tool)

    await memory.close()
    if db_path.exists():
        db_path.unlink()
        
    print("\n" + "=" * 60)
    print("  Offline tests complete.")
    print("=" * 60)

if __name__ == "__main__":
    asyncio.run(run_offline_integration())

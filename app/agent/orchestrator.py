"""Agent orchestrator — main loop for processing user input."""
from __future__ import annotations

from typing import Any

import structlog

from app.ai.router import AIRouter
from app.ai.schemas import AIResponse
from app.agent.context import AgentContext
from app.agent.executor import ToolExecutor
from app.core.events.bus import EventBus
from app.core.events.events import (
    AssistantResponseReady,
    AssistantThinking,
    UserInputReceived,
)
from app.core.permissions.manager import PermissionManager
from app.memory.store import MemoryStore
from app.tools.registry import ToolRegistry

logger = structlog.get_logger(__name__)


class AgentOrchestrator:
    """The main agent loop for processing input and managing execution.

    Flow: Input → Classify → (Tool Call | AI Response) → Verify → Respond
    """

    def __init__(
        self,
        router: AIRouter,
        tool_registry: ToolRegistry,
        memory: MemoryStore,
        event_bus: EventBus,
        permission_manager: PermissionManager,
    ) -> None:
        self.router = router
        self.tool_registry = tool_registry
        self.memory = memory
        self.event_bus = event_bus
        self.permission_manager = permission_manager
        self.context = AgentContext()
        self.executor = ToolExecutor(tool_registry, event_bus)

    async def process_input(self, text: str, source: str = "cli") -> str:
        """Process user input through the full agent pipeline.

        Args:
            text: The user's input text.
            source: Where the input came from ('cli', 'voice', 'text').

        Returns:
            The assistant's response text.
        """
        logger.info("Processing input", source=source, text=text)

        # 1. Publish input event
        await self.event_bus.publish(
            UserInputReceived(text=text, input_source=source)
        )

        # 2. Add to conversation context
        self.context.add_user_message(text)

        # 3. Signal thinking
        await self.event_bus.publish(AssistantThinking())

        # 4. Route through AI
        tools_schema = self.tool_registry.to_openai_tools()
        response = await self.router.process(
            text,
            conversation=self.context.get_messages(),
            tools=tools_schema,
        )

        # 5. Handle tool calls
        if response.tool_calls:
            return await self._handle_tool_calls(response, tools_schema)

        # 6. Pure text response
        if response.text:
            self.context.add_assistant_message(response.text)
            await self.event_bus.publish(
                AssistantResponseReady(text=response.text)
            )

        return response.text or "I'm not sure how to help with that."

    async def _handle_tool_calls(
        self, response: AIResponse, tools_schema: list[dict]
    ) -> str:
        """Execute tool calls and build a response."""
        results: list[str] = []

        for tool_call in response.tool_calls:
            tool_entry = self.tool_registry.get_tool(tool_call.name)

            # Permission check
            if tool_entry:
                definition, _ = tool_entry
                perm_level = definition.permission_level
                # Map tool permission to core permission level
                from app.core.permissions.manager import PermissionLevel
                core_level = PermissionLevel(perm_level.value)
                allowed = await self.permission_manager.request_permission(
                    tool_call.name, tool_call.arguments, core_level
                )
                if not allowed:
                    msg = f"Permission denied for {tool_call.name}."
                    self.context.add_tool_result(tool_call.id, msg, False)
                    results.append(msg)
                    continue

            # Execute
            result = await self.executor.execute(
                tool_call.name, tool_call.arguments
            )

            if result.success:
                msg = result.message or f"Done. {tool_call.name} completed."
                if result.data is not None:
                    msg = f"{msg} Result: {result.data}"
                self.context.add_tool_result(tool_call.id, msg, True)
                results.append(msg)
            else:
                msg = result.error or f"{tool_call.name} failed."
                self.context.add_tool_result(tool_call.id, msg, False)
                results.append(f"Error: {msg}")

        final = " ".join(results) if results else "Done."
        self.context.add_assistant_message(final)
        await self.event_bus.publish(AssistantResponseReady(text=final))
        return final

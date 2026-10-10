"""Agent orchestrator — main loop for processing user input."""
from __future__ import annotations

import structlog
import copy

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
from app.core.permissions.manager import PermissionLevel, PermissionManager
from app.memory.store import MemoryStore
from app.tools.registry import ToolRegistry

logger = structlog.get_logger(__name__)

MAX_AGENT_STEPS = 10

class AgentOrchestrator:
    """The main agent loop for processing input and managing execution."""

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
        self.pending_task = None

    async def process_input(self, text: str, source: str = "cli") -> str:
        logger.info("Processing input", source=source, text=text)
        if hasattr(self, '_tools_executed_this_turn'):
            delattr(self, '_tools_executed_this_turn')

        await self.event_bus.publish(UserInputReceived(text=text, input_source=source))
        
        if self.pending_task:
            self.context.add_user_message(text)
            response = await self.pending_task.handle_input(text)
            if self.pending_task.is_complete:
                correction = getattr(self.pending_task, "correction_instruction", None)
                self.pending_task = None
                if correction:
                    # Immediately process the replacement instruction in the main agent loop
                    return await self.process_input(correction, source=source)
            if response is not None:
                self.context.add_assistant_message(response)
                await self.event_bus.publish(AssistantResponseReady(text=response))
            return response or "Task completed."

        self.context.add_user_message(text)
        tools_schema = self.tool_registry.to_openai_tools()

        for step in range(MAX_AGENT_STEPS):
            await self.event_bus.publish(AssistantThinking())

            # We pass text to router only for classification, but we don't want router to mutate our context list.
            # So we pass a copy, and let router do whatever. We already added the user message.
            messages_copy = copy.deepcopy(self.context.get_messages())
            # router appends `text` if provided. Since we already appended, we pass empty text for conversation,
            # BUT router uses `text` for classification.
            # Looking at router.py: `intent = await self.classify_intent(text)`.
            # So we pass `text` on step 0, but to prevent it from appending it AGAIN to messages_copy,
            # we must pop the last one we added from messages_copy, so router can append it!
            if step == 0:
                messages_copy.pop()
                current_text = text
            else:
                current_text = ""

            response = await self.router.process(
                current_text,
                conversation=messages_copy,
                tools=tools_schema,
            )

            if response.tool_calls:
                self._tools_executed_this_turn = True
                interactive_response, continue_loop, final_results = await self._handle_tool_calls(response, tools_schema)
                if interactive_response is not None:
                    return interactive_response
                cloud_avail = False
                if hasattr(self.router, "is_cloud_available"):
                    import inspect
                    res = self.router.is_cloud_available()
                    if inspect.iscoroutine(res):
                        cloud_avail = bool(await res)
                    else:
                        cloud_avail = bool(res)

                has_local_runtime = (
                    hasattr(self.router, "local_provider")
                    and getattr(self.router.local_provider, "runtime", None) is not None
                )
                can_continue = continue_loop and (cloud_avail or has_local_runtime)
                if not can_continue:
                    # Return the aggregated results as the final response
                    return final_results
            else:
                if response.text:
                    # Check for hallucinated tool success
                    hallucinated = False
                    # Basic heuristic: contains tool name + "succeed" or "success" without any tools executed
                    if "succeed" in response.text.lower() or "success" in response.text.lower() or "execut" in response.text.lower() or "done" in response.text.lower():
                        for tool in self.tool_registry.list_tools():
                            if tool.name in response.text:
                                hallucinated = True
                                break
                    if hallucinated and not hasattr(self, '_tools_executed_this_turn'):
                        logger.warning("hallucinated_tool_success", text=response.text)
                        self.context.add_assistant_message(response.text)
                        msg = "Tool call required to perform this task. You claimed success but no tool was executed. You must emit a valid JSON tool call."
                        self.context.add_user_message(msg)
                        continue

                    self.context.add_assistant_message(response.text)
                    await self.event_bus.publish(AssistantResponseReady(text=response.text))
                    return response.text
                return "Task completed."
                
        final_msg = "I've reached my maximum number of steps for this task."
        self.context.add_assistant_message(final_msg)
        await self.event_bus.publish(AssistantResponseReady(text=final_msg))
        return final_msg

    async def _handle_tool_calls(
        self, response: AIResponse, tools_schema: list[dict]
    ) -> tuple[str | None, bool, str]:
        """Validate, permission-check, execute, and append results.
        Returns (interactive_response, continue_loop, final_results).
        """
        results: list[str] = []
        should_continue = True

        for tool_call in response.tool_calls:
            tool_name = tool_call.name

            tool_entry = self.tool_registry.get_tool(tool_name)
            if not tool_entry:
                msg = f"I tried to call '{tool_name}' but that tool doesn't exist."
                self.context.add_tool_result(tool_call.id, msg, False)
                results.append(msg)
                continue

            definition, _ = tool_entry
            core_level = PermissionLevel(definition.permission_level.value)
            allowed = await self.permission_manager.request_permission(
                tool_name, tool_call.arguments, core_level
            )
            if not allowed:
                msg = f"Permission denied for '{tool_name}'."
                self.context.add_tool_result(tool_call.id, msg, False)
                results.append(msg)
                should_continue = False
                continue

            result = await self.executor.execute(tool_name, tool_call.arguments)

            if getattr(result, 'task', None):
                self.pending_task = result.task
                if hasattr(self.pending_task, 'permission_manager'):
                    pass
                self.pending_task.permission_manager = self.permission_manager
                task_response = await self.pending_task.start()
                self.context.add_tool_result(tool_call.id, f"Started interactive task. Message: {task_response}", True)
                self.context.add_assistant_message(task_response)
                await self.event_bus.publish(AssistantResponseReady(text=task_response))
                return task_response, False, ""

            import json
            if result.success:
                # Return the structured result back to the model as JSON string
                res_dict = {"success": True}
                if result.message:
                    res_dict["message"] = result.message
                if result.data is not None:
                    res_dict["data"] = result.data
                msg = json.dumps(res_dict)
                self.context.add_tool_result(tool_call.id, msg, True)
                results.append(f"{tool_name} succeeded.")
            else:
                res_dict = {"success": False, "error": result.error or "Unknown error"}
                msg = json.dumps(res_dict)
                self.context.add_tool_result(tool_call.id, msg, False)
                results.append(f"Error: {result.error or 'Unknown error'}")
                should_continue = False

        final_msg = " ".join(results)
        self.context.add_assistant_message(final_msg)
        return None, should_continue, final_msg

"""Agent orchestrator — main loop for processing user input."""
from __future__ import annotations

import copy
import re
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

    @staticmethod
    def _is_action_request(text: str) -> bool:
        """Check if user instruction is an action-oriented command requiring execution."""
        clean = text.strip().lower()
        if not clean:
            return False
        action_prefixes = (
            "open", "launch", "start", "run", "click", "select", "press",
            "search", "navigate", "go to", "close", "play", "type", "fill",
            "expand", "collapse", "like", "dislike", "subscribe", "unsubscribe",
            "share", "scroll", "set", "change", "turn", "mute", "unmute",
            "lock", "shutdown", "reboot", "suspend"
        )
        words = re.findall(r"\b\w+\b", clean)
        if words and words[0] in action_prefixes:
            return True
        if any(phrase in clean for phrase in (
            "new tab", "in the new tab", "in a new tab", "search for", "look up",
            "click on", "tap on", "like this", "dislike this", "subscribe to",
            "open the", "click the", "expand the", "scroll down", "scroll up"
        )):
            return True
        return False

    @staticmethod
    def _is_read_only_tool(tool_name: str) -> bool:
        """Return True if tool is an observation/inspection/query tool without mutations."""
        t_low = tool_name.lower()
        if t_low in (
            "browser_inspect", "browser_inspect_page", "browser_read", "browser_read_page",
            "browser_screenshot", "screen_observe", "screen_read", "screen_find",
            "screen_watch_start", "screen_watch_stop",
            "get_volume", "get_brightness", "get_system_info", "get_cpu_usage",
            "get_memory_usage", "get_disk_usage", "get_uptime",
            "list_running_applications", "list_directory", "search_files", "read_file",
            "network_get_status", "network_list_interfaces", "network_list_wifi",
            "network_check_connectivity", "network_get_tailscale_status",
        ):
            return True
        if t_low.startswith("get_") or t_low.startswith("list_") or t_low.startswith("read_"):
            return True
        if "inspect" in t_low or "observe" in t_low:
            return True
        return False

    async def process_input(self, text: str, source: str = "cli") -> str:
        self._tools_executed_this_turn = False
        self._last_tool_results: list[Any] = []
        self._current_turn_actions: list[dict] = []
        self._successful_tools_this_turn: list[dict] = []
        self._mutating_tools_this_turn: list[dict] = []
        self._failed_tools_this_turn: list[dict] = []

        try:
            from app.agent.task_context import get_browser_task_context
            b_ctx = get_browser_task_context()
            ctx_summary = {
                "active_browser": b_ctx.active_browser_name,
                "current_url": b_ctx.current_url,
                "current_title": b_ctx.current_title,
                "last_search_query": b_ctx.last_search_query,
                "relevant_result_type": b_ctx.relevant_result_type,
                "has_active_session": b_ctx.has_active_session(),
            }
        except Exception:
            ctx_summary = {}

        logger.info(
            "agent_input_received",
            source=source,
            text=text,
            context_before_routing=ctx_summary,
        )

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

            messages_copy = copy.deepcopy(self.context.get_messages())
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

            logger.info(
                "agent_step_router_response",
                step=step,
                has_tool_calls=bool(response.tool_calls),
                tool_names=[tc.name for tc in response.tool_calls],
                finish_reason=response.finish_reason,
                text_preview=response.text[:100] if response.text else "",
            )

            if response.tool_calls:
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
                    await self.event_bus.publish(AssistantResponseReady(text=final_results))
                    return final_results
            else:
                cleaned_text = response.text.strip() if response.text else ""
                is_action = self._is_action_request(text)
                wants_new_tab = bool(re.search(r"\bnew\s+(?:browser\s+)?tab\b", text.lower()))
                opened_new_tab = any(
                    action.get("tool") == "browser_new_tab"
                    or (action.get("tool") == "browser_navigate" and action.get("args", {}).get("new_tab"))
                    for action in self._mutating_tools_this_turn
                )

                if cleaned_text:
                    # Check for hallucinated tool success
                    hallucinated = False
                    hallucination_reason = ""
                    low_text = cleaned_text.lower()
                    
                    completion_phrases = [
                        "task completed",
                        "task is complete",
                        "task complete",
                        "action completed",
                        "successfully clicked",
                        "i clicked",
                        "i have clicked",
                        "i opened",
                        "i have opened",
                        "i played",
                        "i have played",
                        "i selected",
                        "i launched",
                        "opened a new tab",
                        "open a new tab",
                        "opening a new tab",
                        "opened new tab",
                        "navigating to",
                        "navigated to",
                        "i navigated",
                        "i have navigated",
                        "i liked",
                        "liked the video",
                        "i disliked",
                        "disliked the video",
                        "subscribed",
                        "i subscribed",
                        "subscribed to",
                        "searched for",
                        "i searched",
                        "searching for",
                    ]
                    claims_completion = (
                        any(phrase in low_text for phrase in completion_phrases)
                        or low_text in ("done.", "done!", "done", "completed.")
                    )
                    claim_patterns = (
                        r"\b(?:opened|navigated|navigating|clicked|selected|liked|disliked|subscribed|searched|launched|running)\b",
                        r"\b(?:i have|i've|i did|already)\b",
                    )
                    claims_action_done = claims_completion or any(re.search(cp, low_text) for cp in claim_patterns)

                    # 1. No tools executed at all this turn
                    if not self._tools_executed_this_turn:
                        for tool in self.tool_registry.list_tools():
                            if tool.name.lower() in low_text:
                                hallucinated = True
                                hallucination_reason = "No tool was executed, but tool name was mentioned claiming execution."
                                break
                        if not hallucinated:
                            if claims_completion:
                                hallucinated = True
                                hallucination_reason = "No tool was executed, but completion was claimed."
                            elif is_action and claims_action_done:
                                hallucinated = True
                                hallucination_reason = "Action was requested and claimed done, but no tool was executed."

                    # 2. Action requested, but only read-only / inspection tools executed
                    elif is_action and not self._mutating_tools_this_turn:
                        if claims_completion or claims_action_done:
                            hallucinated = True
                            hallucination_reason = "Action was requested, but only read-only/inspection tools were executed."

                    # 3. Failed tools: tool failed, but response claims completion/success
                    elif self._failed_tools_this_turn and not self._mutating_tools_this_turn:
                        if claims_completion or claims_action_done:
                            hallucinated = True
                            hallucination_reason = "Tool execution failed, but completion/success was claimed."

                    # 4. New tab requested: verify new-tab tool succeeded
                    elif wants_new_tab and not opened_new_tab:
                        if claims_completion or "new tab" in low_text:
                            hallucinated = True
                            hallucination_reason = "New tab was requested, but no new-tab tool was successfully executed."

                    if hallucinated:
                        logger.warning(
                            "hallucinated_tool_success_detected",
                            text=cleaned_text,
                            reason=hallucination_reason,
                            step=step,
                        )
                        if step < MAX_AGENT_STEPS - 1:
                            self.context.add_assistant_message(cleaned_text)
                            if is_action and not self._mutating_tools_this_turn and self._tools_executed_this_turn:
                                prompt_msg = "Action tool call required. You only inspected the page without executing the requested action. You must emit an action tool call (e.g. browser_click_element, browser_navigate, browser_search_page)."
                            elif wants_new_tab and not opened_new_tab:
                                prompt_msg = "Tool call required to open a new tab. You must emit browser_new_tab or browser_navigate with new_tab=True."
                            elif self._failed_tools_this_turn and not self._mutating_tools_this_turn:
                                prompt_msg = "The previous tool execution failed. Do not claim completion. Attempt an alternative tool or report the failure."
                            else:
                                prompt_msg = "Tool call required to perform this task. You claimed success or completion, but no tool was executed. You must emit a valid tool call."
                            self.context.add_user_message(prompt_msg)
                            continue
                        else:
                            if not self._tools_executed_this_turn:
                                err_msg = "Tool call required to perform this task. No tool was executed."
                            else:
                                err_msg = "Tool call required to perform this task. No action tool was executed."
                            self.context.add_assistant_message(err_msg)
                            await self.event_bus.publish(AssistantResponseReady(text=err_msg))
                            return err_msg

                    self.context.add_assistant_message(cleaned_text)
                    await self.event_bus.publish(AssistantResponseReady(text=cleaned_text))
                    return cleaned_text
                else:
                    if self._mutating_tools_this_turn:
                        res_msg = "Task completed."
                    elif self._successful_tools_this_turn and not is_action:
                        res_msg = "Task completed."
                    elif self._failed_tools_this_turn:
                        err_res = self._failed_tools_this_turn[-1].get("result", None)
                        msg = getattr(err_res, "error", "") or getattr(err_res, "message", "") or "execution failed"
                        res_msg = f"I was unable to complete the request: {msg}"
                    else:
                        res_msg = "I was unable to complete the request because no action was performed."
                    self.context.add_assistant_message(res_msg)
                    await self.event_bus.publish(AssistantResponseReady(text=res_msg))
                    return res_msg
                
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
                logger.error(
                    "tool_invocation_failed_missing",
                    selected_tool=tool_name,
                    args=tool_call.arguments,
                    invocation_status="missing_tool",
                    final_reason=f"Tool '{tool_name}' not registered in ToolRegistry",
                )
                msg = f"I tried to call '{tool_name}' but that tool doesn't exist."
                self.context.add_tool_result(tool_call.id, msg, False)
                results.append(msg)
                should_continue = False
                continue

            definition, _ = tool_entry
            core_level = PermissionLevel(definition.permission_level.value)
            allowed = await self.permission_manager.request_permission(
                tool_name, tool_call.arguments, core_level
            )
            if not allowed:
                logger.warning(
                    "tool_invocation_permission_denied",
                    selected_tool=tool_name,
                    args=tool_call.arguments,
                    invocation_status="permission_denied",
                    final_reason="Permission denied by user or policy",
                )
                msg = f"Permission denied for '{tool_name}'."
                self.context.add_tool_result(tool_call.id, msg, False)
                results.append(msg)
                should_continue = False
                continue

            logger.info(
                "tool_invocation_started",
                selected_tool=tool_name,
                args=tool_call.arguments,
                invocation_status="started",
            )
            result = await self.executor.execute(tool_name, tool_call.arguments)

            if getattr(result, 'task', None):
                self.pending_task = result.task
                self.pending_task.permission_manager = self.permission_manager
                task_response = await self.pending_task.start()
                self.context.add_tool_result(tool_call.id, f"Started interactive task. Message: {task_response}", True)
                self.context.add_assistant_message(task_response)
                await self.event_bus.publish(AssistantResponseReady(text=task_response))
                return task_response, False, ""

            # Check verification details
            verified = None
            if isinstance(result.data, dict) and "verified" in result.data:
                verified = result.data["verified"]
            elif result.success:
                verified = True
            else:
                verified = False

            logger.info(
                "tool_invocation_completed",
                selected_tool=tool_name,
                args=tool_call.arguments,
                invocation_status="success" if result.success else "failure",
                tool_result=result.message if result.success else result.error,
                verification_result=verified,
                final_reason="verified_success" if (result.success and verified is not False) else (result.error or "execution_failed"),
            )

            import json
            if result.success:
                self._tools_executed_this_turn = True
                action_info = {"tool": tool_name, "args": tool_call.arguments, "success": True, "result": result, "verified": verified}
                self._current_turn_actions.append(action_info)
                self._successful_tools_this_turn.append(action_info)
                if not self._is_read_only_tool(tool_name):
                    self._mutating_tools_this_turn.append(action_info)
                res_dict = {"success": True}
                if result.message:
                    res_dict["message"] = result.message
                if result.data is not None:
                    res_dict["data"] = result.data
                msg = json.dumps(res_dict)
                self.context.add_tool_result(tool_call.id, msg, True)
                results.append(result.message or f"{tool_name} succeeded.")
            else:
                action_info = {"tool": tool_name, "args": tool_call.arguments, "success": False, "result": result, "verified": False}
                self._current_turn_actions.append(action_info)
                self._failed_tools_this_turn.append(action_info)
                res_dict = {"success": False, "error": result.error or "Unknown error"}
                if result.message:
                    res_dict["message"] = result.message
                msg = json.dumps(res_dict)
                self.context.add_tool_result(tool_call.id, msg, False)
                err_detail = result.message or result.error or "Unknown error"
                results.append(f"Error: {err_detail}")
                should_continue = False

        final_msg = " ".join(results)
        self.context.add_assistant_message(final_msg)
        return None, should_continue, final_msg

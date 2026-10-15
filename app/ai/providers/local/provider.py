"""Local AI provider using pattern matching for intent classification.

No ML models required. Handles simple deterministic commands locally
and falls back to cloud for complex reasoning.
"""
from __future__ import annotations

import re
import uuid
from typing import AsyncIterator

from app.ai.interfaces.provider import AIProvider
from app.ai.schemas import AIResponse, ClassifiedIntent, IntentType, Message, ToolCall


class LocalProvider(AIProvider):
    """Pattern-matching AI provider for simple local commands.

    Recognises commands like:
    - 'set volume to 40'  / 'volume 40'
    - 'set brightness to 60' / 'brightness 80%'
    - 'open firefox' / 'launch terminal'
    - 'take a screenshot'
    - 'lock screen'
    - 'mute' / 'unmute'
    """

    def __init__(self, runtime: LocalModelRuntime | None = None) -> None:
        """Build the pattern registry.

        Each entry: (compiled_regex, tool_name, arg_names, default_args)
        tool_name must match exactly what's registered in ToolRegistry.
        """
        self.runtime = runtime
        # Matches: "35%", "35 %", "35 percent", or plain "35"
        _num = r"(\d+)\s*(?:%|percent\b)?"

        self._patterns: list[tuple[re.Pattern, str, list[str], dict]] = [
            # Volume -------------------------------------------------------
            (re.compile(
                r"(?:set|change)\s+(?:the\s+)?volume\s+(?:to\s+)?" + _num,
                re.I,
            ), "set_volume", ["level"], {}),
            (re.compile(r"volume\s+(?:to\s+)?" + _num, re.I),
             "set_volume", ["level"], {}),
            (re.compile(
                r"(?:increase|turn\s+up|raise)\s+(?:the\s+)?volume\s+(?:to\s+)?" + _num,
                re.I,
            ), "set_volume", ["level"], {}),
            (re.compile(
                r"(?:decrease|turn\s+down|lower)\s+(?:the\s+)?volume\s+(?:to\s+)?" + _num,
                re.I,
            ), "set_volume", ["level"], {}),
            (re.compile(r"\bmute\b", re.I), "mute", [], {}),
            (re.compile(r"\bunmute\b", re.I), "unmute", [], {}),

            # Brightness ----------------------------------------------------
            (re.compile(
                r"(?:set|change)\s+(?:the\s+)?brightness\s+(?:to\s+)?" + _num,
                re.I,
            ), "set_brightness", ["level"], {}),
            (re.compile(r"brightness\s+(?:to\s+)?" + _num, re.I),
             "set_brightness", ["level"], {}),
            (re.compile(
                r"(?:increase|raise|turn\s+up)\s+(?:the\s+)?brightness\s+(?:to\s+)?" + _num,
                re.I,
            ), "set_brightness", ["level"], {}),

            # Terminal Run Visible ------------------------------------------
            (re.compile(
                r"^(?:open|launch)\s+([\w.\-]+)\s+(?:and|then)\s+(?:run|execute|type)\s+(.*)$",
                re.I,
            ), "terminal_run_visible", ["terminal", "command"], {}),

            # Browser Search ------------------------------------------------
            (re.compile(
                r"^(?:open|launch)\s+([\w.\-]+)\s*(?:browser)?\s+(?:and|then)\s+search\s+([\w.\-]+)\s+for\s+(.*)$",
                re.I,
            ), "browser_search", ["browser_name", "site", "query"], {}),
            (re.compile(
                r"^(?:please\s+|just\s+)?search\s+(youtube|google|duckduckgo)\s+for\s+(.+?)[.!?]?$",
                re.I,
            ), "browser_search", ["site", "query"], {"browser_name": ""}),

            # Screen Observation & Awareness --------------------------------
            (re.compile(
                r"^(?:what(?:'s|\s+is)\s+(?:on|showing\s+on)\s+(?:my\s+|the\s+)?screen|"
                r"what\s+window\s+is\s+active|which\s+window\s+is\s+active|"
                r"read\s+(?:this\s+|the\s+)?error(?:\s+on\s+screen)?|"
                r"what\s+(?:is\s+|does\s+)(?:this\s+|the\s+)(?:webpage\s+showing|dialog\s+say))[.!?]?$",
                re.I,
            ), "screen_observe", [], {"target": "auto", "focus_question": ""}),

            # Screen Watch Mode ---------------------------------------------
            (re.compile(r"^(?:watch\s+my\s+screen|start\s+watching\s+(?:my\s+)?screen)[.!?]?$", re.I),
             "screen_watch_start", [], {"interval": 2.0}),
            (re.compile(r"^(?:stop\s+watching\s+(?:my\s+)?screen)[.!?]?$", re.I),
             "screen_watch_stop", [], {}),

            # First Option / Video Selection --------------------------------
            (re.compile(r"^(?:open|play)\s+(?:the\s+)?first\s+video(?:\s+on\s+youtube)?[.!?]?$", re.I),
             "browser_select_first", [], {"item_type": "video", "query": ""}),
            (re.compile(r"^(?:select|click)\s+(?:the\s+)?first\s+(?:option|result|search\s+result)(?:\s+in\s+the\s+browser)?[.!?]?$", re.I),
             "browser_select_first", [], {"item_type": "result", "query": ""}),

            # Applications ─ supports multi-word app names (e.g., "Burp Suite", "helm browser", "Burp sweet"),
            # while compound actions, URLs, new-tab requests, or descriptive browser references are never routed to app launch.
            (re.compile(
                r"^(?:open|launch|start|run)\s+(?!.*(?:\band\b|\bthen\b|\bsearch\b|\brun\b|\bfirst\b|\bsecond\b|\bthird\b|\bfourth\b|\bfifth\b|\b1st\b|\b2nd\b|\b3rd\b|\bvideo\b|\bresult\b|\boption\b|\bitem\b|\blink\b|\bcurrent\b|\bone\b|\bthat\s+video\b|\bthat\s+one\b|\btab\b|\bbutton\b|\bshare\b|\blike\b|\bdislike\b|\bsubscribe\b|\.(?:com|org|net|io|edu|gov|dev)\b))([a-zA-Z0-9_\-\.\s]{1,50}?)[.!?]?$",
                re.I,
            ), "launch_application", ["name"], {}),

            # Screenshot ----------------------------------------------------
            (re.compile(r"(?:take\s+a?\s*)?screenshot", re.I),
             "take_screenshot", [], {}),

            # Screen lock ---------------------------------------------------
            (re.compile(r"lock\s+(?:the\s+)?(?:screen|computer|pc)", re.I),
             "lock_screen", [], {}),

            # System info ---------------------------------------------------
            (re.compile(r"(?:system|cpu|memory|ram)\s+(?:info|usage|status)", re.I),
             "get_system_info", [], {}),
        ]

    def classify_intent(self, text: str) -> ClassifiedIntent:
        """Classify user intent via pattern matching.

        Returns a ClassifiedIntent with tool_name/tool_args when a
        known command pattern matches, or CONVERSATION otherwise.
        """
        text = text.strip()

        # 1. Explicit New Tab & Domain Navigation routing FIRST
        # Handles:
        # - "open a new tab" / "new tab"
        # - "open leetcode.com in a new tab" / "open leetcode.com in new tab"
        # - "in the new tab, open leadcode.com"
        # - "open a new tab and go to leetcode.com"
        # - "open leetcode.com" / "navigate to github.com"
        try:
            if re.search(
                r"^(?:please\s+|just\s+|can\s+you\s+)?(?:open\s+(?:a\s+|the\s+|another\s+)?new\s+(?:browser\s+)?tab|new\s+(?:browser\s+)?tab)[.!?]?$",
                text,
                re.I,
            ):
                return ClassifiedIntent(
                    type=IntentType.TOOL_CALL,
                    confidence=1.0,
                    tool_name="browser_new_tab",
                    tool_args={"url": "about:blank"},
                    requires_cloud=False,
                )

            from app.tools.browser.domain_aliases import normalize_domain_url

            # Compound new-tab phrasing: "open a new tab and open/go to/navigate to <url>"
            compound_new_tab = re.search(
                r"^(?:please\s+|just\s+|can\s+you\s+)?open\s+(?:a\s+|the\s+|another\s+)?new\s+(?:browser\s+)?tab\s+(?:and\s+|then\s+|to\s+|with\s+|for\s+)(?:open\s+|navigate\s+to\s+|go\s+to\s+|visit\s+)?(.+?)[.!?]?$",
                text,
                re.I,
            )
            if compound_new_tab:
                target_cand = compound_new_tab.group(1).strip()
                norm_url, _ = normalize_domain_url(target_cand)
                return ClassifiedIntent(
                    type=IntentType.TOOL_CALL,
                    confidence=1.0,
                    tool_name="browser_navigate",
                    tool_args={"url": norm_url, "new_tab": True},
                    requires_cloud=False,
                )

            # Standard navigation / new-tab phrasing
            nav_match = re.search(
                r"^(?:please\s+|just\s+|can\s+you\s+)?(?:(?:in|on|into)\s+(?:a\s+|the\s+|another\s+)?new\s+(?:browser\s+)?tab,?\s+)?(?:open(?:\s+up)?|navigate\s+to|go\s+to|visit)\s+(.+?)(?:\s+(?:in|on|into)\s+(?:a\s+|the\s+|another\s+)?new\s+(?:browser\s+)?tab)?[.!?]?$",
                text,
                re.I,
            )
            if nav_match:
                target_cand = nav_match.group(1).strip()
                is_explicit_new_tab = bool(re.search(r"\bnew\s+(?:browser\s+)?tab\b", text, re.I))
                # Do not treat compound app/search/multi-step commands ("open firefox and search...", "open youtube and subscribe...") as direct URL navigation
                if not re.search(r"\b(?:and|then)\b", target_cand, re.I):
                    norm_url, was_alias = normalize_domain_url(target_cand)
                    is_web_target = (
                        was_alias
                        or norm_url.startswith("http://")
                        or norm_url.startswith("https://")
                        or bool(re.search(r"\b[a-zA-Z0-9_\-]+\.(?:com|org|net|io|edu|gov|dev|co|in|me|ai)\b", target_cand, re.I))
                        or is_explicit_new_tab
                    )
                    if is_web_target:
                        return ClassifiedIntent(
                            type=IntentType.TOOL_CALL,
                            confidence=1.0,
                            tool_name="browser_navigate",
                            tool_args={"url": norm_url, "new_tab": is_explicit_new_tab},
                            requires_cloud=False,
                        )
        except Exception:
            pass

        # 2. Deterministic contextual browser reference routing ("click the first video")
        try:
            from app.agent.task_context import is_browser_result_reference, parse_browser_reference
            if is_browser_result_reference(text):
                ref = parse_browser_reference(text)
                return ClassifiedIntent(
                    type=IntentType.TOOL_CALL,
                    confidence=1.0,
                    tool_name="browser_select_first",
                    tool_args={
                        "item_type": ref.get("item_type", "video"),
                        "query": ref.get("query", ""),
                        "index": ref.get("index", 1),
                    },
                    requires_cloud=False,
                )
        except Exception:
            pass

        # 3. Contextual general browser interaction routing when active session exists
        try:
            from app.agent.task_context import is_browser_interaction_command, parse_browser_interaction
            if is_browser_interaction_command(text):
                parsed = parse_browser_interaction(text)
                return ClassifiedIntent(
                    type=IntentType.TOOL_CALL,
                    confidence=1.0,
                    tool_name=parsed["tool_name"],
                    tool_args=parsed["tool_args"],
                    requires_cloud=False,
                )
        except Exception:
            pass

        # 4. Standard regex pattern table
        for pattern, tool_name, arg_names, default_args in self._patterns:
            match = pattern.search(text)
            if match:
                args = dict(default_args)
                groups = match.groups()
                for i, arg_name in enumerate(arg_names):
                    if i < len(groups) and groups[i] is not None:
                        raw = groups[i].strip()
                        try:
                            args[arg_name] = int(raw)
                        except ValueError:
                            args[arg_name] = raw
                return ClassifiedIntent(
                    type=IntentType.TOOL_CALL,
                    confidence=1.0,
                    tool_name=tool_name,
                    tool_args=args,
                    requires_cloud=False,
                )

        # No local match — needs cloud or is conversational
        return ClassifiedIntent(
            type=IntentType.CONVERSATION,
            confidence=0.5,
            requires_cloud=self.runtime is None,
        )

    # --- AIProvider interface ---

    async def respond(
        self,
        messages: list[Message],
        tools: list[dict] | None = None,
        temperature: float = 0.7,
        max_tokens: int = 1024,
    ) -> AIResponse:
        """Respond using local pattern matching or LocalModelRuntime."""
        if not messages:
            return AIResponse(text="")

        last_msg_obj = messages[-1]
        last_role = getattr(last_msg_obj, "role", "user")
        last_msg = last_msg_obj.content or ""

        # Only pattern-match on direct user utterances (not tool outputs or internal orchestrator re-prompts)
        if last_role == "user" and not last_msg.startswith("Tool call required to perform this task"):
            intent = self.classify_intent(last_msg)
            if intent.type == IntentType.TOOL_CALL and intent.tool_name:
                call = ToolCall(
                    id=f"call_{uuid.uuid4().hex[:12]}",
                    name=intent.tool_name,
                    arguments=intent.tool_args,
                )
                return AIResponse(text="", tool_calls=[call], finish_reason="tool_calls")

        if self.runtime:
            return await self.runtime.respond(messages, tools, temperature, max_tokens)

        return AIResponse(
            text=(
                "I can't handle that locally. "
                "Please configure a local or cloud AI provider for complex requests."
            ),
            finish_reason="stop",
        )

    async def respond_stream(
        self,
        messages: list[Message],
        tools: list[dict] | None = None,
        temperature: float = 0.7,
    ) -> AsyncIterator[str]:
        """Stream response (single yield for local)."""
        response = await self.respond(messages, tools, temperature)
        yield response.text

    async def vision(
        self,
        prompt: str,
        images: list[str],
        tools: list[dict] | None = None,
    ) -> AIResponse:
        """Analyze images using local vision processor if runtime is available."""
        if self.runtime and images:
            import base64
            from app.tools.screen.vision import get_screen_vision_processor
            try:
                raw_bytes = base64.b64decode(images[0])
                proc = get_screen_vision_processor()
                res = await proc.analyze_screen(raw_bytes, focus_prompt=prompt)
                if res.get("success"):
                    return AIResponse(text=res.get("summary", ""), finish_reason="stop")
                else:
                    return AIResponse(text=res.get("message", "Visual inspection failed."), finish_reason="error")
            except Exception as e:
                return AIResponse(text=f"Visual analysis error: {e}", finish_reason="error")

        return AIResponse(
            text="Vision requires a cloud AI provider. Set OPENAI_API_KEY in your .env file."
        )

    def is_available(self) -> bool:
        return True

    def supports_vision(self) -> bool:
        return self.runtime is not None

    def supports_tools(self) -> bool:
        return True

    @property
    def name(self) -> str:
        return "local"
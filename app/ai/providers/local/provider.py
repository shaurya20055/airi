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

    def __init__(self) -> None:
        """Build the pattern registry.

        Each entry: (compiled_regex, tool_name, arg_names, default_args)
        tool_name must match exactly what's registered in ToolRegistry.
        """
        self._patterns: list[tuple[re.Pattern, str, list[str], dict]] = [
            # Volume -------------------------------------------------------
            (re.compile(
                r"(?:set|change)\s+(?:the\s+)?volume\s+(?:to\s+)?(\d+)\s*%?",
                re.I,
            ), "set_volume", ["level"], {}),
            (re.compile(r"volume\s+(\d+)\s*%?", re.I),
             "set_volume", ["level"], {}),
            (re.compile(
                r"(?:increase|turn\s+up|raise)\s+(?:the\s+)?volume\s+(?:to\s+)?(\d+)\s*%?",
                re.I,
            ), "set_volume", ["level"], {}),
            (re.compile(
                r"(?:decrease|turn\s+down|lower)\s+(?:the\s+)?volume\s+(?:to\s+)?(\d+)\s*%?",
                re.I,
            ), "set_volume", ["level"], {}),
            (re.compile(r"\bmute\b", re.I), "mute", [], {}),
            (re.compile(r"\bunmute\b", re.I), "unmute", [], {}),

            # Brightness ----------------------------------------------------
            (re.compile(
                r"(?:set|change)\s+(?:the\s+)?brightness\s+(?:to\s+)?(\d+)\s*%?",
                re.I,
            ), "set_brightness", ["level"], {}),
            (re.compile(r"brightness\s+(\d+)\s*%?", re.I),
             "set_brightness", ["level"], {}),
            (re.compile(
                r"(?:increase|raise|turn\s+up)\s+(?:the\s+)?brightness\s+(?:to\s+)?(\d+)\s*%?",
                re.I,
            ), "set_brightness", ["level"], {}),

            # Applications --------------------------------------------------
            (re.compile(
                r"(?:open|launch|start|run)\s+(.+)",
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
            requires_cloud=True,
        )

    # --- AIProvider interface ---

    async def respond(
        self,
        messages: list[Message],
        tools: list[dict] | None = None,
        temperature: float = 0.7,
        max_tokens: int = 1024,
    ) -> AIResponse:
        """Respond using local pattern matching."""
        if not messages:
            return AIResponse(text="")

        last_msg = messages[-1].content
        intent = self.classify_intent(last_msg)

        if intent.type == IntentType.TOOL_CALL and intent.tool_name:
            call = ToolCall(
                id=f"call_{uuid.uuid4().hex[:12]}",
                name=intent.tool_name,
                arguments=intent.tool_args,
            )
            return AIResponse(text="", tool_calls=[call], finish_reason="tool_calls")

        return AIResponse(
            text=(
                "I can't handle that locally. "
                "Please configure a cloud AI provider for complex requests."
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
        """Vision not supported locally."""
        return AIResponse(
            text="Vision requires a cloud AI provider. Set OPENAI_API_KEY in your .env file."
        )

    def is_available(self) -> bool:
        return True

    def supports_vision(self) -> bool:
        return False

    def supports_tools(self) -> bool:
        return True

    @property
    def name(self) -> str:
        return "local"

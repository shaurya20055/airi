"""Ollama runtime adapter for Local AI."""
from __future__ import annotations

import json
import uuid
from typing import AsyncIterator

import httpx
import structlog

from app.ai.providers.local.runtime import LocalModelRuntime
from app.ai.schemas import AIResponse, Message, ToolCall

logger = structlog.get_logger(__name__)


class OllamaRuntime(LocalModelRuntime):
    """Local runtime backed by an Ollama server using its OpenAI-compatible endpoint."""

    def __init__(self, base_url: str = "http://127.0.0.1:11434/v1", model: str = "llama3.2:latest", timeout: float = 30.0):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout

    async def _check_server(self) -> bool:
        """Check if server is responding."""
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                res = await client.get("http://127.0.0.1:11434/api/tags")
                return res.status_code == 200
        except Exception:
            return False

    def is_available(self) -> bool:
        """Synchronous check if configured (availability actually verified dynamically)."""
        return True

    @property
    def name(self) -> str:
        return "ollama"

    async def respond(
        self,
        messages: list[Message],
        tools: list[dict] | None = None,
        temperature: float = 0.7,
        max_tokens: int = 1024,
    ) -> AIResponse:
        """Generate response via Ollama's OpenAI compat endpoint."""
        url = f"{self.base_url}/chat/completions"
        payload = {
            "model": self.model,
            "messages": [],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        for msg in messages:
            # Format according to OpenAI specs
            m = {"role": msg.role, "content": msg.content}
            if msg.role == "tool" and msg.tool_results:
                m["tool_call_id"] = msg.tool_results[0].tool_call_id
            # Also handle previous assistant tool calls in history
            if msg.role == "assistant" and msg.tool_calls:
                m["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)}
                    }
                    for tc in msg.tool_calls
                ]
            payload["messages"].append(m)

        if tools:
            payload["tools"] = tools

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                res = await client.post(url, json=payload)
                res.raise_for_status()
                data = res.json()
        except httpx.RequestError as e:
            logger.error("Ollama connection error", error=str(e))
            return AIResponse(text=f"Error connecting to local AI ({self.name}): {e}", finish_reason="error")
        except httpx.HTTPStatusError as e:
            logger.error("Ollama HTTP error", error=str(e), text=e.response.text)
            return AIResponse(text=f"Local AI HTTP error: {e.response.status_code}", finish_reason="error")
        except Exception as e:
            logger.error("Ollama unexpected error", error=str(e))
            return AIResponse(text=f"Local AI error: {e}", finish_reason="error")

        if not data.get("choices"):
            return AIResponse(text="Empty response from local AI.")

        choice = data["choices"][0]
        msg = choice.get("message", {})

        tool_calls = []
        if "tool_calls" in msg and msg["tool_calls"]:
            for tc in msg["tool_calls"]:
                try:
                    tool_calls.append(ToolCall(
                        id=tc.get("id", f"call_{uuid.uuid4().hex[:12]}"),
                        name=tc["function"]["name"],
                        arguments=json.loads(tc["function"]["arguments"]),
                    ))
                except Exception as e:
                    logger.warning("Failed to parse tool call", error=str(e), tc=tc)

        content = msg.get("content", "") or ""
        finish_reason = choice.get("finish_reason", "stop")

        return AIResponse(
            text=content,
            tool_calls=tool_calls,
            finish_reason=finish_reason,
            usage=data.get("usage", {}),
        )

    async def respond_stream(
        self,
        messages: list[Message],
        tools: list[dict] | None = None,
        temperature: float = 0.7,
    ) -> AsyncIterator[str]:
        """Fall back to full respond for now since tool-calling stream logic is complex."""
        res = await self.respond(messages, tools, temperature)
        yield res.text

from __future__ import annotations

import json
from typing import AsyncIterator

from app.ai.interfaces.provider import AIProvider
from app.ai.schemas import Message, AIResponse, ToolCall

try:
    import openai
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False


class OpenAIProvider(AIProvider):
    """OpenAI AI provider."""

    def __init__(self, api_key: str | None = None, model: str = "gpt-6-astra"):
        """Initialize the OpenAI provider."""
        self.api_key = api_key
        self.model = model
        self.client = openai.AsyncOpenAI(api_key=api_key) if OPENAI_AVAILABLE and api_key else None

    async def respond(self, messages: list[Message], tools: list[dict] | None = None,
                      temperature: float = 0.7, max_tokens: int = 1024) -> AIResponse:
        """Respond using OpenAI API."""
        if not self.is_available():
            return AIResponse(text="OpenAI is not configured or unavailable.")

        openai_messages = []
        for msg in messages:
            content = msg.content
            if msg.images:
                content = [{"type": "text", "text": msg.content}]
                for img in msg.images:
                    content.append({
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{img}"}
                    })
            openai_messages.append({"role": msg.role, "content": content})

        try:
            kwargs = {
                "model": self.model,
                "messages": openai_messages,
                "temperature": temperature,
                "max_tokens": max_tokens
            }
            if tools:
                kwargs["tools"] = tools

            response = await self.client.chat.completions.create(**kwargs)
            choice = response.choices[0]
            
            tool_calls = []
            if choice.message.tool_calls:
                for tc in choice.message.tool_calls:
                    tool_calls.append(ToolCall(
                        id=tc.id,
                        name=tc.function.name,
                        arguments=json.loads(tc.function.arguments)
                    ))
            
            return AIResponse(
                text=choice.message.content or "",
                tool_calls=tool_calls,
                finish_reason=choice.finish_reason,
                usage=dict(response.usage) if response.usage else {}
            )
        except Exception as e:
            return AIResponse(text=f"OpenAI API Error: {str(e)}")

    async def respond_stream(self, messages: list[Message], tools: list[dict] | None = None,
                             temperature: float = 0.7) -> AsyncIterator[str]:
        """Stream response from OpenAI."""
        if not self.is_available():
            yield "OpenAI is not configured or unavailable."
            return

        # Simple implementation
        response = await self.respond(messages, tools, temperature)
        yield response.text

    async def vision(self, prompt: str, images: list[str],
                     tools: list[dict] | None = None) -> AIResponse:
        """Process vision using OpenAI."""
        msg = Message(role="user", content=prompt, images=images)
        return await self.respond([msg], tools=tools)

    def is_available(self) -> bool:
        return OPENAI_AVAILABLE and self.client is not None

    def supports_vision(self) -> bool:
        return True

    def supports_tools(self) -> bool:
        return True

    @property
    def name(self) -> str:
        return "openai"

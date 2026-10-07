from __future__ import annotations

import uuid
from typing import AsyncIterator

from app.ai.interfaces.provider import AIProvider
from app.ai.schemas import ClassifiedIntent, IntentType, AIResponse, Message


class AIRouter:
    """Routes requests to the appropriate AI provider."""

    def __init__(self, local_provider: AIProvider, cloud_provider: AIProvider | None = None):
        """Initialize the router with providers."""
        self.local_provider = local_provider
        self.cloud_provider = cloud_provider

    async def classify_intent(self, text: str) -> ClassifiedIntent:
        """Classify user intent - try local first."""
        if hasattr(self.local_provider, 'classify_intent'):
            intent = self.local_provider.classify_intent(text)
            if intent.type == IntentType.TOOL_CALL:
                return intent
            # If the local provider has an underlying LLM runtime, it can handle non-tools
            if hasattr(self.local_provider, 'runtime') and self.local_provider.runtime is not None:
                intent.requires_cloud = False
                return intent
                
        # If local can't handle it or it's complex, and cloud is available
        if self.is_cloud_available():
            return ClassifiedIntent(
                type=IntentType.CONVERSATION,
                confidence=0.8,
                requires_cloud=True
            )
            
        return ClassifiedIntent(
            type=IntentType.UNKNOWN,
            confidence=0.0,
            requires_cloud=True
        )

    async def process(self, text: str, images: list[str] = None, 
                      conversation: list[Message] = None,
                      tools: list[dict] = None) -> AIResponse:
        """Process input through the appropriate provider."""
        intent = await self.classify_intent(text)
        
        messages = conversation or []
        if text or images:
            messages.append(Message(role="user", content=text, images=images or []))
            
        # If intent is fully local (either local deterministic tool or local LLM fallback)
        if not intent.requires_cloud:
            return await self.local_provider.respond(messages, tools=tools)
            
        if self.is_cloud_available():
            if images:
                return await self.cloud_provider.vision(text, images, tools=tools)
            return await self.cloud_provider.respond(messages, tools=tools)
            
        return AIResponse(text="Cloud AI is required for this request but is currently unavailable.")

    def is_cloud_available(self) -> bool:
        """Check if cloud provider is available."""
        return self.cloud_provider is not None and self.cloud_provider.is_available()

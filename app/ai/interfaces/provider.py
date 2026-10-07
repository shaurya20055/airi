from __future__ import annotations

from abc import ABC, abstractmethod
from typing import AsyncIterator

from app.ai.schemas import Message, AIResponse


class AIProvider(ABC):
    """Abstract interface for AI providers."""

    @abstractmethod
    async def respond(self, messages: list[Message], tools: list[dict] | None = None, 
                      temperature: float = 0.7, max_tokens: int = 1024) -> AIResponse:
        """Get a full response from the AI."""
        pass
    
    @abstractmethod
    async def respond_stream(self, messages: list[Message], tools: list[dict] | None = None,
                             temperature: float = 0.7) -> AsyncIterator[str]:
        """Get a streamed response from the AI."""
        pass
    
    @abstractmethod
    async def vision(self, prompt: str, images: list[str], 
                     tools: list[dict] | None = None) -> AIResponse:
        """Process an image query."""
        pass
    
    @abstractmethod
    def is_available(self) -> bool:
        """Check if the provider is configured and available."""
        pass
    
    @abstractmethod
    def supports_vision(self) -> bool:
        """Check if the provider supports vision capabilities."""
        pass
    
    @abstractmethod
    def supports_tools(self) -> bool:
        """Check if the provider supports tool calling."""
        pass
    
    @property
    @abstractmethod
    def name(self) -> str:
        """Get the provider name."""
        pass

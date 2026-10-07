"""Base abstractions for Local AI Model Runtimes."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import AsyncIterator

from app.ai.schemas import AIResponse, Message

class LocalModelRuntime(ABC):
    """Abstract base class for local offline AI runtimes (e.g. Ollama, llama.cpp)."""
    
    @abstractmethod
    async def respond(self, messages: list[Message], tools: list[dict] | None = None, temperature: float = 0.7, max_tokens: int = 1024) -> AIResponse:
        """Generate a complete response."""
        ...
        
    @abstractmethod
    async def respond_stream(self, messages: list[Message], tools: list[dict] | None = None, temperature: float = 0.7) -> AsyncIterator[str]:
        """Stream a response incrementally."""
        ...
        
    @abstractmethod
    def is_available(self) -> bool:
        """Return True if the runtime is reachable/active."""
        ...
        
    @property
    @abstractmethod
    def name(self) -> str:
        """The name of the runtime (e.g., 'ollama')."""
        ...

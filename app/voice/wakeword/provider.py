from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Callable

from pydantic import BaseModel

class WakeWordResult(BaseModel):
    """Result from a wake word detection."""
    detected: bool
    confidence: float = 0.0
    keyword: str = ''

class WakeWordProvider(ABC):
    """Abstract interface for Wake Word detection providers."""
    
    @abstractmethod
    async def start_listening(self, callback: Callable[[WakeWordResult], None]) -> None:
        """Start listening for the wake word."""
        pass
    
    @abstractmethod
    async def stop_listening(self) -> None:
        """Stop listening for the wake word."""
        pass
    
    @abstractmethod
    def is_available(self) -> bool:
        """Check if the provider is available and ready."""
        pass

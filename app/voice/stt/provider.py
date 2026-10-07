from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel, Field
import numpy as np

class STTResult(BaseModel):
    """Result from a Speech-to-Text operation."""
    text: str
    confidence: float = 0.0
    language: str = 'en'
    segments: list[dict] = Field(default_factory=list)

class STTProvider(ABC):
    """Abstract interface for Speech-to-Text providers."""
    
    @abstractmethod
    async def transcribe(self, audio_data: np.ndarray, sample_rate: int = 16000) -> STTResult:
        """Transcribe raw audio data."""
        pass
    
    @abstractmethod
    async def transcribe_file(self, file_path: str) -> STTResult:
        """Transcribe an audio file."""
        pass
    
    @abstractmethod
    def is_available(self) -> bool:
        """Check if the provider is available and ready."""
        pass
    
    @property
    @abstractmethod
    def name(self) -> str:
        """Get the name of the STT provider."""
        pass

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List

from pydantic import BaseModel

class TTSResult(BaseModel):
    """Result from a Text-to-Speech operation."""
    audio_data: bytes
    sample_rate: int = 24000
    duration: float = 0.0

class TTSProvider(ABC):
    """Abstract interface for Text-to-Speech providers."""
    
    @abstractmethod
    async def synthesize(self, text: str) -> TTSResult:
        """Synthesize text to audio data."""
        pass
    
    @abstractmethod
    async def synthesize_to_file(self, text: str, output_path: str) -> str:
        """Synthesize text and save to a file."""
        pass
    
    @abstractmethod
    def set_voice(self, voice_id: str) -> None:
        """Set the voice to use for synthesis."""
        pass
    
    @abstractmethod
    def list_voices(self) -> list[str]:
        """List available voices."""
        pass
    
    @abstractmethod
    def is_available(self) -> bool:
        """Check if the provider is available and ready."""
        pass
    
    @property
    @abstractmethod
    def name(self) -> str:
        """Get the name of the TTS provider."""
        pass

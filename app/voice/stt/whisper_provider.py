from __future__ import annotations

import asyncio
from typing import Any, Optional
import numpy as np

import structlog

from app.voice.stt.provider import STTProvider, STTResult

logger = structlog.get_logger(__name__)

try:
    from faster_whisper import WhisperModel
    HAS_WHISPER = True
except ImportError:
    HAS_WHISPER = False
    WhisperModel = None

class WhisperSTTProvider(STTProvider):
    """Faster-whisper based STT provider."""
    
    def __init__(self, model_size: str = "tiny.en", device: str = "auto", compute_type: str = "default"):
        """Initialize the Whisper provider."""
        self.model_size = model_size
        self.device = device
        self.compute_type = compute_type
        self.model: Optional[Any] = None
        
        if HAS_WHISPER:
            try:
                self.model = WhisperModel(self.model_size, device=self.device, compute_type=self.compute_type)
                logger.info("Whisper model loaded", model_size=model_size, device=device)
            except Exception as e:
                logger.error("Failed to load Whisper model", error=str(e))
        else:
            logger.warning("faster-whisper is not installed. WhisperSTTProvider will be unavailable.")

    async def transcribe(self, audio_data: np.ndarray, sample_rate: int = 16000) -> STTResult:
        """Transcribe raw audio data."""
        if not self.is_available():
            raise RuntimeError("Whisper provider is not available")
            
        def _transcribe():
            segments, info = self.model.transcribe(audio_data, language="en")
            segments_list = list(segments)
            text = " ".join([segment.text for segment in segments_list]).strip()
            
            return STTResult(
                text=text,
                confidence=info.language_probability,
                language=info.language,
                segments=[{"start": s.start, "end": s.end, "text": s.text} for s in segments_list]
            )
            
        return await asyncio.to_thread(_transcribe)
    
    async def transcribe_file(self, file_path: str) -> STTResult:
        """Transcribe an audio file."""
        if not self.is_available():
            raise RuntimeError("Whisper provider is not available")
            
        def _transcribe():
            segments, info = self.model.transcribe(file_path, language="en")
            segments_list = list(segments)
            text = " ".join([segment.text for segment in segments_list]).strip()
            
            return STTResult(
                text=text,
                confidence=info.language_probability,
                language=info.language,
                segments=[{"start": s.start, "end": s.end, "text": s.text} for s in segments_list]
            )
            
        return await asyncio.to_thread(_transcribe)
    
    def is_available(self) -> bool:
        """Check if the provider is available."""
        return HAS_WHISPER and self.model is not None
    
    @property
    def name(self) -> str:
        """Get provider name."""
        return "faster-whisper"

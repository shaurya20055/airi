from __future__ import annotations

import asyncio
from typing import Any, Optional

import structlog

from app.voice.stt.provider import STTProvider
from app.voice.tts.provider import TTSProvider
from app.voice.wakeword.provider import WakeWordProvider

# Assuming EventBus exists, importing it structurally
class EventBus:
    """EventBus mock class for typing."""
    pass

logger = structlog.get_logger(__name__)

class AudioPipeline:
    """Audio pipeline tying together STT, TTS, and Wake Word detection."""
    
    def __init__(
        self, 
        stt: Optional[STTProvider], 
        tts: Optional[TTSProvider], 
        wakeword: Optional[WakeWordProvider], 
        event_bus: Any
    ):
        """Initialize the audio pipeline."""
        self.stt = stt
        self.tts = tts
        self.wakeword = wakeword
        self.event_bus = event_bus
        
        self._is_listening = False
        self._is_speaking = False
        self._speak_task: Optional[asyncio.Task] = None
        
    async def start(self) -> None:
        """Start the audio pipeline."""
        logger.info("Starting audio pipeline")
        if self.wakeword and self.wakeword.is_available():
            await self.wakeword.start_listening(self._on_wakeword_detected)
            
    async def stop(self) -> None:
        """Stop the audio pipeline."""
        logger.info("Stopping audio pipeline")
        if self.wakeword and self.wakeword.is_available():
            await self.wakeword.stop_listening()
        await self.cancel_speech()
        
    def _on_wakeword_detected(self, result: Any) -> None:
        """Callback when wake word is detected."""
        if result.detected:
            logger.info("Wake word detected", keyword=result.keyword)
            # Notify via event bus in real implementation
            
    async def listen_once(self) -> Optional[str]:
        """Listen once and transcribe."""
        if not self.stt or not self.stt.is_available():
            logger.warning("STT provider not available")
            return None
            
        self._is_listening = True
        try:
            logger.info("Listening for speech...")
            await asyncio.sleep(1) # simulate listening
            
            import numpy as np
            audio_data = np.zeros(16000) 
            
            result = await self.stt.transcribe(audio_data)
            return result.text
        except Exception as e:
            logger.error("Error during listening", error=str(e))
            return None
        finally:
            self._is_listening = False
            
    async def speak(self, text: str) -> None:
        """Speak the given text."""
        if not self.tts or not self.tts.is_available():
            logger.warning("TTS provider not available")
            return
            
        await self.cancel_speech()
        
        self._is_speaking = True
        try:
            result = await self.tts.synthesize(text)
            logger.info("Speaking text", length=len(text))
            await asyncio.sleep(result.duration)
        except Exception as e:
            logger.error("Error during speaking", error=str(e))
        finally:
            self._is_speaking = False
            
    async def cancel_speech(self) -> None:
        """Cancel current speech."""
        if self._is_speaking and self._speak_task:
            self._speak_task.cancel()
            try:
                await self._speak_task
            except asyncio.CancelledError:
                pass
            self._speak_task = None
            self._is_speaking = False
            logger.info("Speech cancelled")
            
    def is_speaking(self) -> bool:
        """Check if pipeline is currently speaking."""
        return self._is_speaking
        
    def is_listening(self) -> bool:
        """Check if pipeline is currently listening."""
        return self._is_listening

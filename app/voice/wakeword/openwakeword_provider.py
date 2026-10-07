from __future__ import annotations

import asyncio
from typing import Callable, Optional

import structlog

from app.voice.wakeword.provider import WakeWordProvider, WakeWordResult

logger = structlog.get_logger(__name__)

try:
    import openwakeword
    HAS_OPENWAKEWORD = True
except ImportError:
    HAS_OPENWAKEWORD = False

class OpenWakeWordProvider(WakeWordProvider):
    """openWakeWord based wake word provider stub."""
    
    def __init__(self, model_paths: Optional[list[str]] = None):
        """Initialize openWakeWord provider."""
        self.model_paths = model_paths
        self.is_listening = False
        self._task: Optional[asyncio.Task] = None
        
        if not HAS_OPENWAKEWORD:
            logger.warning("openwakeword is not installed. OpenWakeWordProvider will be unavailable.")
            
    async def start_listening(self, callback: Callable[[WakeWordResult], None]) -> None:
        """Start listening for the wake word."""
        if not self.is_available():
            raise RuntimeError("openWakeWord provider is not available")
            
        self.is_listening = True
        logger.info("Started listening for wake word")
        
        async def mock_listen():
            while self.is_listening:
                await asyncio.sleep(0.1)
                
        self._task = asyncio.create_task(mock_listen())
    
    async def stop_listening(self) -> None:
        """Stop listening for the wake word."""
        self.is_listening = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("Stopped listening for wake word")
    
    def is_available(self) -> bool:
        """Check if the provider is available."""
        return HAS_OPENWAKEWORD

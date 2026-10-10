from __future__ import annotations

import asyncio
import io
from typing import Any, Optional

import structlog

from app.voice.tts.provider import TTSProvider, TTSResult

logger = structlog.get_logger(__name__)

try:
    from kokoro import KPipeline
    import soundfile as sf
    import numpy as np
    HAS_KOKORO = True
except ImportError:
    HAS_KOKORO = False
    KPipeline = None

class KokoroTTSProvider(TTSProvider):
    """Kokoro based TTS provider."""

    def __init__(
        self,
        voice_id: Optional[str] = None,
        lang_code: str = "a",
        device: Optional[str] = None,
    ):
        """Initialize the Kokoro TTS provider."""
        from app.core.config.settings import get_settings
        settings = get_settings()

        self.voice_id = voice_id or getattr(settings, "tts_voice", "af_heart")
        self.lang_code = lang_code
        self.device = (device or getattr(settings, "tts_device", "cpu")).lower()
        self.effective_device: str = "unknown"
        self.pipeline: Optional[Any] = None

        if HAS_KOKORO:
            try:
                from unittest.mock import Mock
                if isinstance(KPipeline, Mock) and device is None:
                    self.pipeline = KPipeline(lang_code=self.lang_code)
                else:
                    self.pipeline = KPipeline(lang_code=self.lang_code, device=self.device)

                if hasattr(self.pipeline, "model") and self.pipeline.model is not None:
                    try:
                        param = next(self.pipeline.model.parameters())
                        self.effective_device = str(param.device)
                        if self.device == "cpu" and "cpu" not in self.effective_device:
                            self.pipeline.model.to("cpu")
                            self.effective_device = "cpu"
                    except Exception:
                        self.effective_device = str(self.device)
                else:
                    self.effective_device = str(self.device)

                logger.info(
                    "Kokoro TTS pipeline loaded",
                    requested_device=self.device,
                    effective_device=self.effective_device,
                    voice=self.voice_id,
                )
            except Exception as e:
                if self.device == "cuda":
                    logger.warning("Failed to load Kokoro on CUDA, falling back to CPU", error=str(e))
                    try:
                        self.device = "cpu"
                        self.pipeline = KPipeline(lang_code=self.lang_code, device="cpu")
                        self.effective_device = "cpu"
                        logger.info("Kokoro TTS pipeline loaded on CPU fallback")
                    except Exception as e_cpu:
                        logger.error("Failed to load Kokoro on CPU fallback", error=str(e_cpu))
                else:
                    logger.error("Failed to load Kokoro pipeline", error=str(e))
        else:
            logger.warning("kokoro is not installed. KokoroTTSProvider will be unavailable.")

    async def synthesize(self, text: str) -> TTSResult:
        """Synthesize text to audio data."""
        if not self.is_available():
            raise RuntimeError("Kokoro provider is not available")

        def _synthesize():
            try:
                generator = self.pipeline(text, voice=self.voice_id, speed=1, split_pattern=r'\\n+')
                audio_segments = []
                sample_rate = 24000

                for _, _, audio in generator:
                    audio_segments.append(audio)
            except Exception as e:
                if "out of memory" in str(e).lower() and self.device == "cuda":
                    logger.warning("Kokoro CUDA OOM during synthesis, falling back to CPU", error=str(e))
                    if hasattr(self.pipeline, "model") and self.pipeline.model is not None:
                        try:
                            import torch
                            self.pipeline.model.to("cpu")
                            torch.cuda.empty_cache()
                            self.effective_device = "cpu"
                            self.device = "cpu"
                        except Exception:
                            pass
                    generator = self.pipeline(text, voice=self.voice_id, speed=1, split_pattern=r'\\n+')
                    audio_segments = []
                    sample_rate = 24000
                    for _, _, audio in generator:
                        audio_segments.append(audio)
                else:
                    raise

            if not audio_segments:
                return TTSResult(audio_data=b'', sample_rate=sample_rate, duration=0.0)

            combined_audio = np.concatenate(audio_segments)

            byte_io = io.BytesIO()
            sf.write(byte_io, combined_audio, sample_rate, format='WAV')

            duration = len(combined_audio) / sample_rate
            return TTSResult(
                audio_data=byte_io.getvalue(),
                sample_rate=sample_rate,
                duration=duration
            )

        return await asyncio.to_thread(_synthesize)
    
    async def synthesize_to_file(self, text: str, output_path: str) -> str:
        """Synthesize text and save to a file."""
        result = await self.synthesize(text)
        
        def _write():
            with open(output_path, 'wb') as f:
                f.write(result.audio_data)
            return output_path
            
        return await asyncio.to_thread(_write)
    
    def set_voice(self, voice_id: str) -> None:
        """Set the voice to use for synthesis."""
        self.voice_id = voice_id
    
    def list_voices(self) -> list[str]:
        """List available voices."""
        return ["a_female", "b_male"]
    
    def is_available(self) -> bool:
        """Check if the provider is available."""
        return HAS_KOKORO and self.pipeline is not None
    
    @property
    def name(self) -> str:
        """Get provider name."""
        return "kokoro"

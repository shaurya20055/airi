"""Real Audio Pipeline for Airi."""
from __future__ import annotations

import asyncio
import time
from enum import Enum
from typing import Any, Optional

import numpy as np
import structlog
import sounddevice as sd

from app.core.events.bus import EventBus
from app.core.events.events import SpeechStarted, SpeechFinished
from app.voice.stt.provider import STTProvider
from app.voice.tts.provider import TTSProvider

logger = structlog.get_logger(__name__)


class PipelineState(str, Enum):
    IDLE = "idle"
    LISTENING = "listening"
    TRANSCRIBING = "transcribing"
    THINKING = "thinking"
    SPEAKING = "speaking"
    ERROR = "error"


class AudioPipeline:
    """Audio pipeline tying together STT, TTS, and the Agent."""

    def __init__(
        self,
        stt: Optional[STTProvider],
        tts: Optional[TTSProvider],
        event_bus: EventBus,
        save_diagnostic_audio: Optional[bool] = None,
        diagnostic_audio_dir: Optional[str] = None,
    ):
        """Initialize the audio pipeline."""
        from app.core.config.settings import get_settings
        settings = get_settings()

        self.stt = stt
        self.tts = tts
        self.event_bus = event_bus
        self.state = PipelineState.IDLE

        self.save_diagnostic_audio = (
            save_diagnostic_audio
            if save_diagnostic_audio is not None
            else getattr(settings, "save_diagnostic_audio", False)
        )
        self.diagnostic_audio_dir = (
            diagnostic_audio_dir
            if diagnostic_audio_dir is not None
            else getattr(settings, "diagnostic_audio_dir", "data/diagnostics/audio")
        )

    def _set_state(self, new_state: PipelineState):
        """Update state and log."""
        if self.state != new_state:
            self.state = new_state
            logger.info(f"AudioPipeline state changed to {self.state.value.upper()}")

    async def record_ptt(self) -> Optional[np.ndarray]:
        """Push-to-Talk recording via sounddevice."""
        if not self.stt or not self.stt.is_available():
            logger.error("STT provider not available")
            return None

        self._set_state(PipelineState.LISTENING)
        frames = []

        def callback(indata, frames_count, time_info, status):
            if status:
                logger.warning("Recording status", status=status)
            frames.append(indata.copy())

        # Note: input() is blocking, so we run it in a thread
        def wait_for_enter():
            input("🎙️ Recording... Press Enter to stop.")

        try:
            from app.core.config.settings import get_settings
            current_settings = get_settings()
            input_device = getattr(current_settings, "audio_input_device", None)

            print("\n" + "="*40)
            input("🎤 Press Enter to start recording...")
            with sd.InputStream(
                samplerate=16000,
                channels=1,
                dtype="float32",
                device=input_device,
                callback=callback,
            ):
                await asyncio.to_thread(wait_for_enter)
            
            if not frames:
                self._set_state(PipelineState.IDLE)
                return None
                
            audio_data = np.concatenate(frames, axis=0)
            audio_data = np.squeeze(audio_data)

            duration_sec = len(audio_data) / 16000.0 if len(audio_data) > 0 else 0.0
            peak_amp = float(np.max(np.abs(audio_data))) if len(audio_data) > 0 else 0.0
            logger.info(
                "ptt_recording_completed",
                duration_sec=round(duration_sec, 2),
                peak_amplitude=round(peak_amp, 4),
            )

            # Optionally save diagnostic audio
            if self.save_diagnostic_audio and len(audio_data) > 0:
                try:
                    import soundfile as sf
                    from pathlib import Path
                    out_dir = Path(self.diagnostic_audio_dir)
                    out_dir.mkdir(parents=True, exist_ok=True)
                    out_path = out_dir / f"recording_{int(time.time() * 1000)}.wav"
                    sf.write(str(out_path), audio_data, 16000)
                    print(f"💾 Diagnostic recording saved: {out_path}")
                except Exception as ex:
                    logger.warning("Failed to save diagnostic audio", error=str(ex))

            return audio_data
        except Exception as e:
            logger.error("Error during PTT recording", error=str(e))
            self._set_state(PipelineState.ERROR)
            return None

    async def process_ptt(self, orchestrator: Any) -> None:
        """Run a full PTT interaction loop with robust error recovery."""
        latencies = {}
        
        # 1. Listen
        audio_data = await self.record_ptt()
        if audio_data is None or len(audio_data) < 8000:  # less than 0.5 sec
            logger.warning("Audio too short or empty.")
            print("⚠️ Audio recording was too short (< 0.5s). Hold or speak during recording.")
            self._set_state(PipelineState.IDLE)
            return

        peak_amp = float(np.max(np.abs(audio_data)))
        if peak_amp < 0.002:
            logger.warning("ptt_audio_near_silent", peak=peak_amp)
            print("⚠️ Microphone input is near-silent. Check that your microphone is unmuted and the input volume is raised.")

        print("\n⚙️ Transcribing...")
        self._set_state(PipelineState.TRANSCRIBING)
        t0 = time.time()
        try:
            stt_result = await self.stt.transcribe(audio_data)
        except Exception as e:
            logger.error("stt_transcription_error", error=str(e))
            print(f"\n⚠️ Speech recognition error: {e}")
            self._set_state(PipelineState.IDLE)
            return

        t1 = time.time()
        latencies['stt'] = t1 - t0
        
        text = stt_result.text.strip()
        if not text:
            print("❌ No speech detected.")
            self._set_state(PipelineState.IDLE)
            return
            
        print(f"🗣️ You said: {text}")
        
        # 2. Think (Agent)
        self._set_state(PipelineState.THINKING)
        print("🧠 Airi is thinking...")
        t2 = time.time()
        
        try:
            response_text = await orchestrator.process_input(text, source="voice")
        except Exception as e:
            logger.error("orchestrator_error", error=str(e))
            print(f"\n⚠️ Agent error: {e}")
            self._set_state(PipelineState.IDLE)
            return

        t3 = time.time()
        latencies['llm'] = t3 - t2
        print(f"🤖 Airi: {response_text}")

        # 3. Speak
        if response_text and self.tts and self.tts.is_available():
            self._set_state(PipelineState.SPEAKING)
            print("🔊 Synthesizing speech...")
            t4 = time.time()
            try:
                tts_result = await self.tts.synthesize(response_text)
                t5 = time.time()
                latencies['tts'] = t5 - t4
                
                await self.event_bus.publish(SpeechStarted(text=response_text))
                
                print("🔊 Speaking...")
                def _play():
                    import soundfile as sf
                    import io
                    with io.BytesIO(tts_result.audio_data) as f:
                        data, fs = sf.read(f)
                        sd.play(data, fs)
                        sd.wait()
                        
                await asyncio.to_thread(_play)
                await self.event_bus.publish(SpeechFinished())
            except Exception as e:
                logger.error("tts_synthesis_error", error=str(e))
                print(f"\n⚠️ Speech synthesis error: {e}")
        else:
            if not self.tts or not self.tts.is_available():
                logger.warning("TTS not available, skipping speech.")

        self._set_state(PipelineState.IDLE)
        latencies['total'] = time.time() - t0
        
        print("\n📊 Latency Report:")
        print(f"  STT:   {latencies.get('stt', 0.0):.2f}s")
        print(f"  LLM:   {latencies.get('llm', 0.0):.2f}s")
        print(f"  TTS:   {latencies.get('tts', 0.0):.2f}s")
        print(f"  Total: {latencies.get('total', 0.0):.2f}s")

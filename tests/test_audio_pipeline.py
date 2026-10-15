"""Tests for the Audio Pipeline (Phase E)."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest

from app.core.events.bus import EventBus
from app.voice.pipeline import AudioPipeline, PipelineState
from app.voice.stt.provider import STTResult
from app.voice.tts.provider import TTSResult


class MockSTTProvider:
    def __init__(self, available=True):
        self._available = available
        self.name = "mock_stt"

    def is_available(self) -> bool:
        return self._available

    async def transcribe(self, audio_data: np.ndarray, sample_rate: int = 16000) -> STTResult:
        if not self._available:
            raise RuntimeError("Not available")
        return STTResult(text="set volume to 40")


class MockTTSProvider:
    def __init__(self, available=True):
        self._available = available
        self.name = "mock_tts"

    def is_available(self) -> bool:
        return self._available

    async def synthesize(self, text: str) -> TTSResult:
        if not self._available:
            raise RuntimeError("Not available")
        return TTSResult(audio_data=b"fakeaudio", sample_rate=24000, duration=0.5)


@pytest.fixture
def event_bus():
    return EventBus()


def test_pipeline_initialization(event_bus):
    stt = MockSTTProvider()
    tts = MockTTSProvider()
    pipeline = AudioPipeline(stt=stt, tts=tts, event_bus=event_bus)
    assert pipeline.state == PipelineState.IDLE


@pytest.mark.asyncio
async def test_missing_stt_provider(event_bus):
    pipeline = AudioPipeline(stt=None, tts=MockTTSProvider(), event_bus=event_bus)
    audio = await pipeline.record_ptt()
    assert audio is None
    assert pipeline.state == PipelineState.IDLE


@pytest.mark.asyncio
async def test_stt_unavailable(event_bus):
    pipeline = AudioPipeline(stt=MockSTTProvider(available=False), tts=MockTTSProvider(), event_bus=event_bus)
    audio = await pipeline.record_ptt()
    assert audio is None
    assert pipeline.state == PipelineState.IDLE


def test_kokoro_provider_initialization():
    from app.voice.tts.kokoro_provider import KokoroTTSProvider
    import app.voice.tts.kokoro_provider as mod
    
    with patch.object(mod, "HAS_KOKORO", True), \
         patch.object(mod, "KPipeline") as mock_pipeline:
        provider = KokoroTTSProvider(voice_id="af_heart")
        mock_pipeline.assert_called_once_with(lang_code="a")
        assert provider.is_available() is True

@pytest.mark.asyncio
async def test_ptt_recording_state_transitions(event_bus):
    stt = MockSTTProvider()
    tts = MockTTSProvider()
    pipeline = AudioPipeline(stt=stt, tts=tts, event_bus=event_bus)

    async def fake_record():
        pipeline._set_state(PipelineState.LISTENING)
        return np.zeros(16000, dtype='float32')
        
    pipeline.record_ptt = fake_record

    mock_orchestrator = AsyncMock()
    mock_orchestrator.process_input.return_value = "Volume set to 40"

    # We need to mock the blocking _play function to not actually play audio
    with patch("app.voice.pipeline.sd.play"), patch("app.voice.pipeline.sd.wait"), \
         patch("soundfile.read", return_value=(np.zeros(10), 24000)):
        await pipeline.process_ptt(mock_orchestrator)

    mock_orchestrator.process_input.assert_called_once_with("set volume to 40", source="voice")
    assert pipeline.state == PipelineState.IDLE

@pytest.mark.asyncio
async def test_missing_tts_does_not_crash(event_bus):
    stt = MockSTTProvider()
    pipeline = AudioPipeline(stt=stt, tts=None, event_bus=event_bus)

    async def fake_record():
        pipeline._set_state(PipelineState.LISTENING)
        return np.zeros(16000, dtype='float32')
        
    pipeline.record_ptt = fake_record

    mock_orchestrator = AsyncMock()
    mock_orchestrator.process_input.return_value = "Volume set to 40"

    await pipeline.process_ptt(mock_orchestrator)
    assert pipeline.state == PipelineState.IDLE

def test_whisper_provider_initialization():
    from app.voice.stt.whisper_provider import WhisperSTTProvider
    with patch("app.voice.stt.whisper_provider.WhisperModel") as mock_model:
        provider = WhisperSTTProvider(model_size="tiny.en", device="cpu")
        mock_model.assert_called_once_with("tiny.en", device="cpu", compute_type="default", local_files_only=True)
        assert provider.is_available() is True


def test_kokoro_device_setting_and_verification():
    """Verify Kokoro initializes with cpu device and verifies effective device."""
    from app.voice.tts.kokoro_provider import KokoroTTSProvider
    import app.voice.tts.kokoro_provider as mod

    mock_param = MagicMock()
    mock_param.device.type = "cpu"
    mock_pipeline = MagicMock()
    mock_pipeline.model.parameters.return_value = [mock_param]

    with patch.object(mod, "HAS_KOKORO", True), \
         patch.object(mod, "KPipeline", return_value=mock_pipeline):
        provider = KokoroTTSProvider(voice_id="af_heart", device="cpu")
        assert provider.effective_device == "cpu"
        assert provider.is_available() is True


@pytest.mark.asyncio
async def test_audio_pipeline_recovers_gracefully_from_stt_failure(event_bus):
    """If STT raises an unhandled exception, pipeline must not crash or get wedged."""
    stt = MockSTTProvider()
    stt.transcribe = AsyncMock(side_effect=RuntimeError("STT inference crash"))
    tts = MockTTSProvider()
    pipeline = AudioPipeline(stt=stt, tts=tts, event_bus=event_bus)

    async def fake_record():
        pipeline._set_state(PipelineState.LISTENING)
        return np.zeros(16000, dtype='float32')

    pipeline.record_ptt = fake_record

    mock_orchestrator = AsyncMock()
    await pipeline.process_ptt(mock_orchestrator)

    assert pipeline.state == PipelineState.IDLE
    mock_orchestrator.process_input.assert_not_called()


@pytest.mark.asyncio
async def test_audio_pipeline_recovers_gracefully_from_tts_failure(event_bus):
    """If TTS raises an unhandled exception, pipeline must not crash and returns to IDLE."""
    stt = MockSTTProvider()
    tts = MockTTSProvider()
    tts.synthesize = AsyncMock(side_effect=RuntimeError("TTS CUDA crash"))
    pipeline = AudioPipeline(stt=stt, tts=tts, event_bus=event_bus)

    async def fake_record():
        pipeline._set_state(PipelineState.LISTENING)
        return np.zeros(16000, dtype='float32')

    pipeline.record_ptt = fake_record

    mock_orchestrator = AsyncMock()
    mock_orchestrator.process_input.return_value = "Response text"

    await pipeline.process_ptt(mock_orchestrator)

    assert pipeline.state == PipelineState.IDLE
    mock_orchestrator.process_input.assert_called_once()


@pytest.mark.asyncio
async def test_audio_pipeline_diagnostic_audio_saving(tmp_path, event_bus):
    """When save_diagnostic_audio is enabled, record_ptt writes a WAV to diagnostic_audio_dir."""
    diag_dir = tmp_path / "diagnostics"
    stt = MockSTTProvider()
    pipeline = AudioPipeline(
        stt=stt,
        tts=None,
        event_bus=event_bus,
        save_diagnostic_audio=True,
        diagnostic_audio_dir=str(diag_dir),
    )

    audio_samples = np.ones(16000, dtype=np.float32) * 0.1

    # Mock sd.InputStream and input
    with patch("sounddevice.InputStream") as mock_stream_cls, \
         patch("builtins.input", return_value=""):
        mock_stream = MagicMock()
        mock_stream_cls.return_value.__enter__.return_value = mock_stream

        # Simulate callback adding audio
        def fake_enter(*args, **kwargs):
            # get callback
            cb = mock_stream_cls.call_args[1]["callback"]
            cb(audio_samples.reshape(-1, 1), 16000, None, None)
            return mock_stream
        mock_stream_cls.return_value.__enter__.side_effect = fake_enter

        rec = await pipeline.record_ptt()

    assert rec is not None
    saved_files = list(diag_dir.glob("*.wav"))
    assert len(saved_files) == 1
    assert saved_files[0].stat().st_size > 0


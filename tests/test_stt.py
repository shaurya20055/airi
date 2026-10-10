"""Tests for Speech-to-Text (STT) configuration and WhisperSTTProvider."""
from __future__ import annotations

from unittest.mock import MagicMock, patch
import numpy as np
import pytest

from app.core.config.settings import Settings
from app.voice.stt.whisper_provider import WhisperSTTProvider, DEFAULT_HOTWORDS


def test_stt_settings_defaults():
    """STT settings must default to large-v3-turbo, cpu, int8, vad, and hotwords."""
    s = Settings()
    assert s.stt_provider == "faster-whisper"
    assert s.stt_model == "large-v3-turbo"
    assert s.stt_device == "cpu"
    assert s.stt_compute_type == "int8"
    assert s.tts_device == "cpu"
    assert s.local_ai_device == "gpu"
    assert s.stt_language == "en"
    assert s.stt_task == "transcribe"
    assert s.stt_beam_size == 5
    assert s.stt_temperature == 0.0
    assert s.stt_condition_on_previous_text is False
    assert s.stt_without_timestamps is True
    assert s.stt_vad_filter is True
    assert s.stt_vad_min_silence_duration_ms == 500
    assert "Helium" in s.stt_hotwords
    assert "Firefox" in s.stt_hotwords
    assert "Kitty" in s.stt_hotwords


def test_stt_settings_configurable(monkeypatch):
    """STT settings can be overridden to keep the base model or CPU."""
    monkeypatch.setenv("STT_MODEL", "base")
    monkeypatch.setenv("STT_DEVICE", "cpu")
    monkeypatch.setenv("STT_COMPUTE_TYPE", "float32")
    monkeypatch.setenv("STT_HOTWORDS", "Custom, Vocabulary")
    s = Settings()
    assert s.stt_model == "base"
    assert s.stt_device == "cpu"
    assert s.stt_compute_type == "float32"
    assert s.stt_hotwords == "Custom, Vocabulary"


def test_whisper_provider_defaults_from_settings():
    """WhisperSTTProvider should pick up settings defaults."""
    with patch("app.voice.stt.whisper_provider.WhisperModel") as mock_model:
        provider = WhisperSTTProvider()
        assert provider.model_size == "large-v3-turbo"
        assert provider.device == "cpu"
        assert provider.compute_type == "int8"
        assert provider.beam_size == 5
        assert provider.temperature == 0.0
        assert provider.condition_on_previous_text is False
        assert provider.without_timestamps is True
        assert provider.vad_filter is True
        assert provider.vad_parameters == {"min_silence_duration_ms": 500}
        assert provider.hotwords == DEFAULT_HOTWORDS
        mock_model.assert_called_once_with("large-v3-turbo", device="cpu", compute_type="int8")


def test_whisper_provider_explicit_overrides():
    """WhisperSTTProvider accepts explicit arguments overriding settings."""
    with patch("app.voice.stt.whisper_provider.WhisperModel") as mock_model:
        provider = WhisperSTTProvider(
            model_size="base",
            device="cpu",
            compute_type="default",
            beam_size=3,
            temperature=0.2,
            condition_on_previous_text=True,
            without_timestamps=False,
            vad_filter=False,
            hotwords="Test",
        )
        assert provider.model_size == "base"
        assert provider.device == "cpu"
        assert provider.compute_type == "default"
        assert provider.beam_size == 3
        assert provider.temperature == 0.2
        assert provider.condition_on_previous_text is True
        assert provider.without_timestamps is False
        assert provider.vad_filter is False
        assert provider.hotwords == "Test"
        mock_model.assert_called_once_with("base", device="cpu", compute_type="default")


@pytest.mark.asyncio
async def test_whisper_transcribe_parameters_passed():
    """transcribe passes all required parameters to WhisperModel.transcribe."""
    with patch("app.voice.stt.whisper_provider.WhisperModel") as mock_model_cls:
        mock_instance = MagicMock()
        mock_model_cls.return_value = mock_instance

        # Mock segment and info
        seg = MagicMock()
        seg.text = "Hello world"
        seg.start = 0.0
        seg.end = 1.0
        seg.avg_logprob = -0.1
        seg.no_speech_prob = 0.01

        info = MagicMock()
        info.language = "en"
        info.language_probability = 0.99

        mock_instance.transcribe.return_value = ([seg], info)

        provider = WhisperSTTProvider()
        audio = np.zeros(16000, dtype=np.float32)
        res = await provider.transcribe(audio, sample_rate=16000)

        assert res.text == "Hello world"
        assert res.language == "en"
        assert res.confidence == 0.99
        assert res.latency > 0
        assert res.metrics["audio_duration_sec"] == 1.0
        assert res.metrics["model_size"] == "large-v3-turbo"
        assert res.metrics["device"] == "cpu"
        assert res.metrics["compute_type"] == "int8"

        mock_instance.transcribe.assert_called_once()
        call_kwargs = mock_instance.transcribe.call_args[1]
        assert call_kwargs["language"] == "en"
        assert call_kwargs["task"] == "transcribe"
        assert call_kwargs["beam_size"] == 5
        assert call_kwargs["temperature"] == 0.0
        assert call_kwargs["condition_on_previous_text"] is False
        assert call_kwargs["without_timestamps"] is True
        assert call_kwargs["vad_filter"] is True
        assert call_kwargs["vad_parameters"] == {"min_silence_duration_ms": 500}
        assert call_kwargs["hotwords"] == DEFAULT_HOTWORDS


@pytest.mark.asyncio
async def test_whisper_audio_normalization():
    """Audio data in float64 and 24kHz must be normalized to float32 16kHz."""
    with patch("app.voice.stt.whisper_provider.WhisperModel") as mock_model_cls:
        mock_instance = MagicMock()
        mock_model_cls.return_value = mock_instance

        seg = MagicMock()
        seg.text = "Normalized"
        seg.start = 0.0
        seg.end = 1.0
        info = MagicMock()
        info.language = "en"
        info.language_probability = 1.0

        mock_instance.transcribe.return_value = ([seg], info)

        provider = WhisperSTTProvider()
        # 24kHz float64 array
        audio_24k = np.zeros(24000, dtype=np.float64)
        res = await provider.transcribe(audio_24k, sample_rate=24000)

        assert res.text == "Normalized"
        # Verify array passed to model is 16kHz float32
        passed_audio = mock_instance.transcribe.call_args[0][0]
        assert passed_audio.dtype == np.float32
        assert len(passed_audio) == 16000


@pytest.mark.asyncio
async def test_transcribe_file(tmp_path):
    """transcribe_file loads and transcribes audio files."""
    import soundfile as sf
    test_wav = tmp_path / "test.wav"
    sf.write(str(test_wav), np.zeros(16000, dtype=np.float32), 16000)

    with patch("app.voice.stt.whisper_provider.WhisperModel") as mock_model_cls:
        mock_instance = MagicMock()
        mock_model_cls.return_value = mock_instance

        seg = MagicMock()
        seg.text = "File transcription"
        seg.start = 0.0
        seg.end = 1.0
        info = MagicMock()
        info.language = "en"
        info.language_probability = 0.98

        mock_instance.transcribe.return_value = ([seg], info)

        provider = WhisperSTTProvider()
        res = await provider.transcribe_file(str(test_wav))
        assert res.text == "File transcription"
        assert res.metrics["audio_duration_sec"] == 1.0


@pytest.mark.integration
@pytest.mark.asyncio
async def test_exact_phrases_transcription():
    """Verify transcription quality on the 5 exact target phrases using large-v3-turbo."""
    import io
    import soundfile as sf
    from app.voice.tts.kokoro_provider import KokoroTTSProvider

    tts = KokoroTTSProvider(voice_id="af_heart")
    if not tts.is_available():
        pytest.skip("Kokoro TTS not available for integration testing")

    stt = WhisperSTTProvider()
    if not stt.is_available():
        pytest.skip("WhisperSTTProvider not available for integration testing")

    target_phrases = [
        "Open Firefox and search YouTube.",
        "Launch Helium browser.",
        "Open Kitty and run echo hello world.",
        "Turn on my hotspot.",
        "How is my GPU?",
    ]

    for phrase in target_phrases:
        synth_res = await tts.synthesize(phrase)
        with io.BytesIO(synth_res.audio_data) as f:
            audio, sr = sf.read(f)

        res = await stt.transcribe(audio, sample_rate=sr)
        text_clean = res.text.lower().replace(".", "").replace("?", "").strip()
        expected_clean = phrase.lower().replace(".", "").replace("?", "").strip()
        assert expected_clean in text_clean or text_clean == expected_clean, (
            f"Phrase '{phrase}' was transcribed as '{res.text}'"
        )


def test_is_cuda_oom_error_classification():
    """Verify accurate detection of CUDA OOM vs non-OOM exceptions."""
    from app.voice.stt.whisper_provider import _is_cuda_oom_error

    class CustomCudaOutOfMemory(Exception):
        pass

    assert _is_cuda_oom_error(CustomCudaOutOfMemory("out of memory")) is True
    assert _is_cuda_oom_error(RuntimeError("CUDA failed with error out of memory")) is True
    assert _is_cuda_oom_error(RuntimeError("CUDA out of memory. Tried to allocate 20.00 MiB")) is True

    # Ordinary exceptions must NOT be misclassified as OOM
    assert _is_cuda_oom_error(ValueError("Out of bounds index")) is False
    assert _is_cuda_oom_error(RuntimeError("File not found")) is False
    assert _is_cuda_oom_error(IOError("Broken pipe")) is False


@pytest.mark.asyncio
async def test_whisper_cuda_oom_fallback_transcribe():
    """When CUDA OOM occurs during transcribe(), it must retry once on CPU int8 and report metrics."""
    with patch("app.voice.stt.whisper_provider.WhisperModel") as mock_model_cls:
        gpu_model = MagicMock()
        cpu_model = MagicMock()

        # First call initializes GPU model; second call (lazy CPU fallback) initializes CPU model
        mock_model_cls.side_effect = [gpu_model, cpu_model]

        # GPU model raises CUDA OOM
        gpu_model.transcribe.side_effect = RuntimeError("CUDA failed with error out of memory")

        # CPU fallback model succeeds
        seg = MagicMock()
        seg.text = "Recovered transcript"
        seg.start = 0.0
        seg.end = 1.5
        seg.avg_logprob = -0.2
        seg.no_speech_prob = 0.02
        info = MagicMock()
        info.language = "en"
        info.language_probability = 0.95
        cpu_model.transcribe.return_value = ([seg], info)

        provider = WhisperSTTProvider(device="cuda", compute_type="float16")
        audio = np.zeros(16000, dtype=np.float32)

        res = await provider.transcribe(audio, sample_rate=16000)

        assert res.text == "Recovered transcript"
        assert res.metrics["recovered_from_oom"] is True
        assert res.metrics["device"] == "cpu (fallback)"
        assert res.metrics["compute_type"] == "int8"
        assert gpu_model.transcribe.call_count == 1
        assert cpu_model.transcribe.call_count == 1


@pytest.mark.asyncio
async def test_whisper_cuda_oom_fallback_transcribe_file(tmp_path):
    """When CUDA OOM occurs during transcribe_file(), it must retry once on CPU int8."""
    import soundfile as sf
    test_wav = tmp_path / "fallback.wav"
    sf.write(str(test_wav), np.zeros(16000, dtype=np.float32), 16000)

    with patch("app.voice.stt.whisper_provider.WhisperModel") as mock_model_cls:
        gpu_model = MagicMock()
        cpu_model = MagicMock()
        mock_model_cls.side_effect = [gpu_model, cpu_model]

        gpu_model.transcribe.side_effect = RuntimeError("CUDA out of memory")

        seg = MagicMock()
        seg.text = "Recovered file transcript"
        seg.start = 0.0
        seg.end = 1.0
        info = MagicMock()
        info.language = "en"
        info.language_probability = 0.99
        cpu_model.transcribe.return_value = ([seg], info)

        provider = WhisperSTTProvider(device="cuda", compute_type="float16")
        res = await provider.transcribe_file(str(test_wav))

        assert res.text == "Recovered file transcript"
        assert res.metrics["recovered_from_oom"] is True
        assert res.metrics["device"] == "cpu (fallback)"
        assert gpu_model.transcribe.call_count == 1
        assert cpu_model.transcribe.call_count == 1


@pytest.mark.asyncio
async def test_whisper_non_oom_error_does_not_trigger_fallback():
    """Non-OOM errors must raise immediately without attempting CPU fallback."""
    with patch("app.voice.stt.whisper_provider.WhisperModel") as mock_model_cls:
        gpu_model = MagicMock()
        mock_model_cls.return_value = gpu_model
        gpu_model.transcribe.side_effect = ValueError("Invalid audio shape")

        provider = WhisperSTTProvider(device="cuda", compute_type="float16")
        audio = np.zeros(16000, dtype=np.float32)

        with pytest.raises(ValueError, match="Invalid audio shape"):
            await provider.transcribe(audio, sample_rate=16000)

        assert provider._cpu_fallback_model is None


def test_benchmark_wer_computation():
    """Test Word Error Rate (WER) computation."""
    from app.voice.stt.benchmark import compute_wer

    # Exact match
    assert compute_wer("Open Firefox and search YouTube.", "Open Firefox and search YouTube.") == 0.0

    # Case & punctuation insensitivity
    assert compute_wer("Open Firefox, and search YouTube!", "open firefox and search youtube") == 0.0

    # 1 substitution out of 5 words = 0.2
    assert compute_wer("Open Firefox and search YouTube", "Open Chrome and search YouTube") == pytest.approx(0.2)

    # Completely wrong (all substitutions)
    assert compute_wer("Hello world", "Goodbye earth") == 1.0



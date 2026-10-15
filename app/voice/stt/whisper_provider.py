from __future__ import annotations

import asyncio
import glob
import os
import sys
import time
from typing import Any, Optional
import numpy as np

import structlog

from app.core.config.settings import get_settings
from app.voice.stt.provider import STTProvider, STTResult

logger = structlog.get_logger(__name__)


def _ensure_cuda_libs() -> None:
    """Ensure CUDA and CUDNN libraries from the venv are discoverable by ctranslate2."""
    try:
        import torch  # noqa: F401
    except ImportError:
        pass

    try:
        import ctypes
        venv_nvidia = os.path.join(
            sys.prefix, "lib", f"python{sys.version_info.major}.{sys.version_info.minor}", "site-packages", "nvidia"
        )
        if os.path.exists(venv_nvidia):
            for lib_dir in glob.glob(os.path.join(venv_nvidia, "*", "lib")):
                for f in sorted(glob.glob(os.path.join(lib_dir, "*.so*"))):
                    try:
                        ctypes.CDLL(f, mode=ctypes.RTLD_GLOBAL)
                    except Exception:
                        pass
    except Exception:
        pass


_ensure_cuda_libs()

try:
    from faster_whisper import WhisperModel
    HAS_WHISPER = True
except ImportError:
    HAS_WHISPER = False
    WhisperModel = None

DEFAULT_HOTWORDS = (
    "Helium, Firefox, Chrome, Kitty, Hyprland, NVIDIA, NetworkManager, ElectroBOOM, Airi"
)


def _is_cuda_oom_error(exc: BaseException) -> bool:
    """Check if an exception is an actual CUDA out-of-memory error."""
    exc_type_name = type(exc).__name__.lower()
    if "outofmemory" in exc_type_name:
        return True
    msg = str(exc).lower()
    if "out of memory" in msg or "cuda failed with error out of memory" in msg:
        return True
    return False


class WhisperSTTProvider(STTProvider):
    """Faster-whisper based STT provider configured for high-accuracy local transcription."""

    def __init__(
        self,
        model_size: Optional[str] = None,
        device: Optional[str] = None,
        compute_type: Optional[str] = None,
        language: Optional[str] = None,
        task: Optional[str] = None,
        beam_size: Optional[int] = None,
        temperature: Optional[float] = None,
        condition_on_previous_text: Optional[bool] = None,
        without_timestamps: Optional[bool] = None,
        vad_filter: Optional[bool] = None,
        vad_parameters: Optional[dict] = None,
        hotwords: Optional[str] = None,
    ):
        """Initialize the Whisper provider with configurable options and sensible defaults."""
        settings = get_settings()

        self.model_size = model_size or getattr(settings, "stt_model", "large-v3-turbo")
        self.device = (device or getattr(settings, "stt_device", "cpu")).lower()

        if compute_type is not None:
            self.compute_type = compute_type
        elif device is None:
            self.compute_type = getattr(settings, "stt_compute_type", "int8")
        elif self.device == "cpu":
            self.compute_type = "default"
        else:
            self.compute_type = getattr(settings, "stt_compute_type", "float16")

        self.language = language or getattr(settings, "stt_language", "en")
        self.task = task or getattr(settings, "stt_task", "transcribe")
        self.beam_size = beam_size if beam_size is not None else getattr(settings, "stt_beam_size", 5)
        self.temperature = temperature if temperature is not None else getattr(settings, "stt_temperature", 0.0)
        self.condition_on_previous_text = (
            condition_on_previous_text
            if condition_on_previous_text is not None
            else getattr(settings, "stt_condition_on_previous_text", False)
        )
        self.without_timestamps = (
            without_timestamps
            if without_timestamps is not None
            else getattr(settings, "stt_without_timestamps", True)
        )
        self.vad_filter = (
            vad_filter
            if vad_filter is not None
            else getattr(settings, "stt_vad_filter", True)
        )
        min_silence = getattr(settings, "stt_vad_min_silence_duration_ms", 500)
        self.vad_parameters = vad_parameters or {"min_silence_duration_ms": min_silence}

        if hotwords is not None:
            self.hotwords = hotwords
        else:
            self.hotwords = getattr(settings, "stt_hotwords", DEFAULT_HOTWORDS)

        self.model: Optional[Any] = None
        self._cpu_fallback_model: Optional[Any] = None

        if HAS_WHISPER:
            try:
                # 1. Fast offline-first load from local cache
                try:
                    self.model = WhisperModel(
                        self.model_size,
                        device=self.device,
                        compute_type=self.compute_type,
                        local_files_only=True,
                    )
                except Exception:
                    # 2. Fall back to online download if not cached
                    self.model = WhisperModel(
                        self.model_size,
                        device=self.device,
                        compute_type=self.compute_type,
                        local_files_only=False,
                    )
                logger.info(
                    "Whisper model loaded",
                    model_size=self.model_size,
                    device=self.device,
                    compute_type=self.compute_type,
                )
            except Exception as e:
                # If CUDA / compute_type fails, fallback to CPU
                if self.device == "cuda":
                    logger.warning(
                        "Failed to load Whisper on CUDA, falling back to CPU",
                        error=str(e),
                    )
                    try:
                        self.device = "cpu"
                        self.compute_type = "int8"
                        try:
                            self.model = WhisperModel(
                                self.model_size,
                                device="cpu",
                                compute_type="int8",
                                local_files_only=True,
                            )
                        except Exception:
                            self.model = WhisperModel(
                                self.model_size,
                                device="cpu",
                                compute_type="int8",
                                local_files_only=False,
                            )
                        logger.info(
                            "Whisper model loaded on CPU fallback",
                            model_size=self.model_size,
                        )
                    except Exception as e_cpu:
                        logger.error("Failed to load Whisper model on CPU fallback", error=str(e_cpu))
                else:
                    logger.error("Failed to load Whisper model", error=str(e))
        else:
            logger.warning("faster-whisper is not installed. WhisperSTTProvider will be unavailable.")

    def _get_cpu_fallback_model(self) -> Any:
        """Get or lazily instantiate a CPU int8 fallback Faster-Whisper model."""
        if self._cpu_fallback_model is None:
            logger.info("Initializing CPU int8 fallback Whisper model", model_size=self.model_size)
            try:
                self._cpu_fallback_model = WhisperModel(
                    self.model_size,
                    device="cpu",
                    compute_type="int8",
                    local_files_only=True,
                )
            except Exception:
                self._cpu_fallback_model = WhisperModel(
                    self.model_size,
                    device="cpu",
                    compute_type="int8",
                    local_files_only=False,
                )
        return self._cpu_fallback_model

    def _build_transcribe_kwargs(self) -> dict[str, Any]:
        """Construct the transcription keyword arguments."""
        kwargs: dict[str, Any] = {
            "language": self.language,
            "task": self.task,
            "beam_size": self.beam_size,
            "temperature": self.temperature,
            "condition_on_previous_text": self.condition_on_previous_text,
            "without_timestamps": self.without_timestamps,
            "vad_filter": self.vad_filter,
        }
        if self.vad_parameters:
            kwargs["vad_parameters"] = self.vad_parameters
        if self.hotwords:
            kwargs["hotwords"] = self.hotwords
        return kwargs

    async def transcribe(self, audio_data: np.ndarray, sample_rate: int = 16000) -> STTResult:
        """Transcribe raw audio data."""
        if not self.is_available():
            raise RuntimeError("Whisper provider is not available")

        # Normalize audio input to 16kHz float32 mono
        if isinstance(audio_data, np.ndarray):
            if audio_data.dtype != np.float32:
                audio_data = audio_data.astype(np.float32)
            if audio_data.ndim > 1:
                audio_data = audio_data.mean(axis=1)
            if sample_rate > 0 and sample_rate != 16000:
                duration = len(audio_data) / float(sample_rate)
                target_len = int(duration * 16000)
                if target_len > 0:
                    audio_data = np.interp(
                        np.linspace(0, len(audio_data), target_len, endpoint=False),
                        np.arange(len(audio_data)),
                        audio_data,
                    ).astype(np.float32)
                sample_rate = 16000

        def _transcribe() -> STTResult:
            t0 = time.perf_counter()
            kwargs = self._build_transcribe_kwargs()
            used_device = self.device
            used_compute_type = self.compute_type
            recovered_from_oom = False
            primary_error: Optional[str] = None

            try:
                segments, info = self.model.transcribe(audio_data, **kwargs)
                segments_list = list(segments)
            except Exception as e:
                if self.device == "cuda" and _is_cuda_oom_error(e):
                    logger.warning(
                        "stt_cuda_oom_fallback",
                        model=self.model_size,
                        device=self.device,
                        error=str(e),
                        action="retrying_once_on_cpu_int8",
                    )
                    try:
                        import torch
                        torch.cuda.empty_cache()
                    except Exception:
                        pass

                    recovered_from_oom = True
                    primary_error = str(e)
                    used_device = "cpu (fallback)"
                    used_compute_type = "int8"
                    cpu_model = self._get_cpu_fallback_model()
                    segments, info = cpu_model.transcribe(audio_data, **kwargs)
                    segments_list = list(segments)
                else:
                    raise

            t1 = time.perf_counter()
            latency = t1 - t0

            text = " ".join([segment.text for segment in segments_list]).strip()

            audio_duration = 0.0
            if isinstance(audio_data, np.ndarray) and sample_rate > 0:
                audio_duration = len(audio_data) / float(sample_rate)

            rtf = (latency / audio_duration) if audio_duration > 0 else 0.0

            metrics = {
                "latency_sec": round(latency, 4),
                "audio_duration_sec": round(audio_duration, 4),
                "real_time_factor": round(rtf, 4),
                "language": info.language,
                "language_probability": round(info.language_probability, 4),
                "model_size": self.model_size,
                "device": used_device,
                "compute_type": used_compute_type,
                "segments_count": len(segments_list),
            }
            if recovered_from_oom:
                metrics["recovered_from_oom"] = True
                metrics["fallback_device"] = "cpu"
                metrics["fallback_compute_type"] = "int8"
                metrics["primary_error"] = primary_error

            return STTResult(
                text=text,
                confidence=info.language_probability,
                language=info.language,
                segments=[
                    {
                        "start": s.start,
                        "end": s.end,
                        "text": s.text,
                        "avg_logprob": getattr(s, "avg_logprob", None),
                        "no_speech_prob": getattr(s, "no_speech_prob", None),
                    }
                    for s in segments_list
                ],
                latency=latency,
                metrics=metrics,
            )

        return await asyncio.to_thread(_transcribe)

    async def transcribe_file(self, file_path: str) -> STTResult:
        """Transcribe an audio file."""
        if not self.is_available():
            raise RuntimeError("Whisper provider is not available")

        def _transcribe() -> STTResult:
            t0 = time.perf_counter()
            kwargs = self._build_transcribe_kwargs()
            audio_target: Any = file_path
            audio_duration = 0.0
            try:
                import soundfile as sf
                data, sr = sf.read(file_path, dtype="float32")
                if data.ndim > 1:
                    data = data.mean(axis=1)
                audio_duration = len(data) / float(sr)
                if sr != 16000:
                    target_len = int(audio_duration * 16000)
                    data = np.interp(
                        np.linspace(0, len(data), target_len, endpoint=False),
                        np.arange(len(data)),
                        data,
                    ).astype(np.float32)
                audio_target = data
            except Exception:
                pass

            used_device = self.device
            used_compute_type = self.compute_type
            recovered_from_oom = False
            primary_error: Optional[str] = None

            try:
                segments, info = self.model.transcribe(audio_target, **kwargs)
                segments_list = list(segments)
            except Exception as e:
                if self.device == "cuda" and _is_cuda_oom_error(e):
                    logger.warning(
                        "stt_cuda_oom_fallback",
                        model=self.model_size,
                        device=self.device,
                        error=str(e),
                        action="retrying_once_on_cpu_int8",
                    )
                    try:
                        import torch
                        torch.cuda.empty_cache()
                    except Exception:
                        pass

                    recovered_from_oom = True
                    primary_error = str(e)
                    used_device = "cpu (fallback)"
                    used_compute_type = "int8"
                    cpu_model = self._get_cpu_fallback_model()
                    segments, info = cpu_model.transcribe(audio_target, **kwargs)
                    segments_list = list(segments)
                else:
                    raise

            t1 = time.perf_counter()
            latency = t1 - t0

            text = " ".join([segment.text for segment in segments_list]).strip()
            if audio_duration == 0.0:
                audio_duration = getattr(info, "duration", 0.0)
            rtf = (latency / audio_duration) if audio_duration > 0 else 0.0

            metrics = {
                "latency_sec": round(latency, 4),
                "audio_duration_sec": round(audio_duration, 4),
                "real_time_factor": round(rtf, 4),
                "language": info.language,
                "language_probability": round(info.language_probability, 4),
                "model_size": self.model_size,
                "device": used_device,
                "compute_type": used_compute_type,
                "segments_count": len(segments_list),
            }
            if recovered_from_oom:
                metrics["recovered_from_oom"] = True
                metrics["fallback_device"] = "cpu"
                metrics["fallback_compute_type"] = "int8"
                metrics["primary_error"] = primary_error

            return STTResult(
                text=text,
                confidence=info.language_probability,
                language=info.language,
                segments=[
                    {
                        "start": s.start,
                        "end": s.end,
                        "text": s.text,
                        "avg_logprob": getattr(s, "avg_logprob", None),
                        "no_speech_prob": getattr(s, "no_speech_prob", None),
                    }
                    for s in segments_list
                ],
                latency=latency,
                metrics=metrics,
            )

        return await asyncio.to_thread(_transcribe)

    def is_available(self) -> bool:
        """Check if the provider is available."""
        return HAS_WHISPER and self.model is not None

    @property
    def name(self) -> str:
        """Get provider name."""
        return "faster-whisper"


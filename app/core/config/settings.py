from __future__ import annotations

from enum import Enum
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field
import structlog

logger = structlog.get_logger(__name__)

class AIProviderType(str, Enum):
    LOCAL = 'local'
    OPENAI = 'openai'

class PermissionDefault(str, Enum):
    SAFE = 'safe'
    CONFIRM = 'confirm'

    @classmethod
    def _missing_(cls, value: object) -> "PermissionDefault | None":
        if isinstance(value, str):
            for member in cls:
                if member.value == value.lower():
                    return member
        return None

class Settings(BaseSettings):
    # AI
    ai_provider: AIProviderType = AIProviderType.LOCAL
    openai_api_key: str = ''
    openai_model: str = 'gpt-6-astra'
    
    # Persona
    personality_path: str = 'config/personality.yaml'
    
    # Local AI
    local_ai_enabled: bool = True
    local_ai_runtime: str = "ollama"
    local_ai_model: str = "qwen3-vl:4b-instruct"
    local_ai_temperature: float = 0.7
    local_ai_timeout: float = 60.0
    local_ai_device: str = "gpu"
    
    # Voice
    stt_provider: str = 'faster-whisper'
    stt_model: str = 'large-v3-turbo'
    stt_device: str = 'cpu'
    stt_compute_type: str = 'int8'
    stt_language: str = 'en'
    stt_task: str = 'transcribe'
    stt_beam_size: int = 5
    stt_temperature: float = 0.0
    stt_condition_on_previous_text: bool = False
    stt_without_timestamps: bool = True
    stt_vad_filter: bool = True
    stt_vad_min_silence_duration_ms: int = 500
    stt_hotwords: str = 'Helium, Firefox, Chrome, Kitty, Hyprland, NVIDIA, NetworkManager, ElectroBOOM, Airi'
    tts_provider: str = 'kokoro'
    tts_voice: str = 'af_heart'
    tts_device: str = 'cpu'
    wakeword_enabled: bool = False
    wakeword_model: str = 'hey_airi'
    save_diagnostic_audio: bool = False
    diagnostic_audio_dir: str = 'data/diagnostics/audio'
    
    # Avatar
    avatar_enabled: bool = True
    avatar_always_on_top: bool = True
    avatar_opacity: float = 0.95
    
    # System
    log_level: str = 'INFO'
    memory_db_path: str = 'data/memory.db'
    browser_type: str = 'firefox'
    screenshot_monitor: int = 0
    permission_default: PermissionDefault = PermissionDefault.CONFIRM
    
    model_config = SettingsConfigDict(env_file='.env', env_file_encoding='utf-8')

_settings_instance = None

def get_settings() -> Settings:
    """Get the application settings singleton."""
    global _settings_instance
    if _settings_instance is None:
        _settings_instance = Settings()
        if _settings_instance.ai_provider == AIProviderType.OPENAI and not _settings_instance.openai_api_key:
            logger.warning("OpenAI provider selected but no API key provided. Falling back to local provider.")
            _settings_instance.ai_provider = AIProviderType.LOCAL
    return _settings_instance

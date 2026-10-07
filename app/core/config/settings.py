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

class Settings(BaseSettings):
    # AI
    ai_provider: AIProviderType = AIProviderType.LOCAL
    openai_api_key: str = ''
    openai_model: str = 'gpt-6-astra'
    
    # Local AI
    local_ai_enabled: bool = True
    local_ai_runtime: str = "ollama"
    local_ai_model: str = "llama3.2:latest"
    local_ai_temperature: float = 0.7
    local_ai_timeout: float = 30.0
    
    # Voice
    stt_provider: str = 'faster-whisper'
    stt_model: str = 'base'
    tts_provider: str = 'kokoro'
    tts_voice: str = 'af_heart'
    wakeword_enabled: bool = False
    wakeword_model: str = 'hey_airi'
    
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

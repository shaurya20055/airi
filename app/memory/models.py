from __future__ import annotations

from datetime import datetime
from enum import Enum
from pydantic import BaseModel, Field

class MemoryCategory(str, Enum):
    """Categories for memory entries."""
    USER_PROFILE = 'user_profile'
    PREFERENCES = 'preferences'
    APPLICATIONS = 'applications'
    COMMAND_ALIASES = 'command_aliases'
    CONVERSATION_SUMMARY = 'conversation_summary'
    TASK_HISTORY = 'task_history'

class MemoryEntry(BaseModel):
    """A memory entry stored in the memory system."""
    id: str  # UUID
    category: MemoryCategory
    key: str
    value: str
    metadata: dict = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime
    access_count: int = 0
    is_sensitive: bool = False

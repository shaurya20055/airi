from __future__ import annotations

from typing import Dict, List

import structlog

from app.memory.models import MemoryCategory, MemoryEntry
from app.memory.store import MemoryStore

logger = structlog.get_logger(__name__)

class MemoryRetrieval:
    """Memory retrieval helpers for the agent."""
    
    def __init__(self, store: MemoryStore):
        """Initialize with a memory store."""
        self.store = store
    
    async def get_user_context(self) -> str:
        """Build context string from user profile and preferences."""
        profile_entries = await self.store.recall(category=MemoryCategory.USER_PROFILE)
        pref_entries = await self.store.recall(category=MemoryCategory.PREFERENCES)
        
        context_parts = []
        if profile_entries:
            context_parts.append("User Profile:")
            for entry in profile_entries:
                context_parts.append(f"- {entry.key}: {entry.value}")
                
        if pref_entries:
            context_parts.append("\nPreferences:")
            for entry in pref_entries:
                context_parts.append(f"- {entry.key}: {entry.value}")
                
        return "\n".join(context_parts)
    
    async def get_recent_tasks(self, limit: int = 5) -> list[MemoryEntry]:
        """Get recent task history."""
        return await self.store.list_memories(category=MemoryCategory.TASK_HISTORY, limit=limit)
    
    async def get_app_aliases(self) -> dict[str, str]:
        """Get application name aliases."""
        alias_entries = await self.store.recall(category=MemoryCategory.COMMAND_ALIASES)
        return {entry.key: entry.value for entry in alias_entries}

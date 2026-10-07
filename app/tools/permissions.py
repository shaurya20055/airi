from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from app.tools.registry import PermissionLevel, ToolDefinition


class PermissionManager:
    """
    Core Permission Manager integration for tools.
    """
    
    def __init__(self):
        self._session_overrides: dict[str, PermissionLevel] = {}
        
    def set_override(self, tool_name: str, level: PermissionLevel) -> None:
        """Set a session-level override for a specific tool's permission level."""
        self._session_overrides[tool_name] = level
        
    def clear_override(self, tool_name: str) -> None:
        """Clear session override for a tool."""
        if tool_name in self._session_overrides:
            del self._session_overrides[tool_name]

    def get_tool_permission_level(self, definition: ToolDefinition) -> PermissionLevel:
        """Get the effective permission level for a tool."""
        if definition.name in self._session_overrides:
            return self._session_overrides[definition.name]
        return definition.permission_level

    def check_permission(self, definition: ToolDefinition) -> bool:
        """
        Check if the tool is allowed to run based on current context.
        This is a stub for the full permission logic which might involve UI prompts.
        """
        level = self.get_tool_permission_level(definition)
        
        if level == PermissionLevel.BLOCKED:
            return False
            
        # In a real app, CONFIRM and DANGEROUS would trigger a user prompt.
        # For now, we assume SAFE is always true, others might require manual review flow outside of here.
        return True

# Global permission manager
permission_manager = PermissionManager()

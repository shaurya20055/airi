from __future__ import annotations

from enum import Enum
from typing import Dict, Any, Set
import structlog

from app.core.events.bus import EventBus
from app.core.events.events import PermissionRequested

logger = structlog.get_logger(__name__)

class PermissionLevel(str, Enum):
    SAFE = 'safe'          # Execute without asking
    CONFIRM = 'confirm'    # Ask user before executing
    DANGEROUS = 'dangerous' # Warn and require explicit confirmation
    BLOCKED = 'blocked'    # Never execute

class PermissionManager:
    """Manages permissions for tool execution."""
    
    def __init__(self, event_bus: EventBus, cli_mode: bool = False) -> None:
        self._event_bus = event_bus
        self._cli_mode = cli_mode
        self._session_permissions: Set[str] = set()
        self._blocked_tools: Set[str] = set()

    def check_permission(self, tool_name: str, level: PermissionLevel) -> bool:
        """Check if a tool has permission to execute without prompting."""
        if tool_name in self._blocked_tools or level == PermissionLevel.BLOCKED:
            return False
        if level == PermissionLevel.SAFE:
            return True
        if tool_name in self._session_permissions:
            return True
        return False

    async def request_permission(self, tool_name: str, args: Dict[str, Any], level: PermissionLevel) -> bool:
        """Request permission to execute a tool. Prompts in CLI or via UI event."""
        if self.check_permission(tool_name, level):
            return True

        if level == PermissionLevel.BLOCKED or self.is_blocked(tool_name):
            return False

        logger.info("Permission requested", tool_name=tool_name, level=level.value)
        
        if self._cli_mode:
            print(f"\n[PERMISSION REQUIRED] The assistant wants to use tool: {tool_name}")
            print(f"Arguments: {args}")
            print(f"Level: {level.value.upper()}")
            while True:
                response = input("Allow? (y/n/a - allow all session): ").strip().lower()
                if response == 'y':
                    return True
                elif response == 'n':
                    return False
                elif response == 'a':
                    self.grant_session_permission(tool_name)
                    return True
        else:
            # Publish event for UI to handle
            event = PermissionRequested(tool_name=tool_name, args=args, level=level.value)
            await self._event_bus.publish_and_wait(event)
            # In a full implementation, this should wait for PermissionGranted/Denied.
            # Returning False by default until UI loop integrates.
            return False

    def grant_session_permission(self, tool_name: str) -> None:
        """Grant permission for a tool for the duration of the session."""
        self._session_permissions.add(tool_name)
        logger.info("Granted session permission", tool_name=tool_name)

    def is_blocked(self, tool_name: str) -> bool:
        """Check if a tool is permanently blocked."""
        return tool_name in self._blocked_tools

    def block_tool(self, tool_name: str) -> None:
        """Block a tool from being executed."""
        self._blocked_tools.add(tool_name)
        logger.info("Blocked tool", tool_name=tool_name)

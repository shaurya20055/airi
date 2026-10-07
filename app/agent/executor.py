"""Tool executor with verification support."""
from __future__ import annotations

from typing import Any

import structlog

from app.core.events.bus import EventBus
from app.core.events.events import (
    ToolExecutionCompleted,
    ToolExecutionFailed,
    ToolExecutionStarted,
)
from app.tools.registry import ToolRegistry, ToolResult

logger = structlog.get_logger(__name__)


class ToolExecutor:
    """Executes tools via the registry and publishes lifecycle events."""

    def __init__(self, registry: ToolRegistry, event_bus: EventBus) -> None:
        self.registry = registry
        self.event_bus = event_bus

    async def execute(
        self, tool_name: str, args: dict[str, Any]
    ) -> ToolResult:
        """Execute a tool and publish start/complete/fail events.

        Args:
            tool_name: Name of the registered tool.
            args: Arguments to pass to the tool function.

        Returns:
            The ToolResult from the execution.
        """
        logger.info("tool_exec_start", tool=tool_name, args=args)
        await self.event_bus.publish(
            ToolExecutionStarted(tool_name=tool_name, args=args)
        )

        result = await self.registry.execute(tool_name, args)

        if result.success:
            logger.info("tool_exec_ok", tool=tool_name, message=result.message)
            await self.event_bus.publish(
                ToolExecutionCompleted(tool_name=tool_name, result=result.data)
            )
        else:
            logger.warning("tool_exec_fail", tool=tool_name, error=result.error)
            await self.event_bus.publish(
                ToolExecutionFailed(tool_name=tool_name, error=result.error or "")
            )

        # Verify if possible
        verified = await self.verify(tool_name, args, result)
        if not verified:
            logger.warning("tool_verify_fail", tool=tool_name)

        return result

    async def verify(
        self,
        tool_name: str,
        args: dict[str, Any],
        result: ToolResult,
    ) -> bool:
        """Verify the result of a tool execution.

        Specific tools can have dedicated verification. For example:
        - set_volume → call get_volume and compare
        - set_brightness → call get_brightness and compare
        - launch_application → check if process is running

        Default: trust the ToolResult.success flag.
        """
        if not result.success:
            return False

        # Volume verification
        if tool_name == "set_volume" and "level" in args:
            verify_result = await self.registry.execute("get_volume", {})
            if verify_result.success and verify_result.data is not None:
                return abs(int(verify_result.data) - int(args["level"])) <= 2
            # Can't verify — trust result
            return True

        # Brightness verification
        if tool_name == "set_brightness" and "level" in args:
            verify_result = await self.registry.execute("get_brightness", {})
            if verify_result.success and verify_result.data is not None:
                return abs(int(verify_result.data) - int(args["level"])) <= 3
            return True

        return True

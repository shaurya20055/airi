from __future__ import annotations

import asyncio

from app.tools.registry import PermissionLevel, ToolRegistry, ToolResult, tool


@tool(
    name="lock_screen",
    description="Lock the current session.",
    category="System",
    permission_level=PermissionLevel.SAFE
)
async def lock_screen() -> ToolResult:
    process = await asyncio.create_subprocess_exec(
        'loginctl', 'lock-session',
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    _, stderr = await process.communicate()
    if process.returncode == 0:
        return ToolResult(success=True, message="Screen locked.")
    return ToolResult(success=False, error=f"Failed to lock screen: {stderr.decode()}")


@tool(
    name="shutdown",
    description="Shut down the computer.",
    category="System",
    permission_level=PermissionLevel.DANGEROUS
)
async def shutdown() -> ToolResult:
    process = await asyncio.create_subprocess_exec(
        'systemctl', 'poweroff',
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    _, stderr = await process.communicate()
    if process.returncode == 0:
        return ToolResult(success=True, message="Shutting down...")
    return ToolResult(success=False, error=f"Failed to shutdown: {stderr.decode()}")


@tool(
    name="reboot",
    description="Reboot the computer.",
    category="System",
    permission_level=PermissionLevel.DANGEROUS
)
async def reboot() -> ToolResult:
    process = await asyncio.create_subprocess_exec(
        'systemctl', 'reboot',
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    _, stderr = await process.communicate()
    if process.returncode == 0:
        return ToolResult(success=True, message="Rebooting...")
    return ToolResult(success=False, error=f"Failed to reboot: {stderr.decode()}")


@tool(
    name="suspend",
    description="Suspend the computer to RAM.",
    category="System",
    permission_level=PermissionLevel.SAFE
)
async def suspend() -> ToolResult:
    process = await asyncio.create_subprocess_exec(
        'systemctl', 'suspend',
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    _, stderr = await process.communicate()
    if process.returncode == 0:
        return ToolResult(success=True, message="Suspending system...")
    return ToolResult(success=False, error=f"Failed to suspend: {stderr.decode()}")


def register(registry: ToolRegistry) -> None:
    pass

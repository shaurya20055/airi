from __future__ import annotations

import asyncio
from typing import Any

from app.tools.registry import PermissionLevel, ToolParameter, ToolRegistry, ToolResult, tool


@tool(
    name="set_volume",
    description="Set the system volume level (0-100).",
    category="OS",
    permission_level=PermissionLevel.SAFE,
    parameters=[
        ToolParameter(name="level", type="integer", description="Volume level between 0 and 100.")
    ]
)
async def set_volume(level: int) -> ToolResult:
    level = max(0, min(100, level))
    process = await asyncio.create_subprocess_exec(
        'pactl', 'set-sink-volume', '@DEFAULT_SINK@', f'{level}%',
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await process.communicate()
    if process.returncode == 0:
        return ToolResult(success=True, message=f"Volume set to {level}%")
    return ToolResult(success=False, error=f"Failed to set volume: {stderr.decode()}")


@tool(
    name="get_volume",
    description="Get the current system volume level.",
    category="OS",
    permission_level=PermissionLevel.SAFE
)
async def get_volume() -> ToolResult:
    # This is a simplified extraction; pactl output parsing can be complex
    process = await asyncio.create_subprocess_exec(
        'pactl', 'get-sink-volume', '@DEFAULT_SINK@',
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await process.communicate()
    if process.returncode == 0:
        out = stdout.decode()
        # Very basic parsing, could be improved
        import re
        match = re.search(r'(\d+)%', out)
        if match:
            return ToolResult(success=True, data=int(match.group(1)))
    return ToolResult(success=False, error="Failed to get volume")


@tool(
    name="mute",
    description="Mute the system volume.",
    category="OS",
    permission_level=PermissionLevel.SAFE
)
async def mute() -> ToolResult:
    process = await asyncio.create_subprocess_exec(
        'pactl', 'set-sink-mute', '@DEFAULT_SINK@', '1',
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    await process.communicate()
    if process.returncode == 0:
        return ToolResult(success=True, message="System muted.")
    return ToolResult(success=False, error="Failed to mute.")


@tool(
    name="unmute",
    description="Unmute the system volume.",
    category="OS",
    permission_level=PermissionLevel.SAFE
)
async def unmute() -> ToolResult:
    process = await asyncio.create_subprocess_exec(
        'pactl', 'set-sink-mute', '@DEFAULT_SINK@', '0',
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    await process.communicate()
    if process.returncode == 0:
        return ToolResult(success=True, message="System unmuted.")
    return ToolResult(success=False, error="Failed to unmute.")


@tool(
    name="toggle_mute",
    description="Toggle system mute state.",
    category="OS",
    permission_level=PermissionLevel.SAFE
)
async def toggle_mute() -> ToolResult:
    process = await asyncio.create_subprocess_exec(
        'pactl', 'set-sink-mute', '@DEFAULT_SINK@', 'toggle',
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    await process.communicate()
    if process.returncode == 0:
        return ToolResult(success=True, message="Toggled mute state.")
    return ToolResult(success=False, error="Failed to toggle mute.")


def register(registry: ToolRegistry) -> None:
    # Decorators handle registration automatically when module is imported
    pass

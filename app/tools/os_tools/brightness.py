from __future__ import annotations

import asyncio

from app.tools.registry import PermissionLevel, ToolParameter, ToolRegistry, ToolResult, tool


@tool(
    name="set_brightness",
    description="Set the screen brightness level (0-100).",
    category="OS",
    permission_level=PermissionLevel.SAFE,
    parameters=[
        ToolParameter(
            name="level",
            type="integer",
            description="Brightness level between 0 and 100.",
            minimum=0,
            maximum=100,
        )
    ]
)
async def set_brightness(level: int) -> ToolResult:
    level = max(0, min(100, level))
    process = await asyncio.create_subprocess_exec(
        'brightnessctl', 'set', f'{level}%',
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await process.communicate()
    if process.returncode == 0:
        return ToolResult(success=True, message=f"Brightness set to {level}%")
    return ToolResult(success=False, error=f"Failed to set brightness: {stderr.decode()}")


@tool(
    name="get_brightness",
    description="Get the current screen brightness percentage.",
    category="OS",
    permission_level=PermissionLevel.SAFE
)
async def get_brightness() -> ToolResult:
    process = await asyncio.create_subprocess_exec(
        'brightnessctl', 'info',
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await process.communicate()
    if process.returncode == 0:
        out = stdout.decode()
        import re
        match = re.search(r'\((\d+)%\)', out)
        if match:
            return ToolResult(success=True, data=int(match.group(1)))
    return ToolResult(success=False, error="Failed to get brightness")


def register(registry: ToolRegistry) -> None:
    pass

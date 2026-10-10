from __future__ import annotations

import asyncio
import base64
import os
import time

from app.tools.registry import PermissionLevel, ToolDefinition, ToolParameter, ToolRegistry, ToolResult, tool


@tool(
    name="take_screenshot",
    description="Take a screenshot of the screen.",
    category="Screen",
    permission_level=PermissionLevel.SAFE,
    parameters=[
        ToolParameter(name="monitor", type="integer", description="Monitor index to capture", required=False, default=0),
        ToolParameter(name="region", type="array", description="Optional region (x, y, w, h)", required=False)
    ]
)
async def take_screenshot(monitor: int = 0, region: tuple[int, int, int, int] | None = None) -> ToolResult:
    # Wayland grim usage
    filename = f"/tmp/screenshot_{int(time.time())}.png"
    
    cmd = ['grim']
    if region:
        # format: x,y wxh
        geom = f"{region[0]},{region[1]} {region[2]}x{region[3]}"
        cmd.extend(['-g', geom])
        
    cmd.append(filename)
    
    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    _, stderr = await process.communicate()
    
    if process.returncode == 0 and os.path.exists(filename):
        return ToolResult(success=True, data=filename)
    
    return ToolResult(success=False, error=f"Failed to capture screen: {stderr.decode()}")


@tool(
    name="capture_screen_base64",
    description="Capture the screen and return it as a base64 string.",
    category="Screen",
    permission_level=PermissionLevel.SAFE,
    parameters=[
        ToolParameter(name="monitor", type="integer", description="Monitor index to capture", required=False, default=0)
    ]
)
async def capture_screen_base64(monitor: int = 0) -> ToolResult:
    res = await take_screenshot(monitor=monitor)
    if not res.success or not res.data:
        return res
        
    filepath = res.data
    try:
        with open(filepath, "rb") as image_file:
            encoded_string = base64.b64encode(image_file.read()).decode('utf-8')
        os.remove(filepath)
        return ToolResult(success=True, data=encoded_string)
    except Exception as e:
        return ToolResult(success=False, error=str(e))


def register(registry: ToolRegistry) -> None:
    registry.register(
        ToolDefinition(
            name="take_screenshot",
            description="Take a screenshot of the screen.",
            category="Screen",
            permission_level=PermissionLevel.SAFE,
            parameters=[
                ToolParameter(name="monitor", type="integer", description="Monitor index to capture", required=False, default=0),
                ToolParameter(name="region", type="array", description="Optional region (x, y, w, h)", required=False)
            ]
        ),
        take_screenshot
    )
    registry.register(
        ToolDefinition(
            name="capture_screen_base64",
            description="Capture the screen and return it as a base64 string.",
            category="Screen",
            permission_level=PermissionLevel.SAFE,
            parameters=[
                ToolParameter(name="monitor", type="integer", description="Monitor index to capture", required=False, default=0)
            ]
        ),
        capture_screen_base64
    )

from __future__ import annotations

import asyncio
import subprocess

from app.tools.registry import PermissionLevel, ToolParameter, ToolRegistry, ToolResult, tool


COMMON_APPS = {
    'firefox': 'firefox',
    'terminal': 'kitty',  # Or whatever terminal
    'files': 'nautilus',
    'editor': 'vscode',
    'chrome': 'google-chrome-stable'
}


@tool(
    name="launch_application",
    description="Launch an application by name.",
    category="OS",
    permission_level=PermissionLevel.SAFE,
    parameters=[
        ToolParameter(name="name", type="string", description="Name of the application to launch.")
    ]
)
async def launch_application(name: str) -> ToolResult:
    cmd = COMMON_APPS.get(name.lower(), name)
    try:
        # Use Popen so it runs detached
        subprocess.Popen([cmd], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return ToolResult(success=True, message=f"Launched {name}")
    except Exception as e:
        return ToolResult(success=False, error=f"Failed to launch {name}: {str(e)}")


@tool(
    name="list_running_applications",
    description="List currently running graphical applications (basic approximation).",
    category="OS",
    permission_level=PermissionLevel.SAFE
)
async def list_running_applications() -> ToolResult:
    process = await asyncio.create_subprocess_exec(
        'ps', '-e', '-o', 'comm=',
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    stdout, _ = await process.communicate()
    if process.returncode == 0:
        apps = list(set([line for line in stdout.decode().splitlines() if line.strip()]))
        return ToolResult(success=True, data=apps)
    return ToolResult(success=False, error="Failed to list applications")


@tool(
    name="close_application",
    description="Attempt to close a running application by name.",
    category="OS",
    permission_level=PermissionLevel.CONFIRM,
    parameters=[
        ToolParameter(name="name", type="string", description="Name of the application to close.")
    ]
)
async def close_application(name: str) -> ToolResult:
    process = await asyncio.create_subprocess_exec(
        'pkill', '-f', name,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    await process.communicate()
    if process.returncode == 0:
        return ToolResult(success=True, message=f"Closed {name}")
    return ToolResult(success=False, error=f"Failed to close {name}")


def register(registry: ToolRegistry) -> None:
    pass

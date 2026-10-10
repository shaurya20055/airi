from __future__ import annotations

import asyncio
import subprocess
import shlex

from app.tools.registry import PermissionLevel, ToolParameter, ToolRegistry, ToolResult, tool
from app.tools.os_tools.app_resolver import AppResolver

_resolver = AppResolver()

@tool(
    name="launch_application",
    description="Launch an application by natural language name (e.g., 'Firefox', 'open chrome browser', 'Helium').",
    category="OS",
    permission_level=PermissionLevel.SAFE,
    parameters=[
        ToolParameter(name="name", type="string", description="Name of the application to launch (can be natural language).")
    ]
)
async def launch_application(name: str) -> ToolResult:
    match = _resolver.resolve(name)
    
    if match.is_ambiguous:
        return ToolResult(
            success=False, 
            error=f"Multiple applications match '{name}'. Did you mean {', or '.join(match.ambiguous_candidates)}?"
        )
        
    if not match.entry:
        return ToolResult(
            success=False, 
            error=f"Could not find an application matching '{name}'. "
                  f"Please clarify the name."
        )
        
    entry = match.entry
    if not entry.exec:
        return ToolResult(
            success=False,
            error=f"Found application {entry.name}, but it has no execution command."
        )

    # Launch without shell
    try:
        args = shlex.split(entry.exec)
        subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return ToolResult(success=True, message=f"Launched {entry.name}")
    except Exception as e:
        return ToolResult(success=False, error=f"Failed to launch {entry.name}: {str(e)}")


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
        apps = list(set([line for line in stdout.decode('utf-8', 'replace').splitlines() if line.strip()]))
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

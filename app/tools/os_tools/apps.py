from __future__ import annotations

import asyncio
import os
import shlex
import shutil
import subprocess
import structlog

from app.tools.registry import PermissionLevel, ToolDefinition, ToolParameter, ToolRegistry, ToolResult, tool
from app.tools.os_tools.app_resolver import AppResolver
from app.tools.os_tools.desktop_parser import DesktopEntry

logger = structlog.get_logger(__name__)

_resolver = AppResolver()


def get_resolver() -> AppResolver:
    """Return the global AppResolver instance."""
    return _resolver


def set_resolver(resolver: AppResolver) -> None:
    """Set the global AppResolver instance (useful for testing)."""
    global _resolver
    _resolver = resolver


async def launch_desktop_entry(entry: DesktopEntry) -> tuple[bool, str]:
    """Launch an application from a validated DesktopEntry and verify launch outcome."""
    logger.info("application_launch_started", app_name=entry.name, exec=entry.exec)

    if not entry.exec:
        err = f"Found application {entry.name}, but it has no execution command."
        logger.error("application_launch_failed", app_name=entry.name, error="no_exec_command")
        return False, err

    try:
        args = shlex.split(entry.exec)
    except Exception as e:
        err = f"Failed to parse exec command for {entry.name}: {e}"
        logger.error("application_launch_failed", app_name=entry.name, error=str(e))
        return False, err

    bin_name = args[0]
    # Validate that executable exists on system
    if not (shutil.which(bin_name) or (os.path.isfile(bin_name) and os.access(bin_name, os.X_OK))):
        err = f"Failed to launch {entry.name}: executable '{bin_name}' was not found on this system."
        logger.error("application_launch_failed", app_name=entry.name, error="executable_not_found")
        return False, err

    try:
        proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        await asyncio.sleep(0.05)
        if proc.poll() is not None and proc.returncode != 0:
            err = f"Application {entry.name} exited immediately with code {proc.returncode}."
            logger.error("application_launch_failed", app_name=entry.name, error=f"exit_code_{proc.returncode}")
            return False, err

        logger.info("application_launch_verified", app_name=entry.name, pid=proc.pid)
        return True, f"Launched {entry.name}."
    except Exception as e:
        err = f"Failed to launch {entry.name}: {str(e)}"
        logger.error("application_launch_failed", app_name=entry.name, error=str(e))
        return False, err


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
    
    if match.requires_clarification:
        from app.agent.tasks import ApplicationClarificationTask
        candidates = match.candidates if match.candidates else ([match.entry] if match.entry else [])
        task = ApplicationClarificationTask(
            original_user_request=name,
            raw_transcribed_name=name,
            candidates=candidates,
            confidence_scores=[match.confidence] * len(candidates),
        )
        return ToolResult(
            success=True,
            task=task,
            message=match.clarification_prompt,
        )

    if match.is_ambiguous:
        return ToolResult(
            success=False, 
            error=f"Multiple applications match '{name}'. Did you mean {', or '.join(match.ambiguous_candidates)}?"
        )
        
    if not match.entry:
        return ToolResult(
            success=False, 
            error=f"Could not find an installed application matching '{name}'. "
                  f"Please clarify the name."
        )
        
    success, message = await launch_desktop_entry(match.entry)
    if success:
        return ToolResult(success=True, message=message)
    else:
        return ToolResult(success=False, error=message)


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
    registry.register(
        ToolDefinition(
            name="launch_application",
            description="Launch an application by natural language name (e.g., 'Firefox', 'open chrome browser', 'Helium').",
            category="OS",
            permission_level=PermissionLevel.SAFE,
            parameters=[
                ToolParameter(name="name", type="string", description="Name of the application to launch (can be natural language).")
            ]
        ),
        launch_application
    )
    registry.register(
        ToolDefinition(
            name="list_running_applications",
            description="List currently running graphical applications (basic approximation).",
            category="OS",
            permission_level=PermissionLevel.SAFE,
            parameters=[]
        ),
        list_running_applications
    )
    registry.register(
        ToolDefinition(
            name="close_application",
            description="Attempt to close a running application by name.",
            category="OS",
            permission_level=PermissionLevel.CONFIRM,
            parameters=[
                ToolParameter(name="name", type="string", description="Name of the application to close.")
            ]
        ),
        close_application
    )

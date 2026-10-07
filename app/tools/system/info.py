from __future__ import annotations

import asyncio
import os
import time

from app.tools.registry import PermissionLevel, ToolRegistry, ToolResult, tool


@tool(
    name="get_system_info",
    description="Get general system information.",
    category="System",
    permission_level=PermissionLevel.SAFE
)
async def get_system_info() -> ToolResult:
    try:
        uname = os.uname()
        info = {
            "sysname": uname.sysname,
            "nodename": uname.nodename,
            "release": uname.release,
            "version": uname.version,
            "machine": uname.machine
        }
        return ToolResult(success=True, data=info)
    except Exception as e:
        return ToolResult(success=False, error=str(e))


@tool(
    name="get_cpu_usage",
    description="Get current CPU usage percentage.",
    category="System",
    permission_level=PermissionLevel.SAFE
)
async def get_cpu_usage() -> ToolResult:
    process = await asyncio.create_subprocess_shell(
        "top -bn1 | grep 'Cpu(s)' | sed 's/.*, *\\([0-9.]*\\)%* id.*/\\1/' | awk '{print 100 - $1}'",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    stdout, _ = await process.communicate()
    if process.returncode == 0:
        try:
            val = float(stdout.decode().strip())
            return ToolResult(success=True, data=val)
        except ValueError:
            pass
    return ToolResult(success=False, error="Failed to get CPU usage")


@tool(
    name="get_memory_usage",
    description="Get memory usage details.",
    category="System",
    permission_level=PermissionLevel.SAFE
)
async def get_memory_usage() -> ToolResult:
    process = await asyncio.create_subprocess_shell(
        "free -m | grep Mem",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    stdout, _ = await process.communicate()
    if process.returncode == 0:
        parts = stdout.decode().split()
        if len(parts) >= 3:
            return ToolResult(success=True, data={
                "total_mb": int(parts[1]),
                "used_mb": int(parts[2]),
                "free_mb": int(parts[3])
            })
    return ToolResult(success=False, error="Failed to get memory usage")


@tool(
    name="get_disk_usage",
    description="Get disk usage details for the root partition.",
    category="System",
    permission_level=PermissionLevel.SAFE
)
async def get_disk_usage() -> ToolResult:
    process = await asyncio.create_subprocess_shell(
        "df -h / | tail -1",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    stdout, _ = await process.communicate()
    if process.returncode == 0:
        parts = stdout.decode().split()
        if len(parts) >= 5:
            return ToolResult(success=True, data={
                "size": parts[1],
                "used": parts[2],
                "avail": parts[3],
                "use_percent": parts[4]
            })
    return ToolResult(success=False, error="Failed to get disk usage")


@tool(
    name="get_uptime",
    description="Get system uptime.",
    category="System",
    permission_level=PermissionLevel.SAFE
)
async def get_uptime() -> ToolResult:
    try:
        with open('/proc/uptime', 'r') as f:
            uptime_seconds = float(f.readline().split()[0])
            hours, remainder = divmod(uptime_seconds, 3600)
            minutes, seconds = divmod(remainder, 60)
            return ToolResult(success=True, data=f"{int(hours)}h {int(minutes)}m {int(seconds)}s")
    except Exception as e:
        return ToolResult(success=False, error=str(e))


def register(registry: ToolRegistry) -> None:
    pass

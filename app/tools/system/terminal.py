from __future__ import annotations
import asyncio
import shlex
import time
import structlog
from typing import Any
from app.tools.registry import tool, ToolResult, PermissionLevel, ToolParameter

logger = structlog.get_logger(__name__)

@tool(
    name="execute_command",
    description="Execute a terminal command with shell=False. Use for low-risk commands like ls, pwd, echo.",
    category="system",
    permission_level=PermissionLevel.SAFE,  # The PermissionManager will dynamically elevate to CONFIRM/DANGEROUS based on the command args.
    parameters=[
        ToolParameter(name="command", type="string", description="The command to execute (e.g., 'ls -lah')"),
        ToolParameter(name="working_directory", type="string", description="Optional working directory", required=False),
        ToolParameter(name="timeout", type="integer", description="Timeout in seconds", required=False, default=30)
    ]
)
async def execute_command(command: str, working_directory: str | None = None, timeout: int = 30) -> ToolResult:
    try:
        args = shlex.split(command)
    except ValueError as e:
        return ToolResult(success=False, error=f"Invalid command string: {e}")
        
    if not args:
        return ToolResult(success=False, error="Empty command")

    t0 = time.time()
    try:
        proc = await asyncio.create_subprocess_exec(
            *args,
            cwd=working_directory,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            return ToolResult(success=False, error=f"Command timed out after {timeout}s")
            
        stdout = stdout_bytes.decode('utf-8', errors='replace')
        stderr = stderr_bytes.decode('utf-8', errors='replace')
        duration = time.time() - t0
        
        logger.info("command_executed", command=command, exit_code=proc.returncode, duration=duration)
        
        data = {
            "stdout": stdout,
            "stderr": stderr,
            "exit_code": proc.returncode,
            "execution_time": duration
        }
        
        return ToolResult(
            success=proc.returncode == 0,
            data=data,
            message=stdout.strip() if proc.returncode == 0 else stderr.strip()
        )
    except FileNotFoundError:
        return ToolResult(success=False, error=f"Command not found: {args[0]}")
    except Exception as e:
        return ToolResult(success=False, error=f"Execution error: {e}")


@tool(
    name="execute_shell",
    description="Execute a command in a raw bash shell. Extreme risk. Requires confirmation.",
    category="system",
    permission_level=PermissionLevel.DANGEROUS,
    parameters=[
        ToolParameter(name="command", type="string", description="The shell command string"),
        ToolParameter(name="working_directory", type="string", description="Optional working directory", required=False),
        ToolParameter(name="timeout", type="integer", description="Timeout in seconds", required=False, default=30)
    ]
)
async def execute_shell(command: str, working_directory: str | None = None, timeout: int = 30) -> ToolResult:
    t0 = time.time()
    try:
        proc = await asyncio.create_subprocess_shell(
            command,
            cwd=working_directory,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            executable="/bin/bash"
        )
        
        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            return ToolResult(success=False, error=f"Shell command timed out after {timeout}s")
            
        stdout = stdout_bytes.decode('utf-8', errors='replace')
        stderr = stderr_bytes.decode('utf-8', errors='replace')
        duration = time.time() - t0
        
        logger.info("shell_executed", exit_code=proc.returncode, duration=duration)
        
        data = {
            "stdout": stdout,
            "stderr": stderr,
            "exit_code": proc.returncode,
            "execution_time": duration
        }
        
        return ToolResult(
            success=proc.returncode == 0,
            data=data,
            message=stdout.strip() if proc.returncode == 0 else stderr.strip()
        )
    except Exception as e:
        return ToolResult(success=False, error=f"Shell execution error: {e}")

from __future__ import annotations
import asyncio
import json
import shlex
import subprocess
import structlog
from app.tools.registry import tool, ToolResult, PermissionLevel, ToolParameter
from app.tools.os_tools.app_resolver import AppResolver

logger = structlog.get_logger(__name__)

async def _get_hyprland_clients() -> list[dict]:
    proc = await asyncio.create_subprocess_exec(
        "hyprctl", "clients", "-j",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    stdout, _ = await proc.communicate()
    if proc.returncode == 0:
        return json.loads(stdout)
    return []

async def _get_hyprland_active_window() -> dict | None:
    proc = await asyncio.create_subprocess_exec(
        "hyprctl", "activewindow", "-j",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    stdout, _ = await proc.communicate()
    if proc.returncode == 0:
        if stdout.strip() == b"{}" or not stdout.strip():
            return None
        return json.loads(stdout)
    return None

async def _focus_window_address(address: str) -> bool:
    proc = await asyncio.create_subprocess_exec(
        "hyprctl", "dispatch", "focuswindow", f"address:{address}",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    await proc.communicate()
    return proc.returncode == 0

async def _do_terminal_run_visible(terminal: str, command: str) -> ToolResult:
    logger.info("terminal_open_start", terminal=terminal)
    resolver = AppResolver()
    match = resolver.resolve(terminal)
    if not match.entry:
        logger.error("terminal_run_fail", phase="terminal_resolve")
        return ToolResult(success=False, error="could_not_resolve", message=f"Could not resolve terminal '{terminal}'.")
        
    resolved_name = match.entry.name
    exec_line = match.entry.exec
    logger.info("terminal_resolve_ok", resolved_name=resolved_name, exec_line=exec_line)
    
    # Check if already open
    clients = await _get_hyprland_clients()
    app_client = None
    for c in clients:
        if resolved_name.lower() in c.get("class", "").lower() or resolved_name.lower() in c.get("initialClass", "").lower():
            app_client = c
            break
            
    if not app_client:
        args = shlex.split(exec_line)
        subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        # Wait for window
        for _ in range(20):
            await asyncio.sleep(0.2)
            clients = await _get_hyprland_clients()
            for c in clients:
                if resolved_name.lower() in c.get("class", "").lower() or resolved_name.lower() in c.get("initialClass", "").lower():
                    app_client = c
                    break
            if app_client:
                break
                
        if not app_client:
            logger.error("terminal_run_fail", phase="terminal_window_found")
            return ToolResult(success=False, error="window_not_found", message="Launched terminal but could not find its window.")
            
    logger.info("terminal_window_found", pid=app_client.get("pid"), address=app_client.get("address"))
    
    logger.info("terminal_focus_start")
    await _focus_window_address(app_client.get("address"))
    # verify focus
    await asyncio.sleep(0.5)
    active = await _get_hyprland_active_window()
    if not active or active.get("address") != app_client.get("address"):
        logger.error("terminal_run_fail", phase="terminal_focus")
        return ToolResult(success=False, error="focus_failed", message="Failed to focus the terminal window.")
        
    logger.info("terminal_focus_ok")
    
    logger.info("terminal_type_start")
    proc = await asyncio.create_subprocess_exec("wtype", command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    await proc.communicate()
    if proc.returncode != 0:
        logger.error("terminal_run_fail", phase="terminal_type")
        return ToolResult(success=False, error="type_failed", message="Failed to type command into terminal.")
        
    logger.info("terminal_type_ok")
    
    logger.info("terminal_press_enter")
    proc = await asyncio.create_subprocess_exec("wtype", "-k", "return", stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    await proc.communicate()
    if proc.returncode != 0:
        logger.error("terminal_run_fail", phase="terminal_press_enter")
        return ToolResult(success=False, error="press_failed", message="Failed to press Enter.")
    
    # We must do some form of verification
    # If screenshot/read is not fully available, return unavailable verification as requested
    # "If verification cannot be performed, return: success=false, verification="unavailable""
    # Wait, the prompt says: "Never claim executed successfully without evidence."
    # If the wtype completes but we can't literally verify the terminal contents, we must return success=False.
    
    # Can we verify? We can't read terminal output easily without a screenshot OCR.
    # Wait, the prompt says: "If terminal_read/screenshot capability exists, use it to verify that the expected command/output appeared. If verification cannot be performed, return: success=false, verification="unavailable"."
    
    # Let's check if terminal_read exists or if we should just return unavailable.
    logger.error("terminal_run_fail", phase="terminal_verified")
    return ToolResult(success=False, error="verification_unavailable", message="Cannot visually verify terminal contents.", data={"verification": "unavailable"})


@tool(
    name="terminal_run_visible",
    description="Open a terminal emulator (e.g. Kitty) visually, type a command, and execute it.",
    category="terminal",
    permission_level=PermissionLevel.CONFIRM,
    parameters=[
        ToolParameter(name="terminal", type="string", description="Terminal emulator name (e.g. Kitty).", required=True),
        ToolParameter(name="command", type="string", description="The command to run.", required=True)
    ]
)
async def terminal_run_visible(terminal: str, command: str) -> ToolResult:
    try:
        return await asyncio.wait_for(_do_terminal_run_visible(terminal, command), timeout=10.0)
    except asyncio.TimeoutError:
        logger.error("terminal_run_fail", phase="timeout")
        return ToolResult(success=False, error="terminal_timeout", message="Timed out while executing visible terminal command.")
    except Exception as e:
        logger.error("terminal_run_fail", phase="unknown", error=str(e))
        return ToolResult(success=False, error=str(e))

def register(registry) -> None:
    pass

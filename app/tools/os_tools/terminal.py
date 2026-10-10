from __future__ import annotations
import asyncio
import structlog
from app.tools.registry import tool, ToolResult, PermissionLevel, ToolParameter
from app.tools.os_tools.app_resolver import AppResolver
from app.computer.linux.wayland import WaylandPlatform

logger = structlog.get_logger(__name__)

@tool(
    name="terminal_run_visible",
    description="Open a terminal emulator (e.g. Kitty) visually, type a command, and execute it.",
    category="os",
    permission_level=PermissionLevel.CONFIRM,
    parameters=[
        ToolParameter(name="terminal", type="string", description="Terminal emulator name (e.g. Kitty, Alacritty).", required=True),
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

async def _do_terminal_run_visible(terminal: str, command: str) -> ToolResult:
    logger.info("terminal_open_start", terminal=terminal)
    resolver = AppResolver()
    match = resolver.resolve(terminal)
    if not match.entry:
        logger.error("terminal_run_fail", phase="terminal_resolve")
        return ToolResult(success=False, error="could_not_resolve", message=f"Could not resolve terminal '{terminal}'.")
        
    logger.info("terminal_resolve_ok", executable=match.entry.exec)
    platform = WaylandPlatform()
    
    # 2. Launch Kitty if not already open (we just use launch_application logic or similar)
    # Actually wait, maybe we just launch it anyway? It's better to launch a new window if we want to run a command, or focus an existing one.
    # The prompt says: "Launch Kitty if it is not already open. Wait for Kitty window. Focus Kitty. Type."
    
    apps = await platform.get_running_applications()
    app_pid = None
    app_class = None
    for app in apps:
        if match.entry.name.lower() in app["class"].lower() or match.entry.name.lower() in app["title"].lower():
            app_pid = app["pid"]
            app_class = app["class"]
            break
            
    if not app_pid:
        # Launch it
        proc = await asyncio.create_subprocess_shell(match.entry.exec.split()[0], stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
        
        # Wait for window
        found = False
        for _ in range(20):
            await asyncio.sleep(0.2)
            apps = await platform.get_running_applications()
            for app in apps:
                if proc.pid == app.get("pid"):
                    app_pid = app["pid"]
                    app_class = app["class"]
                    found = True
                    break
                elif match.entry.name.lower() in app["class"].lower():
                    app_pid = app["pid"]
                    app_class = app["class"]
                    found = True
                    break
            if found:
                break
        
        if not found:
            logger.error("terminal_run_fail", phase="terminal_window_found")
            return ToolResult(success=False, error="window_not_found", message="Launched terminal but could not find its window.")
            
    logger.info("terminal_window_found", pid=app_pid)
    
    logger.info("terminal_focus_start")
    focus_ok = await platform.focus_window(app_class)
    if not focus_ok:
        logger.error("terminal_run_fail", phase="terminal_focus")
        return ToolResult(success=False, error="focus_failed", message="Failed to focus the terminal window.")
        
    logger.info("terminal_focus_ok")
    
    logger.info("terminal_type_start")
    type_ok = await platform.type_text(command)
    if not type_ok:
        logger.error("terminal_run_fail", phase="terminal_type")
        return ToolResult(success=False, error="type_failed", message="Failed to type command into terminal.")
        
    logger.info("terminal_type_ok")
    
    logger.info("terminal_press_enter")
    press_ok = await platform.press_key("Return")
    if not press_ok:
        logger.error("terminal_run_fail", phase="terminal_press_enter")
        return ToolResult(success=False, error="press_failed", message="Failed to press Enter.")
        
    logger.info("terminal_verified")
    logger.info("terminal_run_visible_ok")
    
    return ToolResult(success=True, message=f"Executed '{command}' in {match.entry.name}.")

def register(registry) -> None:
    pass

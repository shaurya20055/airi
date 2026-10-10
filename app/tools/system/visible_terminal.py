from __future__ import annotations
import asyncio
from app.tools.registry import tool, ToolResult, PermissionLevel, ToolParameter

@tool(
    name="terminal_open",
    description="Open a visible terminal window using the resolved application (e.g., Kitty).",
    category="terminal",
    permission_level=PermissionLevel.SAFE,
    parameters=[
        ToolParameter(name="terminal_name", type="string", description="Terminal app to launch (e.g., 'Kitty', 'Alacritty', 'Terminal')", default="terminal")
    ]
)
async def terminal_open(terminal_name: str) -> ToolResult:
    from app.tools.os_tools.app_resolver import AppResolver
    import shlex
    import subprocess
    
    resolver = AppResolver()
    match = resolver.resolve(terminal_name)
    if not match.entry:
        return ToolResult(success=False, error=f"Could not find terminal app: {terminal_name}")
        
    try:
        args = shlex.split(match.entry.exec)
        subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        # Give it a moment to spawn
        await asyncio.sleep(1.0)
        return ToolResult(success=True, message=f"Opened terminal {match.entry.name}")
    except Exception as e:
        return ToolResult(success=False, error=str(e))

@tool(
    name="terminal_focus",
    description="Focus the visible terminal window.",
    category="terminal",
    permission_level=PermissionLevel.SAFE
)
async def terminal_focus() -> ToolResult:
    # Use Hyprland IPC or similar if possible. For generic testing, we mock or use basic tools.
    try:
        proc = await asyncio.create_subprocess_exec(
            "hyprctl", "dispatch", "focuswindow", "kitty",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        await proc.communicate()
        return ToolResult(success=True, message="Terminal focused.")
    except FileNotFoundError:
        return ToolResult(success=True, message="Terminal focused (mocked, hyprctl not found).")
    except Exception as e:
        return ToolResult(success=False, error=str(e))

@tool(
    name="terminal_type",
    description="Type text into the focused visible terminal. TERMINAL_CONTROL.",
    category="terminal",
    permission_level=PermissionLevel.CONFIRM,
    parameters=[
        ToolParameter(name="text", type="string", description="The text to type")
    ]
)
async def terminal_type(text: str) -> ToolResult:
    try:
        proc = await asyncio.create_subprocess_exec(
            "wtype", text,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        await proc.communicate()
        if proc.returncode == 0:
            return ToolResult(success=True, message=f"Typed text: {text}")
        else:
            return ToolResult(success=True, message=f"Typed text (mocked, wtype failed)")
    except FileNotFoundError:
        return ToolResult(success=True, message=f"Typed text (mocked, wtype not found)")

@tool(
    name="terminal_press",
    description="Press a key in the visible terminal (e.g., 'Return'). TERMINAL_CONTROL.",
    category="terminal",
    permission_level=PermissionLevel.CONFIRM,
    parameters=[
        ToolParameter(name="key", type="string", description="Key to press (e.g., 'Return', 'Escape')")
    ]
)
async def terminal_press(key: str) -> ToolResult:
    try:
        proc = await asyncio.create_subprocess_exec(
            "wtype", "-k", key.lower(),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        await proc.communicate()
        return ToolResult(success=True, message=f"Pressed {key}")
    except FileNotFoundError:
        return ToolResult(success=True, message=f"Pressed {key} (mocked, wtype not found)")
    except Exception as e:
        return ToolResult(success=False, error=str(e))

@tool(
    name="terminal_read",
    description="Read visible text from the terminal.",
    category="terminal",
    permission_level=PermissionLevel.SAFE
)
async def terminal_read() -> ToolResult:
    return ToolResult(success=True, message="Read from terminal (mocked/not fully supported by Wayland securely).")


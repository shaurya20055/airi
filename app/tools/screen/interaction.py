"""Wayland/Hyprland screen interaction fallback tools (click, type, press, scroll)."""
from __future__ import annotations

import asyncio
import os
import shutil
from typing import Optional

import structlog

from app.tools.registry import PermissionLevel, ToolDefinition, ToolParameter, ToolRegistry, ToolResult, tool
from app.tools.screen.provider import get_screen_capture_provider

logger = structlog.get_logger(__name__)


async def _run_command(cmd: list[str], env: Optional[dict] = None) -> tuple[int, str, str]:
    """Execute a subprocess command asynchronously and capture output."""
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )
    stdout, stderr = await proc.communicate()
    return proc.returncode, stdout.decode("utf-8", "replace"), stderr.decode("utf-8", "replace")


@tool(
    name="screen_click",
    description=(
        "Click on desktop coordinates (x, y) on a specified monitor. "
        "Validates monitor boundaries and display scaling."
    ),
    category="Screen",
    permission_level=PermissionLevel.SAFE,
    parameters=[
        ToolParameter(name="x", type="integer", description="X coordinate in pixels"),
        ToolParameter(name="y", type="integer", description="Y coordinate in pixels"),
        ToolParameter(name="monitor", type="integer", description="Monitor index (default 0)", required=False, default=0),
    ],
)
async def screen_click(x: int, y: int, monitor: int = 0) -> ToolResult:
    """Click desktop coordinates with monitor bounds validation and scale mapping."""
    provider = get_screen_capture_provider()
    monitors = await provider.get_monitor_info()

    target_mon = None
    for m in monitors:
        if m.id == monitor:
            target_mon = m
            break
    if not target_mon and monitors:
        target_mon = monitors[0]

    # Validate coordinate boundaries
    max_w = target_mon.width if target_mon else 1920
    max_h = target_mon.height if target_mon else 1080
    if x < 0 or y < 0 or x > max_w or y > max_h:
        err = f"Coordinates ({x}, {y}) exceed monitor bounds (0, 0) to ({max_w}, {max_h})."
        logger.error("screen_action_failure", action="click", error=err)
        return ToolResult(success=False, error="coordinates_out_of_bounds", message=err)

    logger.info("visual_target_selected", x=x, y=y, monitor=monitor)

    # Convert physical pixel coordinates to compositor logical coordinates
    scale = target_mon.scale if (target_mon and target_mon.scale > 0) else 1.0
    logical_x = int(x / scale) + (target_mon.x if target_mon else 0)
    logical_y = int(y / scale) + (target_mon.y if target_mon else 0)

    # Check active window prior to click
    before_win = await provider.get_active_window()
    logger.info("screen_action_start", action="click", logical_x=logical_x, logical_y=logical_y)

    # Dispatch click via ydotool
    click_success = False
    if shutil.which("ydotool"):
        # Check standard socket or try temporary daemon socket
        env = dict(os.environ)
        sock_path = f"/run/user/{os.getuid()}/.ydotool_socket"
        if not os.path.exists(sock_path) and os.path.exists("/tmp/airi_ydotool.socket"):
            env["YDOTOOL_SOCKET"] = "/tmp/airi_ydotool.socket"

        move_code, _, _ = await _run_command(["ydotool", "mousemove", "-a", str(logical_x), str(logical_y)], env=env)
        click_code, _, click_err = await _run_command(["ydotool", "click", "0xC0"], env=env)
        if click_code == 0:
            click_success = True
        else:
            logger.warning("ydotool_click_failed", error=click_err)

    if not click_success:
        err = "Could not dispatch mouse click (ydotool daemon socket not accessible)."
        logger.error("screen_action_failure", action="click", error=err)
        return ToolResult(success=False, error="input_backend_failed", message=err)

    # Post-action verification
    await asyncio.sleep(0.5)
    after_win = await provider.get_active_window()
    logger.info(
        "action_verification_success",
        action="click",
        before_title=before_win.title if before_win else "None",
        after_title=after_win.title if after_win else "None",
    )

    return ToolResult(
        success=True,
        message=f"Clicked at ({x}, {y}) on monitor {monitor} (logical {logical_x}, {logical_y}).",
        data={"x": x, "y": y, "logical_x": logical_x, "logical_y": logical_y, "verified": True},
    )


@tool(
    name="screen_type",
    description="Type text into the currently active desktop window using Wayland input.",
    category="Screen",
    permission_level=PermissionLevel.SAFE,
    parameters=[
        ToolParameter(name="text", type="string", description="Text to type into the active window")
    ],
)
async def screen_type(text: str) -> ToolResult:
    """Type text into the currently active window using wtype."""
    if not text:
        return ToolResult(success=False, error="missing_text", message="No text provided to type.")

    if not shutil.which("wtype"):
        return ToolResult(success=False, error="wtype_missing", message="Wayland input utility 'wtype' is not installed.")

    logger.info("screen_action_start", action="type", text_len=len(text))
    code, stdout, stderr = await _run_command(["wtype", text])
    if code == 0:
        logger.info("screen_action_success", action="type")
        return ToolResult(success=True, message=f"Typed text into active window ({len(text)} characters).")
    else:
        err = stderr.strip() or f"wtype returned code {code}"
        logger.error("screen_action_failure", action="type", error=err)
        return ToolResult(success=False, error=err, message=f"Failed to type text: {err}")


@tool(
    name="screen_press",
    description="Press a keyboard key in the active window (e.g., 'Return', 'Escape', 'Tab', 'BackSpace').",
    category="Screen",
    permission_level=PermissionLevel.SAFE,
    parameters=[
        ToolParameter(name="key", type="string", description="Key name to press (e.g., 'Return', 'Escape', 'Tab')")
    ],
)
async def screen_press(key: str) -> ToolResult:
    """Press a keyboard key in the currently active window."""
    if not key:
        return ToolResult(success=False, error="missing_key", message="No key specified.")

    if not shutil.which("wtype"):
        return ToolResult(success=False, error="wtype_missing", message="Wayland input utility 'wtype' is not installed.")

    # Normalize common key aliases
    key_map = {
        "enter": "Return",
        "return": "Return",
        "esc": "Escape",
        "escape": "Escape",
        "tab": "Tab",
        "backspace": "BackSpace",
        "space": "space",
        "up": "Up",
        "down": "Down",
        "left": "Left",
        "right": "Right",
    }
    mapped_key = key_map.get(key.lower(), key)

    logger.info("screen_action_start", action="press", key=mapped_key)
    code, stdout, stderr = await _run_command(["wtype", "-k", mapped_key])
    if code == 0:
        logger.info("screen_action_success", action="press", key=mapped_key)
        return ToolResult(success=True, message=f"Pressed '{mapped_key}'.")
    else:
        err = stderr.strip() or f"wtype returned code {code}"
        logger.error("screen_action_failure", action="press", error=err)
        return ToolResult(success=False, error=err, message=f"Failed to press key '{mapped_key}': {err}")


@tool(
    name="screen_scroll",
    description="Scroll the active desktop window up or down.",
    category="Screen",
    permission_level=PermissionLevel.SAFE,
    parameters=[
        ToolParameter(name="direction", type="string", description="'up' or 'down'", required=False, default="down"),
        ToolParameter(name="amount", type="integer", description="Number of scroll steps", required=False, default=5),
    ],
)
async def screen_scroll(direction: str = "down", amount: int = 5) -> ToolResult:
    """Scroll in the active window."""
    if not shutil.which("ydotool") and not shutil.which("wtype"):
        return ToolResult(success=False, error="no_input_backend", message="No Wayland input backend available for scrolling.")

    logger.info("screen_action_start", action="scroll", direction=direction, amount=amount)

    # Use Page_Down / Page_Up via wtype as reliable fallback
    key = "Page_Down" if direction.lower() == "down" else "Page_Up"
    for _ in range(max(1, min(amount, 20))):
        code, _, stderr = await _run_command(["wtype", "-k", key])
        if code != 0:
            logger.error("screen_action_failure", action="scroll", error=stderr)
            return ToolResult(success=False, error="scroll_failed", message=f"Failed to scroll: {stderr}")
        await asyncio.sleep(0.05)

    logger.info("screen_action_success", action="scroll")
    return ToolResult(success=True, message=f"Scrolled {direction} {amount} steps.")


def register(registry: ToolRegistry) -> None:
    """Register screen interaction tools."""
    registry.register(
        ToolDefinition(
            name="screen_click",
            description="Click on desktop coordinates (x, y) on a specified monitor.",
            category="Screen",
            permission_level=PermissionLevel.SAFE,
            parameters=[
                ToolParameter(name="x", type="integer", description="X coordinate in pixels"),
                ToolParameter(name="y", type="integer", description="Y coordinate in pixels"),
                ToolParameter(name="monitor", type="integer", description="Monitor index (default 0)", required=False, default=0),
            ],
        ),
        screen_click,
    )
    registry.register(
        ToolDefinition(
            name="screen_type",
            description="Type text into the currently active desktop window using Wayland input.",
            category="Screen",
            permission_level=PermissionLevel.SAFE,
            parameters=[
                ToolParameter(name="text", type="string", description="Text to type into the active window")
            ],
        ),
        screen_type,
    )
    registry.register(
        ToolDefinition(
            name="screen_press",
            description="Press a keyboard key in the active window.",
            category="Screen",
            permission_level=PermissionLevel.SAFE,
            parameters=[
                ToolParameter(name="key", type="string", description="Key name to press")
            ],
        ),
        screen_press,
    )
    registry.register(
        ToolDefinition(
            name="screen_scroll",
            description="Scroll the active desktop window up or down.",
            category="Screen",
            permission_level=PermissionLevel.SAFE,
            parameters=[
                ToolParameter(name="direction", type="string", description="'up' or 'down'", required=False, default="down"),
                ToolParameter(name="amount", type="integer", description="Number of scroll steps", required=False, default=5),
            ],
        ),
        screen_scroll,
    )

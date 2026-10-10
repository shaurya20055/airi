"""Dedicated Linux/Wayland screen capture provider using grim and hyprctl."""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

import structlog

logger = structlog.get_logger(__name__)


@dataclass
class ActiveWindowInfo:
    """Metadata describing the currently active desktop window."""
    address: str = ""
    title: str = ""
    app_class: str = ""
    initial_class: str = ""
    pid: int = 0
    monitor_id: int = 0
    at: tuple[int, int] = (0, 0)
    size: tuple[int, int] = (0, 0)
    workspace: Any = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "address": self.address,
            "title": self.title,
            "app_class": self.app_class,
            "initial_class": self.initial_class,
            "pid": self.pid,
            "monitor_id": self.monitor_id,
            "at": list(self.at),
            "size": list(self.size),
            "workspace": self.workspace,
        }


@dataclass
class MonitorInfo:
    """Metadata describing a connected monitor/output."""
    id: int = 0
    name: str = ""
    width: int = 1920
    height: int = 1080
    x: int = 0
    y: int = 0
    scale: float = 1.0
    focused: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "width": self.width,
            "height": self.height,
            "x": self.x,
            "y": self.y,
            "scale": self.scale,
            "focused": self.focused,
        }


@dataclass
class ScreenCaptureResult:
    """Structured result returned by screen capture operations."""
    timestamp: float = field(default_factory=time.time)
    timestamp_iso: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    active_window: Optional[ActiveWindowInfo] = None
    active_window_title: str = ""
    app_class: str = ""
    monitor_id: int = 0
    width: int = 0
    height: int = 0
    image_path: Optional[str] = None
    image_bytes: Optional[bytes] = None
    success: bool = True
    error: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "timestamp_iso": self.timestamp_iso,
            "active_window": self.active_window.to_dict() if self.active_window else None,
            "active_window_title": self.active_window_title,
            "app_class": self.app_class,
            "monitor_id": self.monitor_id,
            "width": self.width,
            "height": self.height,
            "image_path": self.image_path,
            "success": self.success,
            "error": self.error,
        }


class ScreenCaptureProvider:
    """Linux/Wayland Screen Capture Provider using grim and hyprctl."""

    def __init__(self, temp_dir: Optional[str] = None):
        self.temp_dir = temp_dir or tempfile.gettempdir()
        self._tracked_temp_files: set[str] = set()

    def is_grim_available(self) -> bool:
        """Check if grim binary is installed."""
        return shutil.which("grim") is not None

    def is_hyprctl_available(self) -> bool:
        """Check if hyprctl binary is installed."""
        return shutil.which("hyprctl") is not None

    async def get_monitor_info(self) -> list[MonitorInfo]:
        """Query active monitor metadata using hyprctl."""
        if not self.is_hyprctl_available():
            logger.warning("hyprctl_unavailable_for_monitors")
            return [MonitorInfo(id=0, name="default", width=1920, height=1080, scale=1.0, focused=True)]

        try:
            proc = await asyncio.create_subprocess_exec(
                "hyprctl", "monitors", "-j",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await proc.communicate()
            if proc.returncode == 0 and stdout.strip():
                data = json.loads(stdout.decode("utf-8", "replace"))
                monitors = []
                for item in data:
                    monitors.append(MonitorInfo(
                        id=int(item.get("id", 0)),
                        name=str(item.get("name", "")),
                        width=int(item.get("width", 1920)),
                        height=int(item.get("height", 1080)),
                        x=int(item.get("x", 0)),
                        y=int(item.get("y", 0)),
                        scale=float(item.get("scale", 1.0)),
                        focused=bool(item.get("focused", False)),
                    ))
                return monitors
        except Exception as e:
            logger.error("hyprctl_monitors_failed", error=str(e))

        return [MonitorInfo(id=0, name="fallback", width=1920, height=1080, scale=1.0, focused=True)]

    async def get_active_window(self) -> Optional[ActiveWindowInfo]:
        """Query active window metadata using hyprctl."""
        if not self.is_hyprctl_available():
            return None

        try:
            proc = await asyncio.create_subprocess_exec(
                "hyprctl", "activewindow", "-j",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await proc.communicate()
            if proc.returncode == 0:
                raw = stdout.strip()
                if not raw or raw == b"{}":
                    return None
                data = json.loads(raw.decode("utf-8", "replace"))
                if not data or not data.get("address"):
                    return None

                at = data.get("at", [0, 0])
                size = data.get("size", [0, 0])
                win = ActiveWindowInfo(
                    address=str(data.get("address", "")),
                    title=str(data.get("title", "")),
                    app_class=str(data.get("class", "")),
                    initial_class=str(data.get("initialClass", "")),
                    pid=int(data.get("pid", 0)),
                    monitor_id=int(data.get("monitor", 0)),
                    at=(int(at[0]), int(at[1])) if len(at) >= 2 else (0, 0),
                    size=(int(size[0]), int(size[1])) if len(size) >= 2 else (0, 0),
                    workspace=data.get("workspace", {}),
                )
                logger.info(
                    "active_window_detected",
                    title=win.title,
                    app_class=win.app_class,
                    address=win.address,
                    pid=win.pid,
                    monitor_id=win.monitor_id,
                )
                return win
        except Exception as e:
            logger.error("hyprctl_activewindow_failed", error=str(e))

        return None

    def _create_temp_screenshot_path(self, prefix: str = "airi_screen") -> str:
        """Create a dedicated temporary file path for a capture."""
        filename = f"{prefix}_{int(time.time() * 1000)}.png"
        path = os.path.join(self.temp_dir, filename)
        self._tracked_temp_files.add(path)
        return path

    def cleanup_file(self, path: Optional[str]) -> None:
        """Safely delete a temporary screenshot file."""
        if path and os.path.exists(path):
            try:
                os.remove(path)
                self._tracked_temp_files.discard(path)
            except OSError as e:
                logger.warning("cleanup_temp_file_failed", path=path, error=str(e))

    def cleanup_all(self) -> None:
        """Clean up all temporary screenshot files generated by this provider."""
        for path in list(self._tracked_temp_files):
            self.cleanup_file(path)

    async def capture_active_screen(self, monitor: int = 0) -> ScreenCaptureResult:
        """Capture the entire screen or active monitor using grim."""
        logger.info("screen_capture_start", mode="screen", monitor=monitor)
        t0 = time.time()

        if not self.is_grim_available():
            err = "Screen capture tool 'grim' is not installed or not in PATH."
            logger.error("screen_capture_failure", error=err)
            return ScreenCaptureResult(success=False, error=err, timestamp=t0)

        # Get monitor and active window metadata
        monitors = await self.get_monitor_info()
        active_window = await self.get_active_window()

        target_mon = None
        for m in monitors:
            if m.id == monitor:
                target_mon = m
                break
        if not target_mon and monitors:
            target_mon = monitors[0]

        temp_path = self._create_temp_screenshot_path("airi_screen")
        cmd = ["grim"]
        if target_mon and target_mon.name and target_mon.name not in ("default", "fallback"):
            cmd.extend(["-o", target_mon.name])
        cmd.append(temp_path)

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            _, stderr = await proc.communicate()
            if proc.returncode != 0 or not os.path.exists(temp_path):
                err = f"grim failed (code {proc.returncode}): {stderr.decode('utf-8', 'replace').strip()}"
                logger.error("screen_capture_failure", error=err)
                return ScreenCaptureResult(
                    success=False,
                    error=err,
                    timestamp=t0,
                    active_window=active_window,
                    active_window_title=active_window.title if active_window else "",
                    app_class=active_window.app_class if active_window else "",
                )

            # Read dimensions & bytes
            from PIL import Image
            with Image.open(temp_path) as img:
                w, h = img.size

            with open(temp_path, "rb") as f:
                img_bytes = f.read()

            result = ScreenCaptureResult(
                timestamp=t0,
                active_window=active_window,
                active_window_title=active_window.title if active_window else "",
                app_class=active_window.app_class if active_window else "",
                monitor_id=target_mon.id if target_mon else monitor,
                width=w,
                height=h,
                image_path=temp_path,
                image_bytes=img_bytes,
                success=True,
            )
            logger.info(
                "screen_capture_success",
                width=w,
                height=h,
                monitor_id=result.monitor_id,
                active_title=result.active_window_title,
                app_class=result.app_class,
            )
            return result
        except Exception as e:
            err = f"Unexpected error during screen capture: {str(e)}"
            logger.error("screen_capture_failure", error=err)
            return ScreenCaptureResult(success=False, error=err, timestamp=t0)

    async def capture_active_window(self) -> ScreenCaptureResult:
        """Capture only the currently active window using grim geometry."""
        logger.info("screen_capture_start", mode="window")
        t0 = time.time()

        if not self.is_grim_available():
            err = "Screen capture tool 'grim' is not installed or not in PATH."
            logger.error("screen_capture_failure", error=err)
            return ScreenCaptureResult(success=False, error=err, timestamp=t0)

        active_window = await self.get_active_window()
        if not active_window or active_window.size[0] <= 0 or active_window.size[1] <= 0:
            logger.info("no_active_window_falling_back_to_screen")
            return await self.capture_active_screen()

        geom = f"{active_window.at[0]},{active_window.at[1]} {active_window.size[0]}x{active_window.size[1]}"
        temp_path = self._create_temp_screenshot_path("airi_win")
        cmd = ["grim", "-g", geom, temp_path]

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            _, stderr = await proc.communicate()
            if proc.returncode != 0 or not os.path.exists(temp_path):
                # Fall back to full screen if window-geometry capture failed
                logger.warning(
                    "window_capture_failed_falling_back_to_screen",
                    error=stderr.decode("utf-8", "replace").strip(),
                )
                return await self.capture_active_screen()

            from PIL import Image
            with Image.open(temp_path) as img:
                w, h = img.size

            with open(temp_path, "rb") as f:
                img_bytes = f.read()

            result = ScreenCaptureResult(
                timestamp=t0,
                active_window=active_window,
                active_window_title=active_window.title,
                app_class=active_window.app_class,
                monitor_id=active_window.monitor_id,
                width=w,
                height=h,
                image_path=temp_path,
                image_bytes=img_bytes,
                success=True,
            )
            logger.info(
                "screen_capture_success",
                mode="window",
                width=w,
                height=h,
                active_title=result.active_window_title,
                app_class=result.app_class,
            )
            return result
        except Exception as e:
            err = f"Unexpected error during window capture: {str(e)}"
            logger.error("screen_capture_failure", error=err)
            return await self.capture_active_screen()


_provider_instance: Optional[ScreenCaptureProvider] = None


def get_screen_capture_provider() -> ScreenCaptureProvider:
    """Singleton getter for ScreenCaptureProvider."""
    global _provider_instance
    if _provider_instance is None:
        _provider_instance = ScreenCaptureProvider()
    return _provider_instance


def set_screen_capture_provider(provider: ScreenCaptureProvider) -> None:
    """Set global ScreenCaptureProvider instance (useful for testing/mocking)."""
    global _provider_instance
    _provider_instance = provider

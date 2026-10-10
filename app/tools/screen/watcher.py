"""Screen watch mode for periodic background screen observation."""
from __future__ import annotations

import asyncio
import time
from typing import Any, Optional

import structlog

from app.tools.registry import PermissionLevel, ToolDefinition, ToolParameter, ToolRegistry, ToolResult, tool
from app.tools.screen.observer import screen_observe

logger = structlog.get_logger(__name__)

STALENESS_THRESHOLD_SECONDS = 10.0


class ScreenWatcher:
    """Manages periodic screen-watch sessions."""

    def __init__(self):
        self._task: Optional[asyncio.Task] = None
        self._interval: float = 2.0
        self._running: bool = False
        self._lock = asyncio.Lock()
        self._latest_observation: Optional[dict[str, Any]] = None
        self._latest_timestamp: float = 0.0

    @property
    def is_watching(self) -> bool:
        return self._running and self._task is not None and not self._task.done()

    def get_latest_observation(self) -> Optional[dict[str, Any]]:
        """Return the latest observation with staleness calculation."""
        if not self._latest_observation:
            return None

        age = time.time() - self._latest_timestamp
        obs = dict(self._latest_observation)
        obs["age_seconds"] = round(age, 2)
        obs["is_stale"] = age > STALENESS_THRESHOLD_SECONDS
        return obs

    async def start(self, interval: float = 2.0) -> bool:
        """Start periodic screen observation."""
        if self.is_watching:
            logger.info("screen_watch_already_active")
            return True

        self._interval = max(1.0, interval)
        self._running = True
        self._latest_observation = None
        self._latest_timestamp = 0.0

        self._task = asyncio.create_task(self._watch_loop())
        logger.info("screen_watch_started", interval=self._interval)
        return True

    async def stop(self) -> bool:
        """Stop screen watching immediately."""
        if not self._running:
            return False

        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None
        logger.info("screen_watch_stopped")
        return True

    async def _watch_loop(self) -> None:
        """Periodic background observation loop."""
        try:
            while self._running:
                # Ensure only ONE observation task runs at a time
                if not self._lock.locked():
                    async with self._lock:
                        try:
                            res = await screen_observe(target="auto", focus_question="")
                            if res.success and res.data:
                                self._latest_observation = res.data
                                self._latest_timestamp = res.data.get("timestamp", time.time())
                        except Exception as e:
                            logger.error("screen_watch_tick_failed", error=str(e))

                await asyncio.sleep(self._interval)
        except asyncio.CancelledError:
            pass
        finally:
            self._running = False


_watcher_instance: Optional[ScreenWatcher] = None


def get_screen_watcher() -> ScreenWatcher:
    """Singleton getter for ScreenWatcher."""
    global _watcher_instance
    if _watcher_instance is None:
        _watcher_instance = ScreenWatcher()
    return _watcher_instance


@tool(
    name="screen_watch_start",
    description="Start periodically observing the desktop screen in the background (default: every 2 seconds).",
    category="Screen",
    permission_level=PermissionLevel.SAFE,
    parameters=[
        ToolParameter(
            name="interval",
            type="number",
            description="Sampling interval in seconds (minimum 1.0, default 2.0).",
            required=False,
            default=2.0,
        )
    ],
)
async def screen_watch_start(interval: float = 2.0) -> ToolResult:
    """Start watching screen."""
    watcher = get_screen_watcher()
    await watcher.start(interval=interval)
    return ToolResult(
        success=True,
        message=f"Started watching screen every {max(1.0, interval):.1f} seconds.",
        data={"watching": True, "interval": max(1.0, interval)},
    )


@tool(
    name="screen_watch_stop",
    description="Stop the active screen watching background task immediately.",
    category="Screen",
    permission_level=PermissionLevel.SAFE,
)
async def screen_watch_stop() -> ToolResult:
    """Stop watching screen."""
    watcher = get_screen_watcher()
    stopped = await watcher.stop()
    msg = "Stopped watching screen." if stopped else "Screen watching was not active."
    return ToolResult(
        success=True,
        message=msg,
        data={"watching": False},
    )


def register(registry: ToolRegistry) -> None:
    """Register screen watcher tools."""
    registry.register(
        ToolDefinition(
            name="screen_watch_start",
            description="Start periodically observing the desktop screen in the background (default: every 2 seconds).",
            category="Screen",
            permission_level=PermissionLevel.SAFE,
            parameters=[
                ToolParameter(
                    name="interval",
                    type="number",
                    description="Sampling interval in seconds (minimum 1.0, default 2.0).",
                    required=False,
                    default=2.0,
                )
            ],
        ),
        screen_watch_start,
    )
    registry.register(
        ToolDefinition(
            name="screen_watch_stop",
            description="Stop the active screen watching background task immediately.",
            category="Screen",
            permission_level=PermissionLevel.SAFE,
            parameters=[],
        ),
        screen_watch_stop,
    )

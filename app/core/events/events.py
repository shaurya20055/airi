"""Core event types for the Airi event system.

Every inter-component notification is represented as a frozen dataclass that
extends ``Event``. The ``EventBus`` dispatches by exact type, so handlers
only receive events they subscribed to.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class Event:
    """Base event class with timestamp and source."""
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    source: str = "system"


# -- User / Assistant -------------------------------------------------------

@dataclass
class UserInputReceived(Event):
    """Fired when user input is received from any channel."""
    text: str = ""
    input_source: str = "text"  # 'voice' | 'text' | 'cli'


@dataclass
class AssistantResponseReady(Event):
    """Fired when the assistant has a response ready to output."""
    text: str = ""
    speak: bool = True


@dataclass
class AssistantThinking(Event):
    """Fired when the assistant starts processing."""
    pass


# -- Tool lifecycle ----------------------------------------------------------

@dataclass
class ToolExecutionStarted(Event):
    """Fired when a tool starts execution."""
    tool_name: str = ""
    args: dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolExecutionCompleted(Event):
    """Fired when a tool completes execution successfully."""
    tool_name: str = ""
    result: Any = None


@dataclass
class ToolExecutionFailed(Event):
    """Fired when a tool fails to execute."""
    tool_name: str = ""
    error: str = ""


# -- Avatar ------------------------------------------------------------------

@dataclass
class AvatarStateChanged(Event):
    """Fired when the avatar visual state should change."""
    state: str = ""
    expression: str = ""


# -- Voice -------------------------------------------------------------------

@dataclass
class SpeechStarted(Event):
    """Fired when TTS speech starts."""
    text: str = ""


@dataclass
class SpeechFinished(Event):
    """Fired when TTS speech finishes."""
    pass


@dataclass
class WakeWordDetected(Event):
    """Fired when the wake word is detected."""
    pass


# -- Screen ------------------------------------------------------------------

@dataclass
class ScreenshotCaptured(Event):
    """Fired when a screenshot is captured."""
    path: str = ""


# -- Permissions -------------------------------------------------------------

@dataclass
class PermissionRequested(Event):
    """Published when the agent needs user approval for a tool.

    For GUI flows the UI handles this and responds with
    ``PermissionGranted`` or ``PermissionDenied`` carrying the same
    ``request_id``.
    """
    tool_name: str = ""
    args: dict[str, Any] = field(default_factory=dict)
    level: str = ""
    request_id: str = ""
    description: str = ""


@dataclass
class PermissionGranted(Event):
    """Published by the UI to allow a pending permission request."""
    tool_name: str = ""
    request_id: str = ""
    for_session: bool = False


@dataclass
class PermissionDenied(Event):
    """Published by the UI to deny a pending permission request."""
    tool_name: str = ""
    request_id: str = ""


# -- System ------------------------------------------------------------------

@dataclass
class SystemDiagnosticsRequested(Event):
    """Fired to request system diagnostics."""
    pass


@dataclass
class ShutdownRequested(Event):
    """Fired to request application shutdown."""
    pass

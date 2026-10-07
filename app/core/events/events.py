from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict

@dataclass
class Event:
    """Base event class with timestamp and source."""
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    source: str = "system"

@dataclass
class UserInputReceived(Event):
    """Fired when user input is received."""
    text: str = ""
    input_source: str = "text" # 'voice'|'text'|'cli'

@dataclass
class AssistantResponseReady(Event):
    """Fired when the assistant has a response ready to output."""
    text: str = ""
    speak: bool = True

@dataclass
class AssistantThinking(Event):
    """Fired when the assistant starts processing."""
    pass

@dataclass
class ToolExecutionStarted(Event):
    """Fired when a tool starts execution."""
    tool_name: str = ""
    args: Dict[str, Any] = field(default_factory=dict)

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

@dataclass
class AvatarStateChanged(Event):
    """Fired when the avatar state should change."""
    state: str = ""
    expression: str = ""

@dataclass
class SpeechStarted(Event):
    """Fired when TTS speech starts."""
    text: str = ""

@dataclass
class SpeechFinished(Event):
    """Fired when TTS speech finishes."""
    pass

@dataclass
class ScreenshotCaptured(Event):
    """Fired when a screenshot is captured."""
    path: str = ""

@dataclass
class PermissionRequested(Event):
    """Fired when a tool requests permission."""
    tool_name: str = ""
    args: Dict[str, Any] = field(default_factory=dict)
    level: str = ""

@dataclass
class PermissionGranted(Event):
    """Fired when a permission request is granted."""
    tool_name: str = ""

@dataclass
class PermissionDenied(Event):
    """Fired when a permission request is denied."""
    tool_name: str = ""

@dataclass
class WakeWordDetected(Event):
    """Fired when the wake word is detected."""
    pass

@dataclass
class SystemDiagnosticsRequested(Event):
    """Fired to request system diagnostics."""
    pass

@dataclass
class ShutdownRequested(Event):
    """Fired to request application shutdown."""
    pass

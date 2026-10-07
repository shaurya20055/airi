from __future__ import annotations

from app.core.events.bus import EventBus, Event
from app.core.events.events import (
    UserInputReceived,
    AssistantResponseReady,
    AssistantThinking,
    ToolExecutionStarted,
    ToolExecutionCompleted,
    ToolExecutionFailed,
    AvatarStateChanged,
    SpeechStarted,
    SpeechFinished,
    ScreenshotCaptured,
    PermissionRequested,
    PermissionGranted,
    PermissionDenied,
    WakeWordDetected,
    SystemDiagnosticsRequested,
    ShutdownRequested,
)

__all__ = [
    "EventBus",
    "Event",
    "UserInputReceived",
    "AssistantResponseReady",
    "AssistantThinking",
    "ToolExecutionStarted",
    "ToolExecutionCompleted",
    "ToolExecutionFailed",
    "AvatarStateChanged",
    "SpeechStarted",
    "SpeechFinished",
    "ScreenshotCaptured",
    "PermissionRequested",
    "PermissionGranted",
    "PermissionDenied",
    "WakeWordDetected",
    "SystemDiagnosticsRequested",
    "ShutdownRequested",
]

"""Screen observation tool combining desktop capture with local vision inference."""
from __future__ import annotations

import time
from typing import Optional

import structlog

from app.tools.registry import PermissionLevel, ToolParameter, ToolRegistry, ToolResult, tool
from app.tools.screen.provider import ScreenCaptureProvider, get_screen_capture_provider
from app.tools.screen.vision import ScreenVisionProcessor, get_screen_vision_processor

logger = structlog.get_logger(__name__)


@tool(
    name="screen_observe",
    description=(
        "Capture the screen or active window and analyze its visible contents using the local vision model. "
        "Returns visible text, UI elements, active window, and summary."
    ),
    category="Screen",
    permission_level=PermissionLevel.SAFE,
    parameters=[
        ToolParameter(
            name="target",
            type="string",
            description="What to capture: 'screen' (entire monitor), 'window' (active window only), or 'auto'.",
            required=False,
            default="auto",
        ),
        ToolParameter(
            name="focus_question",
            type="string",
            description="Optional specific question (e.g., 'What is the error dialog saying?', 'What is on this webpage?').",
            required=False,
            default="",
        ),
    ],
)
async def screen_observe(target: str = "auto", focus_question: str = "") -> ToolResult:
    """Observe current screen or active window and analyze via local vision model."""
    provider = get_screen_capture_provider()
    vision_proc = get_screen_vision_processor()

    logger.info("screen_observation_requested", target=target, focus_question=focus_question)

    # 1. Fresh Capture
    if target == "window":
        capture_result = await provider.capture_active_window()
    else:
        capture_result = await provider.capture_active_screen()

    if not capture_result.success or not capture_result.image_bytes:
        err = capture_result.error or "Failed to capture desktop screen."
        logger.error("screen_observation_failure", reason="capture_failed", error=err)
        return ToolResult(
            success=False,
            error=err,
            message=f"Could not observe the screen: {err}",
            data={"timestamp": capture_result.timestamp, "capture_error": err},
        )

    # 2. Extract window info
    active_win = capture_result.active_window
    app_class = capture_result.app_class or (active_win.app_class if active_win else "Unknown")
    win_title = capture_result.active_window_title or (active_win.title if active_win else "Unknown")

    # 3. Vision Analysis
    try:
        analysis = await vision_proc.analyze_screen(
            image_bytes=capture_result.image_bytes,
            focus_prompt=focus_question,
        )
    finally:
        # Cleanup temporary file immediately to respect privacy
        provider.cleanup_file(capture_result.image_path)

    obs_timestamp = time.time()
    logger.info("observation_timestamp", timestamp=obs_timestamp)

    if not analysis.get("success"):
        err = analysis.get("error", "vision_failed")
        msg = analysis.get("message", "Local vision model was unable to inspect the screen.")
        logger.error("screen_observation_failure", reason="vision_failed", error=err)
        return ToolResult(
            success=False,
            error=err,
            message=msg,
            data={
                "timestamp": obs_timestamp,
                "active_window": active_win.to_dict() if active_win else None,
                "current_application": app_class,
                "window_title": win_title,
            },
        )

    # 4. Construct Structured Observation Result
    summary = analysis.get("summary", "")
    uncertainty = analysis.get("uncertainty", "none")
    visible_text = analysis.get("visible_text", [])
    ui_elements = analysis.get("ui_elements", [])
    detected_app = analysis.get("application") or app_class

    user_message = (
        f"Active window: '{win_title}' ({detected_app}).\n"
        f"Summary: {summary}"
    )
    if uncertainty and uncertainty.lower() not in ("none", "null", ""):
        user_message += f"\nNote: {uncertainty}"

    data_payload = {
        "timestamp": obs_timestamp,
        "active_window": active_win.to_dict() if active_win else None,
        "current_application": detected_app,
        "window_title": win_title,
        "visible_text": visible_text,
        "ui_elements": ui_elements,
        "summary": summary,
        "uncertainty": uncertainty,
        "untrusted_content": True,  # Security tagging: screen text is untrusted
    }

    return ToolResult(
        success=True,
        data=data_payload,
        message=user_message,
    )


def register(registry: ToolRegistry) -> None:
    """Explicitly register screen observation tool."""
    registry.register(
        ToolDefinition(
            name="screen_observe",
            description=(
                "Capture the screen or active window and analyze its visible contents using the local vision model. "
                "Returns visible text, UI elements, active window, and summary."
            ),
            category="Screen",
            permission_level=PermissionLevel.SAFE,
            parameters=[
                ToolParameter(
                    name="target",
                    type="string",
                    description="What to capture: 'screen' (entire monitor), 'window' (active window only), or 'auto'.",
                    required=False,
                    default="auto",
                ),
                ToolParameter(
                    name="focus_question",
                    type="string",
                    description="Optional specific question.",
                    required=False,
                    default="",
                ),
            ],
        ),
        screen_observe,
    )
from app.tools.registry import ToolDefinition

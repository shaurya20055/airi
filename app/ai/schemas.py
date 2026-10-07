from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel


class ToolCall(BaseModel):
    """A tool call requested by the AI."""
    id: str
    name: str
    arguments: dict[str, Any]


class ToolCallResult(BaseModel):
    """The result of executing a tool call."""
    tool_call_id: str
    result: str
    success: bool


class Message(BaseModel):
    """A message in an AI conversation."""
    role: str  # 'user', 'assistant', 'system', 'tool'
    content: str
    images: list[str] = []  # base64 encoded images
    tool_calls: list[ToolCall] = []
    tool_results: list[ToolCallResult] = []


class AIResponse(BaseModel):
    """A full response from the AI."""
    text: str
    tool_calls: list[ToolCall] = []
    finish_reason: str = 'stop'
    usage: dict[str, int] = {}


class IntentType(str, Enum):
    """The type of user intent."""
    TOOL_CALL = 'tool_call'      # Direct tool execution
    CONVERSATION = 'conversation' # Chat/question
    VISION = 'vision'            # Needs screen/image understanding
    COMPLEX = 'complex'          # Needs advanced reasoning
    UNKNOWN = 'unknown'


class ClassifiedIntent(BaseModel):
    """The classified intent of a user message."""
    type: IntentType
    confidence: float
    tool_name: str | None = None
    tool_args: dict[str, Any] = {}
    requires_cloud: bool = False

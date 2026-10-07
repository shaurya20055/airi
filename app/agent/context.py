from __future__ import annotations

from app.ai.schemas import Message, ToolCallResult

class AgentContext:
    """Manages the conversation context and history."""

    def __init__(self, max_history: int = 20):
        """Initialize the context."""
        self.messages: list[Message] = []
        self.max_history = max_history
        self._add_system_prompt()

    def _add_system_prompt(self):
        """Add the initial system prompt."""
        self.messages.append(Message(
            role="system",
            content="You are Airi, a helpful desktop AI assistant."
        ))

    def add_user_message(self, text: str, images: list[str] = None):
        """Add a user message to the context."""
        self.messages.append(Message(role="user", content=text, images=images or []))
        self._trim_history()

    def add_assistant_message(self, text: str):
        """Add an assistant message to the context."""
        self.messages.append(Message(role="assistant", content=text))
        self._trim_history()
        
    def add_tool_result(self, tool_call_id: str, result: str, success: bool = True):
        """Add a tool call result to the context."""
        tool_res = ToolCallResult(tool_call_id=tool_call_id, result=result, success=success)
        self.messages.append(Message(role="tool", content=result, tool_results=[tool_res]))
        self._trim_history()

    def get_messages(self) -> list[Message]:
        """Get the current conversation history."""
        return self.messages

    def clear(self):
        """Clear the conversation history, retaining the system prompt."""
        self.messages.clear()
        self._add_system_prompt()
        
    def _trim_history(self):
        """Trim history if it exceeds the maximum size."""
        if len(self.messages) > self.max_history:
            # Keep system prompt at index 0, and the last (max_history - 1) messages
            self.messages = [self.messages[0]] + self.messages[-(self.max_history - 1):]

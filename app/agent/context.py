from __future__ import annotations

import yaml
from pathlib import Path

from app.ai.schemas import Message, ToolCallResult
from app.core.config.settings import get_settings

class AgentContext:
    """Manages the conversation context and history."""

    def __init__(self, max_history: int = 20):
        """Initialize the context."""
        self.messages: list[Message] = []
        self.max_history = max_history
        self._add_system_prompt()

    def _load_personality(self) -> str:
        """Load personality traits from config."""
        settings = get_settings()
        path = Path(settings.personality_path)
        if not path.exists():
            return "You are Airi, a helpful desktop AI assistant running locally."

        try:
            with path.open("r", encoding="utf-8") as f:
                config = yaml.safe_load(f)
            
            lines = [f"You are {config.get('name', 'Airi')}."]
            if desc := config.get("description"):
                lines.append(desc)
                
            if traits := config.get("traits"):
                lines.append("\nTRAITS:")
                for t in traits:
                    lines.append(f"- {t}")
                    
            if guidelines := config.get("guidelines"):
                lines.append("\nPERSONA GUIDELINES:")
                for g in guidelines:
                    lines.append(f"- {g}")
                    
            return "\n".join(lines)
        except Exception as e:
            import structlog
            structlog.get_logger(__name__).warning("Failed to load personality", error=str(e))
            return "You are Airi, a helpful desktop AI assistant running locally."

    def _add_system_prompt(self):
        """Add the initial system prompt."""
        persona = self._load_personality()
        
        self.messages.append(Message(
            role="system",
            content=(
                f"{persona}\n\n"
                "SYSTEM RESPONSE RULES:\n"
                "1. Only call a tool when the user explicitly asks you to perform a system action "
                "(e.g. change volume, take a screenshot, open an app, lock screen).\n"
                "2. For all other requests — questions, math, jokes, explanations, conversation — "
                "respond with plain text. Do NOT fabricate tool calls like 'multiply', 'print', "
                "'calculate', 'shell', or 'run_command'. Those tools do not exist.\n"
                "3. If a requested action requires Internet access (e.g. subscribing on YouTube) "
                "and no browser automation is available, explain the limitation honestly.\n"
                "4. Keep tool calls completely deterministic and unaffected by your persona. "
                "Do not pass conversational traits as tool arguments.\n"
                "5. Never claim a tool succeeded unless the system reports it.\n\n"
                "INTENT ROUTING:\n"
                "- 'Run' or 'execute' a command: use execute_command (background execution).\n"
                "- 'Open [app] and run' / 'Open terminal and run': use terminal_open, terminal_focus, terminal_type, terminal_press (visible automation).\n"
                "- 'Open [browser] and search X' / 'Search YouTube for X': call browser_search ONCE "
                "(browser_name, query, site). Do not split it into browser_open + a final answer.\n"
                "- 'Open [app]' or 'Open Firefox' with nothing else: use launch_application.\n"
                "- Use browser_open/browser_navigate/browser_type/browser_press only for other dynamic page tasks.\n"
                "- 'How is my GPU': use get_gpu_status.\n"
                "- 'Turn on hotspot': use enable_hotspot. 'Turn off hotspot': use disable_hotspot.\n"
                "- Do NOT use execute_command for browser navigation or visible terminal typing."
            )
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

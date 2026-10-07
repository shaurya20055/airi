from __future__ import annotations

import inspect
import json
from enum import Enum
from typing import Any, Callable

from pydantic import BaseModel, Field


class PermissionLevel(str, Enum):
    SAFE = 'safe'
    CONFIRM = 'confirm'
    DANGEROUS = 'dangerous'
    BLOCKED = 'blocked'


class ToolParameter(BaseModel):
    name: str
    type: str
    description: str
    required: bool = True
    default: Any = None


class ToolDefinition(BaseModel):
    name: str
    description: str
    category: str
    permission_level: PermissionLevel
    parameters: list[ToolParameter] = Field(default_factory=list)
    requires_confirmation: bool = False
    enabled: bool = True


class ToolResult(BaseModel):
    success: bool
    data: Any = None
    message: str = ''
    error: str | None = None


class ToolRegistry:
    _instance = None
    _tools: dict[str, tuple[ToolDefinition, Callable]]

    def __new__(cls) -> ToolRegistry:
        if cls._instance is None:
            cls._instance = super(ToolRegistry, cls).__new__(cls)
            cls._instance._tools = {}
        return cls._instance

    def register(self, definition: ToolDefinition, func: Callable) -> None:
        """Register a new tool."""
        self._tools[definition.name] = (definition, func)

    def get_tool(self, name: str) -> tuple[ToolDefinition, Callable] | None:
        """Retrieve a tool by name."""
        return self._tools.get(name)

    def list_tools(self) -> list[ToolDefinition]:
        """List all registered tools."""
        return [t[0] for t in self._tools.values()]

    def list_by_category(self, category: str) -> list[ToolDefinition]:
        """List tools filtered by category."""
        return [t[0] for t in self._tools.values() if t[0].category == category]

    async def execute(self, name: str, args: dict[str, Any]) -> ToolResult:
        """Execute a tool by name, passing in the arguments."""
        tool = self.get_tool(name)
        if not tool:
            return ToolResult(success=False, error=f"Tool '{name}' not found.")
        
        definition, func = tool
        if not definition.enabled:
            return ToolResult(success=False, error=f"Tool '{name}' is disabled.")
        
        # Note: Permissions check should ideally wrap this execution
        # depending on integration with permissions.py.
        try:
            if inspect.iscoroutinefunction(func):
                result = await func(**args)
            else:
                result = func(**args)
            
            if isinstance(result, ToolResult):
                return result
            return ToolResult(success=True, data=result)
        except Exception as e:
            return ToolResult(success=False, error=str(e))

    def to_openai_tools(self) -> list[dict]:
        """Convert registered tools to OpenAI function calling format."""
        openai_tools = []
        for definition, _ in self._tools.values():
            if not definition.enabled:
                continue
            
            properties = {}
            required = []
            for param in definition.parameters:
                properties[param.name] = {
                    "type": param.type,
                    "description": param.description
                }
                if param.required:
                    required.append(param.name)
            
            tool_dict = {
                "type": "function",
                "function": {
                    "name": definition.name,
                    "description": definition.description,
                    "parameters": {
                        "type": "object",
                        "properties": properties,
                        "required": required
                    }
                }
            }
            openai_tools.append(tool_dict)
        return openai_tools

    def get_tool_descriptions(self) -> str:
        """Return human-readable list of tools."""
        lines = []
        for definition, _ in self._tools.values():
            if definition.enabled:
                lines.append(f"- {definition.name} ({definition.category}): {definition.description}")
        return "\n".join(lines)


# Global registry instance
registry = ToolRegistry()


def tool(name: str, description: str, category: str, permission_level: PermissionLevel, parameters: list[ToolParameter] | None = None, requires_confirmation: bool = False) -> Callable:
    """Decorator to register a tool."""
    def decorator(func: Callable) -> Callable:
        definition = ToolDefinition(
            name=name,
            description=description,
            category=category,
            permission_level=permission_level,
            parameters=parameters or [],
            requires_confirmation=requires_confirmation
        )
        registry.register(definition, func)
        return func
    return decorator

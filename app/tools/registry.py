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
    type: str          # 'integer', 'number', 'string', 'boolean', 'object', 'array'
    description: str
    required: bool = True
    default: Any = None
    minimum: int | float | None = None    # For integer/number types
    maximum: int | float | None = None    # For integer/number types
    enum_values: list[Any] | None = None  # For enumerated string/integer types


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
    task: Any = None


class ArgumentValidationError(Exception):
    """Raised when tool arguments fail validation."""
    pass


def _coerce_arg(value: Any, param: ToolParameter) -> Any:
    """Coerce and validate a single argument against its declared schema.

    Raises ArgumentValidationError with a descriptive message on failure.
    """
    t = param.type.lower()

    # --- Type coercion ---
    if t == "integer":
        if isinstance(value, bool):
            raise ArgumentValidationError(
                f"Parameter '{param.name}': expected integer, got boolean."
            )
        if isinstance(value, str):
            try:
                value = int(value)
            except ValueError:
                raise ArgumentValidationError(
                    f"Parameter '{param.name}': cannot convert '{value}' to integer."
                )
        elif isinstance(value, float):
            if value != int(value):
                raise ArgumentValidationError(
                    f"Parameter '{param.name}': float {value} has fractional part, expected integer."
                )
            value = int(value)
        elif not isinstance(value, int):
            raise ArgumentValidationError(
                f"Parameter '{param.name}': expected integer, got {type(value).__name__}."
            )

    elif t == "number":
        if isinstance(value, bool):
            raise ArgumentValidationError(
                f"Parameter '{param.name}': expected number, got boolean."
            )
        if isinstance(value, str):
            try:
                value = float(value)
            except ValueError:
                raise ArgumentValidationError(
                    f"Parameter '{param.name}': cannot convert '{value}' to number."
                )
        elif not isinstance(value, (int, float)):
            raise ArgumentValidationError(
                f"Parameter '{param.name}': expected number, got {type(value).__name__}."
            )

    elif t == "boolean":
        if isinstance(value, str):
            if value.lower() in ("true", "1", "yes"):
                value = True
            elif value.lower() in ("false", "0", "no"):
                value = False
            else:
                raise ArgumentValidationError(
                    f"Parameter '{param.name}': cannot convert '{value}' to boolean."
                )
        elif not isinstance(value, bool):
            raise ArgumentValidationError(
                f"Parameter '{param.name}': expected boolean, got {type(value).__name__}."
            )

    elif t == "string":
        if not isinstance(value, str):
            value = str(value)

    # --- Range validation ---
    if param.minimum is not None and value < param.minimum:
        raise ArgumentValidationError(
            f"Parameter '{param.name}': value {value} is below minimum {param.minimum}."
        )
    if param.maximum is not None and value > param.maximum:
        raise ArgumentValidationError(
            f"Parameter '{param.name}': value {value} is above maximum {param.maximum}."
        )

    # --- Enum validation ---
    if param.enum_values is not None and value not in param.enum_values:
        raise ArgumentValidationError(
            f"Parameter '{param.name}': value {value!r} not in allowed values {param.enum_values}."
        )

    return value


def coerce_and_validate_args(
    definition: ToolDefinition, raw_args: dict[str, Any]
) -> tuple[dict[str, Any], list[str]]:
    """Coerce and validate raw_args against the tool's parameter schema.

    Returns (coerced_args, errors).  errors is empty on success.
    """
    param_map = {p.name: p for p in definition.parameters}
    errors: list[str] = []
    coerced: dict[str, Any] = {}

    # Check required parameters
    for param in definition.parameters:
        if param.required and param.name not in raw_args:
            if param.default is not None:
                coerced[param.name] = param.default
            else:
                errors.append(f"Missing required parameter '{param.name}'.")

    # Coerce provided arguments
    for key, value in raw_args.items():
        if key not in param_map:
            # Unknown argument — silently ignore (LLM sometimes adds extras)
            continue
        try:
            coerced[key] = _coerce_arg(value, param_map[key])
        except ArgumentValidationError as e:
            errors.append(str(e))

    return coerced, errors


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
        """Execute a tool by name with validated/coerced arguments.

        Validation flow:
        1. Tool must be registered — unknown names are rejected immediately.
        2. Arguments are coerced to declared types (e.g. "35" → 35).
        3. Arguments are range/enum validated per schema.
        4. Only then is the tool function called.
        """
        entry = self.get_tool(name)
        if not entry:
            return ToolResult(
                success=False,
                error=f"Unknown tool '{name}'. Only registered tools may be called."
            )

        definition, func = entry
        if not definition.enabled:
            return ToolResult(success=False, error=f"Tool '{name}' is disabled.")

        # Coerce and validate arguments
        coerced, errors = coerce_and_validate_args(definition, args)
        if errors:
            return ToolResult(
                success=False,
                error=f"Argument validation failed for '{name}': " + "; ".join(errors)
            )

        try:
            if inspect.iscoroutinefunction(func):
                result = await func(**coerced)
            else:
                result = func(**coerced)

            if isinstance(result, ToolResult):
                return result
            return ToolResult(success=True, data=result)
        except Exception as e:
            return ToolResult(success=False, error=str(e))

    def to_openai_tools(self) -> list[dict]:
        """Convert registered tools to OpenAI function calling format.

        Includes minimum/maximum/enum constraints so the LLM understands
        valid argument ranges.
        """
        openai_tools = []
        for definition, _ in self._tools.values():
            if not definition.enabled:
                continue

            properties = {}
            required = []
            for param in definition.parameters:
                prop: dict[str, Any] = {
                    "type": param.type,
                    "description": param.description,
                }
                if param.minimum is not None:
                    prop["minimum"] = param.minimum
                if param.maximum is not None:
                    prop["maximum"] = param.maximum
                if param.enum_values is not None:
                    prop["enum"] = param.enum_values
                properties[param.name] = prop
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
                        "required": required,
                    },
                },
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


def tool(
    name: str,
    description: str,
    category: str,
    permission_level: PermissionLevel,
    parameters: list[ToolParameter] | None = None,
    requires_confirmation: bool = False,
) -> Callable:
    """Decorator to register a tool."""
    def decorator(func: Callable) -> Callable:
        definition = ToolDefinition(
            name=name,
            description=description,
            category=category,
            permission_level=permission_level,
            parameters=parameters or [],
            requires_confirmation=requires_confirmation,
        )
        registry.register(definition, func)
        return func
    return decorator

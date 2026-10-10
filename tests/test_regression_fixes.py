"""Regression tests for the fixes to tool validation, argument coercion,
fast-path determinism, unknown-tool rejection, and model configuration.

Tests are grouped by fix number for traceability.
"""
from __future__ import annotations

import pytest

from app.ai.providers.local.provider import LocalProvider
from app.ai.schemas import IntentType
from app.core.config.settings import Settings, get_settings
from app.tools.registry import (
    ArgumentValidationError,
    ToolDefinition,
    ToolParameter,
    ToolRegistry,
    ToolResult,
    _coerce_arg,
    coerce_and_validate_args,
    PermissionLevel,
)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _int_param(name: str, minimum: int | None = None, maximum: int | None = None) -> ToolParameter:
    return ToolParameter(
        name=name, type="integer", description="test",
        minimum=minimum, maximum=maximum,
    )


def _fresh_registry() -> ToolRegistry:
    """Return the global registry without touching any module-level state."""
    import app.tools.registry as mod
    # Save old tools, clear for test, restore after
    return mod.registry


# ── FIX 2: Argument coercion ─────────────────────────────────────────────────

class TestArgCoercion:
    """_coerce_arg converts types and enforces constraints."""

    def test_string_to_int(self):
        p = _int_param("level")
        assert _coerce_arg("35", p) == 35

    def test_float_whole_to_int(self):
        p = _int_param("level")
        assert _coerce_arg(35.0, p) == 35

    def test_int_passthrough(self):
        p = _int_param("level")
        assert _coerce_arg(40, p) == 40

    def test_non_numeric_string_raises(self):
        p = _int_param("level")
        with pytest.raises(ArgumentValidationError, match="cannot convert"):
            _coerce_arg("abc", p)

    def test_below_minimum_raises(self):
        p = _int_param("level", minimum=0, maximum=100)
        with pytest.raises(ArgumentValidationError, match="below minimum"):
            _coerce_arg(-1, p)

    def test_above_maximum_raises(self):
        p = _int_param("level", minimum=0, maximum=100)
        with pytest.raises(ArgumentValidationError, match="above maximum"):
            _coerce_arg(150, p)

    def test_at_boundary_minimum(self):
        p = _int_param("level", minimum=0, maximum=100)
        assert _coerce_arg(0, p) == 0

    def test_at_boundary_maximum(self):
        p = _int_param("level", minimum=0, maximum=100)
        assert _coerce_arg(100, p) == 100

    def test_boolean_rejected_as_int(self):
        p = _int_param("level")
        with pytest.raises(ArgumentValidationError, match="boolean"):
            _coerce_arg(True, p)

    def test_string_bool_true(self):
        p = ToolParameter(name="flag", type="boolean", description="test")
        assert _coerce_arg("true", p) is True

    def test_string_bool_false(self):
        p = ToolParameter(name="flag", type="boolean", description="test")
        assert _coerce_arg("false", p) is False


class TestCoerceAndValidateArgs:
    """coerce_and_validate_args integrates coercion with the full definition."""

    def _make_def(self) -> ToolDefinition:
        return ToolDefinition(
            name="set_volume",
            description="Set volume",
            category="OS",
            permission_level=PermissionLevel.SAFE,
            parameters=[_int_param("level", minimum=0, maximum=100)],
        )

    def test_string_level_coerced(self):
        coerced, errors = coerce_and_validate_args(self._make_def(), {"level": "35"})
        assert errors == []
        assert coerced["level"] == 35

    def test_non_numeric_produces_error(self):
        _, errors = coerce_and_validate_args(self._make_def(), {"level": "abc"})
        assert errors  # non-empty

    def test_out_of_range_produces_error(self):
        _, errors = coerce_and_validate_args(self._make_def(), {"level": 150})
        assert errors

    def test_unknown_arg_ignored(self):
        coerced, errors = coerce_and_validate_args(
            self._make_def(), {"level": 40, "extra_param": "ignored"}
        )
        assert errors == []
        assert "extra_param" not in coerced

    def test_missing_required_produces_error(self):
        _, errors = coerce_and_validate_args(self._make_def(), {})
        assert errors


# ── FIX 1: Unknown tool rejection ────────────────────────────────────────────

class TestUnknownToolRejection:
    """Registry must reject unknown tool names without executing anything."""

    @pytest.mark.asyncio
    async def test_unknown_tool_rejected(self):
        import app.tools.registry as mod
        old_tools = dict(mod.registry._tools)
        mod.registry._tools.clear()

        defn = ToolDefinition(
            name="safe_tool",
            description="A safe tool",
            category="test",
            permission_level=PermissionLevel.SAFE,
        )
        sentinel = {"called": False}

        async def safe_fn() -> ToolResult:
            sentinel["called"] = True
            return ToolResult(success=True, message="ok")

        mod.registry.register(defn, safe_fn)

        # Execute unknown tool
        result = await mod.registry.execute("multiply", {})
        assert result.success is False
        assert "unknown" in result.error.lower() or "not found" in result.error.lower()
        assert sentinel["called"] is False  # safe_fn must NOT have been called

        mod.registry._tools = old_tools  # restore

    @pytest.mark.asyncio
    async def test_shell_tool_rejected(self):
        """No tool called 'shell' or 'run_command' may ever execute."""
        import app.tools.registry as mod
        for dangerous_name in ("shell", "run_command", "execute", "print"):
            result = await mod.registry.execute(dangerous_name, {"cmd": "rm -rf /"})
            assert result.success is False


# ── FIX 3: Text vs tool calls ─────────────────────────────────────────────────

class TestTextVsToolCalls:
    """Conversational inputs must NOT produce spurious tool calls."""

    def test_joke_request_is_conversation(self):
        p = LocalProvider()
        intent = p.classify_intent("Tell me a short joke.")
        assert intent.type == IntentType.CONVERSATION

    def test_math_question_is_conversation(self):
        p = LocalProvider()
        intent = p.classify_intent("What is 27 times 43?")
        assert intent.type == IntentType.CONVERSATION

    def test_explain_ram_is_conversation(self):
        p = LocalProvider()
        intent = p.classify_intent("Explain what RAM is.")
        assert intent.type == IntentType.CONVERSATION

    def test_greeting_is_conversation(self):
        p = LocalProvider()
        intent = p.classify_intent("Hey Airi, how are you?")
        assert intent.type == IntentType.CONVERSATION


# ── FIX 5: Deterministic fast path ───────────────────────────────────────────

class TestFastPath:
    """High-confidence commands must be caught by the pattern matcher."""

    def test_set_volume_percent(self):
        p = LocalProvider()
        intent = p.classify_intent("Set my volume to 35 percent.")
        assert intent.type == IntentType.TOOL_CALL
        assert intent.tool_name == "set_volume"
        assert intent.tool_args["level"] == 35

    def test_set_volume_symbol(self):
        p = LocalProvider()
        intent = p.classify_intent("set volume to 40%")
        assert intent.type == IntentType.TOOL_CALL
        assert intent.tool_args["level"] == 40

    def test_set_volume_bare(self):
        p = LocalProvider()
        intent = p.classify_intent("set volume to 40")
        assert intent.type == IntentType.TOOL_CALL
        assert intent.tool_args["level"] == 40

    def test_set_brightness_percent(self):
        p = LocalProvider()
        intent = p.classify_intent("Set my brightness to 50 percent.")
        assert intent.type == IntentType.TOOL_CALL
        assert intent.tool_name == "set_brightness"
        assert intent.tool_args["level"] == 50

    def test_screenshot_fast_path(self):
        p = LocalProvider()
        intent = p.classify_intent("Take a screenshot.")
        assert intent.type == IntentType.TOOL_CALL
        assert intent.tool_name == "take_screenshot"

    def test_mute_fast_path(self):
        p = LocalProvider()
        intent = p.classify_intent("mute")
        assert intent.type == IntentType.TOOL_CALL
        assert intent.tool_name == "mute"

    def test_open_youtube_complex_goes_to_llm(self):
        """'Open YouTube and subscribe...' is too complex for the fast path."""
        p = LocalProvider()
        intent = p.classify_intent("Open YouTube and subscribe to ElectroBOOM.")
        # Must NOT be a tool call (the complex sentence won't match the narrow open pattern)
        assert intent.type == IntentType.CONVERSATION

    def test_open_simple_app(self):
        """'open firefox' is a single token — fast path should catch it."""
        p = LocalProvider()
        intent = p.classify_intent("open firefox")
        assert intent.type == IntentType.TOOL_CALL
        assert intent.tool_name == "launch_application"
        assert intent.tool_args["name"] == "firefox"


# ── FIX 6: Model configuration ───────────────────────────────────────────────

class TestModelConfiguration:
    """The active local model must be configurable and clearly reported."""

    def test_default_model_is_qwen(self):
        s = Settings()
        assert s.local_ai_model == "qwen3-vl:4b-instruct"

    def test_model_can_be_overridden(self, monkeypatch):
        import app.core.config.settings as mod
        mod._settings_instance = None
        monkeypatch.setenv("LOCAL_AI_MODEL", "llama3.2:latest")
        s = get_settings()
        assert s.local_ai_model == "llama3.2:latest"
        mod._settings_instance = None

    def test_local_ai_enabled_default(self):
        s = Settings()
        assert s.local_ai_enabled is True

    def test_local_ai_runtime_default(self):
        s = Settings()
        assert s.local_ai_runtime == "ollama"

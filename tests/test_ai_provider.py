"""Tests for AI providers and router."""
from __future__ import annotations

import pytest
from app.ai.providers.local.provider import LocalProvider
from app.ai.router import AIRouter
from app.ai.schemas import IntentType, Message, AIResponse


# --- LocalProvider intent classification ---

def test_classify_set_volume(local_provider):
    intent = local_provider.classify_intent("set volume to 40")
    assert intent.type == IntentType.TOOL_CALL
    assert intent.tool_name == "set_volume"
    assert intent.tool_args["level"] == 40


def test_classify_volume_shorthand(local_provider):
    intent = local_provider.classify_intent("volume 75")
    assert intent.type == IntentType.TOOL_CALL
    assert intent.tool_name == "set_volume"
    assert intent.tool_args["level"] == 75


def test_classify_brightness(local_provider):
    intent = local_provider.classify_intent("set brightness to 60%")
    assert intent.type == IntentType.TOOL_CALL
    assert intent.tool_name == "set_brightness"
    assert intent.tool_args["level"] == 60


def test_classify_launch_app(local_provider):
    intent = local_provider.classify_intent("open firefox")
    assert intent.type == IntentType.TOOL_CALL
    assert intent.tool_name == "launch_application"
    assert intent.tool_args["name"].lower() == "firefox"


def test_classify_screenshot(local_provider):
    intent = local_provider.classify_intent("take a screenshot")
    assert intent.type == IntentType.TOOL_CALL
    assert intent.tool_name == "take_screenshot"


def test_classify_lock_screen(local_provider):
    intent = local_provider.classify_intent("lock the screen")
    assert intent.type == IntentType.TOOL_CALL
    assert intent.tool_name == "lock_screen"


def test_classify_mute(local_provider):
    intent = local_provider.classify_intent("mute")
    assert intent.type == IntentType.TOOL_CALL
    assert intent.tool_name == "mute"


def test_classify_unknown(local_provider):
    intent = local_provider.classify_intent("what is the meaning of life?")
    assert intent.type == IntentType.CONVERSATION
    assert intent.requires_cloud is True


# --- LocalProvider respond ---

@pytest.mark.asyncio
async def test_respond_known_command(local_provider):
    msgs = [Message(role="user", content="set volume to 50")]
    response = await local_provider.respond(msgs)
    assert len(response.tool_calls) == 1
    assert response.tool_calls[0].name == "set_volume"


@pytest.mark.asyncio
async def test_respond_unknown_returns_text(local_provider):
    msgs = [Message(role="user", content="explain quantum physics")]
    response = await local_provider.respond(msgs)
    assert len(response.tool_calls) == 0
    assert response.text != ""


@pytest.mark.asyncio
async def test_respond_empty_messages(local_provider):
    response = await local_provider.respond([])
    assert response.text == ""


def test_is_available(local_provider):
    assert local_provider.is_available() is True


def test_supports_vision(local_provider):
    assert local_provider.supports_vision() is False


def test_supports_tools(local_provider):
    assert local_provider.supports_tools() is True


def test_name(local_provider):
    assert local_provider.name == "local"


# --- AIRouter ---

@pytest.mark.asyncio
async def test_router_local_tool_call(local_provider):
    router = AIRouter(local_provider=local_provider)
    intent = await router.classify_intent("set volume to 40")
    assert intent.type == IntentType.TOOL_CALL


@pytest.mark.asyncio
async def test_router_process_local(local_provider):
    router = AIRouter(local_provider=local_provider)
    response = await router.process("set volume to 40")
    assert len(response.tool_calls) == 1


@pytest.mark.asyncio
async def test_router_no_cloud_fallback(local_provider):
    router = AIRouter(local_provider=local_provider, cloud_provider=None)
    response = await router.process("explain quantum physics")
    assert "unavailable" in response.text.lower() or "cloud" in response.text.lower()


@pytest.mark.asyncio
async def test_router_cloud_available(local_provider, mock_cloud_provider):
    router = AIRouter(local_provider=local_provider, cloud_provider=mock_cloud_provider)
    assert router.is_cloud_available() is True


@pytest.mark.asyncio
async def test_router_cloud_used_for_conversation(local_provider, mock_cloud_provider):
    router = AIRouter(local_provider=local_provider, cloud_provider=mock_cloud_provider)
    response = await router.process("tell me a joke")
    assert response.text == "Cloud response"

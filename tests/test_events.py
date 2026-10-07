"""Tests for app.core.events — EventBus and event types."""
from __future__ import annotations

import asyncio
import pytest
from app.core.events.bus import EventBus
from app.core.events.events import (
    Event,
    UserInputReceived,
    ToolExecutionStarted,
    ToolExecutionCompleted,
    AssistantThinking,
    ShutdownRequested,
)


@pytest.mark.asyncio
async def test_subscribe_and_publish(event_bus):
    received = []

    async def handler(event):
        received.append(event)

    event_bus.subscribe(UserInputReceived, handler)
    await event_bus.publish(UserInputReceived(text="hello", input_source="cli"))
    await asyncio.sleep(0.05)
    assert len(received) == 1
    assert received[0].text == "hello"


@pytest.mark.asyncio
async def test_publish_and_wait(event_bus):
    results = []

    async def handler(event):
        await asyncio.sleep(0.01)
        results.append("done")

    event_bus.subscribe(UserInputReceived, handler)
    await event_bus.publish_and_wait(UserInputReceived(text="hello"))
    assert len(results) == 1


@pytest.mark.asyncio
async def test_unsubscribe(event_bus):
    received = []

    async def handler(event):
        received.append(event)

    event_bus.subscribe(UserInputReceived, handler)
    event_bus.unsubscribe(UserInputReceived, handler)
    await event_bus.publish(UserInputReceived(text="hello"))
    await asyncio.sleep(0.05)
    assert len(received) == 0


@pytest.mark.asyncio
async def test_handler_error_does_not_crash_bus(event_bus):
    async def bad_handler(event):
        raise ValueError("Oops")

    event_bus.subscribe(UserInputReceived, bad_handler)
    # Should not raise
    await event_bus.publish_and_wait(UserInputReceived(text="hello"))


@pytest.mark.asyncio
async def test_multiple_handlers(event_bus):
    r1 = []
    r2 = []

    async def h1(e):
        r1.append(e)

    async def h2(e):
        r2.append(e)

    event_bus.subscribe(UserInputReceived, h1)
    event_bus.subscribe(UserInputReceived, h2)
    await event_bus.publish_and_wait(UserInputReceived(text="multi"))
    assert len(r1) == 1
    assert len(r2) == 1


@pytest.mark.asyncio
async def test_different_event_types_isolated(event_bus):
    received = []

    async def handler(event):
        received.append(event)

    event_bus.subscribe(UserInputReceived, handler)
    await event_bus.publish(AssistantThinking())  # different type
    await asyncio.sleep(0.05)
    assert len(received) == 0


def test_event_timestamp():
    event = Event()
    assert event.timestamp is not None
    assert event.source == "system"


def test_user_input_event():
    e = UserInputReceived(text="test", input_source="voice")
    assert e.text == "test"
    assert e.input_source == "voice"


def test_tool_execution_event():
    e = ToolExecutionStarted(tool_name="set_volume", args={"level": 40})
    assert e.tool_name == "set_volume"
    assert e.args["level"] == 40

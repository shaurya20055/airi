"""Tests for app.core.state.manager."""
from __future__ import annotations

import pytest
from app.core.state.manager import AppState, StateManager


def test_initial_state(event_bus):
    sm = StateManager(event_bus)
    assert sm.state == AppState.INITIALIZING


@pytest.mark.asyncio
async def test_transition(event_bus):
    sm = StateManager(event_bus)
    await sm.transition(AppState.READY)
    assert sm.state == AppState.READY


@pytest.mark.asyncio
async def test_transition_to_same_state_is_noop(event_bus):
    sm = StateManager(event_bus)
    await sm.transition(AppState.READY)
    await sm.transition(AppState.READY)
    assert sm.state == AppState.READY

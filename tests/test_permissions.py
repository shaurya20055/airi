"""Tests for app.core.permissions.manager."""
from __future__ import annotations

import pytest
from app.core.permissions.manager import PermissionManager, PermissionLevel


def test_safe_auto_allowed(permission_manager):
    assert permission_manager.check_permission("any_tool", PermissionLevel.SAFE) is True


def test_blocked_always_denied(permission_manager):
    assert permission_manager.check_permission("any_tool", PermissionLevel.BLOCKED) is False


def test_confirm_denied_without_session(permission_manager):
    assert permission_manager.check_permission("some_tool", PermissionLevel.CONFIRM) is False


def test_session_permission_grants_access(permission_manager):
    permission_manager.grant_session_permission("my_tool")
    assert permission_manager.check_permission("my_tool", PermissionLevel.CONFIRM) is True


def test_block_tool(permission_manager):
    permission_manager.block_tool("bad_tool")
    assert permission_manager.is_blocked("bad_tool") is True
    assert permission_manager.is_blocked("good_tool") is False


def test_blocked_tool_denied_even_if_safe(permission_manager):
    permission_manager.block_tool("blocked_one")
    assert permission_manager.check_permission("blocked_one", PermissionLevel.SAFE) is False


@pytest.mark.asyncio
async def test_request_permission_safe_auto_grants(permission_manager):
    result = await permission_manager.request_permission("tool", {}, PermissionLevel.SAFE)
    assert result is True


@pytest.mark.asyncio
async def test_request_permission_blocked_auto_denies(permission_manager):
    result = await permission_manager.request_permission("tool", {}, PermissionLevel.BLOCKED)
    assert result is False

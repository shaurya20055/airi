"""Permission enforcement.

The PermissionManager decides whether a tool call may run. User interaction is
delegated to a pluggable ``PermissionPrompter`` so the same policy works for the
CLI, the future Qt overlay, and headless/test contexts.

Policy:
    SAFE       -> allowed
    CONFIRM    -> ask; user may allow once or for the whole session
    DANGEROUS  -> ask every time with an explicit warning; never session-allowed
    BLOCKED    -> denied, no prompt
Config overrides may only make a tool *stricter*, never more permissive.
"""
from __future__ import annotations

import asyncio
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import structlog

from app.core.events.bus import EventBus
from app.core.events.events import PermissionDenied, PermissionGranted, PermissionRequested
from app.core.permissions.levels import PermissionLevel

logger = structlog.get_logger(__name__)

__all__ = [
    "PermissionLevel",
    "PermissionDecision",
    "PermissionRequest",
    "PermissionPrompter",
    "DenyAllPrompter",
    "CLIPrompter",
    "EventBusPrompter",
    "PermissionManager",
]


class PermissionDecision(str, Enum):
    ALLOW_ONCE = "allow_once"
    ALLOW_SESSION = "allow_session"
    DENY = "deny"


@dataclass(frozen=True)
class PermissionRequest:
    """A request shown to the user."""

    tool_name: str
    level: PermissionLevel
    args: dict[str, Any]
    description: str = ""
    request_id: str = field(default_factory=lambda: uuid.uuid4().hex)


class PermissionPrompter(ABC):
    """Asks the user for a decision. Implementations must never block the event loop."""

    @abstractmethod
    async def ask(self, request: PermissionRequest) -> PermissionDecision: ...


class DenyAllPrompter(PermissionPrompter):
    """Headless default: anything that needs confirmation is denied."""

    async def ask(self, request: PermissionRequest) -> PermissionDecision:
        return PermissionDecision.DENY


class CLIPrompter(PermissionPrompter):
    """Interactive terminal prompt (input() runs in a worker thread)."""

    async def ask(self, request: PermissionRequest) -> PermissionDecision:
        dangerous = request.level == PermissionLevel.DANGEROUS
        header = "⚠  DANGEROUS ACTION" if dangerous else "Permission required"
        lines = [
            f"\n[{header}] Airi wants to run: {request.tool_name}",
            f"  {request.description}" if request.description else "",
            f"  Arguments: {request.args}",
        ]
        print("\n".join(line for line in lines if line))
        if dangerous:
            answer = await asyncio.to_thread(input, "  Type 'yes' to allow this once: ")
            return PermissionDecision.ALLOW_ONCE if answer.strip().lower() == "yes" else PermissionDecision.DENY
        while True:
            answer = (await asyncio.to_thread(input, "  Allow? [y]es / [n]o / [a]lways this session: ")).strip().lower()
            if answer in ("y", "yes"):
                return PermissionDecision.ALLOW_ONCE
            if answer in ("a", "always"):
                return PermissionDecision.ALLOW_SESSION
            if answer in ("n", "no", ""):
                return PermissionDecision.DENY


class EventBusPrompter(PermissionPrompter):
    """For GUI clients: publishes PermissionRequested and waits for a matching reply event.

    The UI answers by publishing PermissionGranted / PermissionDenied with the same
    ``request_id``. No answer within ``timeout_s`` means DENY.
    """

    def __init__(self, event_bus: EventBus, timeout_s: float = 60.0) -> None:
        self._bus = event_bus
        self._timeout_s = timeout_s
        self._pending: dict[str, asyncio.Future[PermissionDecision]] = {}
        event_bus.subscribe(PermissionGranted, self._on_granted)
        event_bus.subscribe(PermissionDenied, self._on_denied)

    async def _on_granted(self, event: PermissionGranted) -> None:
        fut = self._pending.get(event.request_id)
        if fut and not fut.done():
            fut.set_result(PermissionDecision.ALLOW_SESSION if event.for_session else PermissionDecision.ALLOW_ONCE)

    async def _on_denied(self, event: PermissionDenied) -> None:
        fut = self._pending.get(event.request_id)
        if fut and not fut.done():
            fut.set_result(PermissionDecision.DENY)

    async def ask(self, request: PermissionRequest) -> PermissionDecision:
        fut: asyncio.Future[PermissionDecision] = asyncio.get_running_loop().create_future()
        self._pending[request.request_id] = fut
        try:
            await self._bus.publish(PermissionRequested(
                tool_name=request.tool_name, args=request.args,
                level=request.level.value, request_id=request.request_id,
                description=request.description,
            ))
            return await asyncio.wait_for(fut, timeout=self._timeout_s)
        except asyncio.TimeoutError:
            logger.warning("permission_timeout", tool=request.tool_name)
            return PermissionDecision.DENY
        finally:
            self._pending.pop(request.request_id, None)


class PermissionManager:
    """Central permission policy."""

    def __init__(
        self,
        event_bus: EventBus,
        cli_mode: bool = False,
        prompter: PermissionPrompter | None = None,
        overrides: dict[str, PermissionLevel] | None = None,
    ) -> None:
        self._event_bus = event_bus
        if prompter is None:
            prompter = CLIPrompter() if cli_mode else DenyAllPrompter()
        self._prompter = prompter
        self._session_permissions: set[str] = set()
        self._blocked_tools: set[str] = set()
        self._overrides: dict[str, PermissionLevel] = dict(overrides or {})

    # -- policy helpers ----------------------------------------------------

    def check_permission(self, tool_name: str, level: PermissionLevel, args: dict[str, Any] | None = None) -> bool:
        """True if the tool may run *without* prompting."""
        level = self.effective_level(tool_name, level, args)
        if level == PermissionLevel.BLOCKED:
            return False
        if level == PermissionLevel.SAFE:
            return True
        if level == PermissionLevel.CONFIRM and tool_name in self._session_permissions:
            return True
        return False

    def effective_level(self, tool_name: str, declared: PermissionLevel, args: dict[str, Any] | None = None) -> PermissionLevel:
        """Declared level combined with blocks/overrides and dynamic policies."""
        if tool_name in self._blocked_tools:
            return PermissionLevel.BLOCKED
            
        # Dynamic policy for commands
        if tool_name == "execute_command" and args:
            from app.core.permissions.command_policy import CommandPolicy
            dynamic_level, _ = CommandPolicy.classify(args)
            declared = PermissionLevel.strictest(declared, dynamic_level)
            
        if tool_name == "execute_shell":
            declared = PermissionLevel.DANGEROUS
            
        override = self._overrides.get(tool_name)
        if override is None:
            return declared
        return PermissionLevel.strictest(declared, override)

    async def request_permission(
        self, tool_name: str, args: dict[str, Any], level: PermissionLevel, description: str = ""
    ) -> bool:
        """Return True if the tool may run, prompting the user if needed."""
        # Dynamic policy reason evaluation
        if tool_name == "execute_command" and args:
            from app.core.permissions.command_policy import CommandPolicy
            dynamic_level, reason = CommandPolicy.classify(args)
            if reason:
                description = f"{description} ({reason})" if description else reason

        if tool_name == "execute_shell":
            reason = "Raw shell execution is highly dangerous"
            description = f"{description} ({reason})" if description else reason

        effective = self.effective_level(tool_name, level, args)
        if effective == PermissionLevel.BLOCKED:
            logger.info("permission_blocked", tool=tool_name)
            return False
        if self.check_permission(tool_name, effective, args):
            return True

        request = PermissionRequest(tool_name=tool_name, level=effective, args=args, description=description)
        logger.info("permission_requested", tool=tool_name, level=effective.value)
        try:
            decision = await self._prompter.ask(request)
        except (EOFError, KeyboardInterrupt):
            decision = PermissionDecision.DENY

        if decision == PermissionDecision.ALLOW_SESSION and effective == PermissionLevel.CONFIRM:
            self.grant_session_permission(tool_name)
        allowed = decision != PermissionDecision.DENY
        logger.info("permission_decision", tool=tool_name, decision=decision.value)
        return allowed

    def grant_session_permission(self, tool_name: str) -> None:
        """Allow a CONFIRM-level tool for the rest of this session."""
        self._session_permissions.add(tool_name)

    def revoke_session_permissions(self) -> None:
        self._session_permissions.clear()

    def is_blocked(self, tool_name: str) -> bool:
        return tool_name in self._blocked_tools or self._overrides.get(tool_name) == PermissionLevel.BLOCKED

    def block_tool(self, tool_name: str) -> None:
        self._blocked_tools.add(tool_name)

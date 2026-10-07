"""Permission levels — the single source of truth for the whole application.

Every tool declares one of these levels. The PermissionManager enforces them
at the single execution choke point (``app.agent.executor.ToolExecutor``).
"""
from __future__ import annotations

from enum import Enum


class PermissionLevel(str, Enum):
    """How much user involvement a tool requires before it may run."""

    SAFE = "safe"            # Runs without asking (read-only / trivially reversible)
    CONFIRM = "confirm"      # Asks the user; may be allowed for the whole session
    DANGEROUS = "dangerous"  # Asks every time with an explicit warning; never session-allowed
    BLOCKED = "blocked"      # Never runs

    @property
    def rank(self) -> int:
        """Numeric strictness used when combining levels (higher = stricter)."""
        return _RANK[self]

    @classmethod
    def strictest(cls, *levels: "PermissionLevel") -> "PermissionLevel":
        """Return the strictest of the given levels."""
        return max(levels, key=lambda lvl: lvl.rank)


_RANK = {
    PermissionLevel.SAFE: 0,
    PermissionLevel.CONFIRM: 1,
    PermissionLevel.DANGEROUS: 2,
    PermissionLevel.BLOCKED: 3,
}

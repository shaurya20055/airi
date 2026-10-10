"""Browser permission policy classifying sensitive vs normal browser operations."""
from __future__ import annotations

import re
from typing import Any
from app.core.permissions.levels import PermissionLevel

# Selectors or keywords indicative of sensitive or consequential operations
SENSITIVE_SELECTORS = re.compile(
    r"\b(?:pay|payment|purchase|checkout|buy|order|confirm-payment|billing|credit-card|cvv|password|passphrase|secret|delete-account|transfer)\b",
    re.I
)


class BrowserPolicy:
    """Classifies browser automation operations into SAFE or CONFIRM."""

    @classmethod
    def classify(cls, tool_name: str, args: dict[str, Any]) -> tuple[PermissionLevel, str]:
        # Sensitive clicks
        if tool_name == "browser_click":
            selector = str(args.get("selector", ""))
            if SENSITIVE_SELECTORS.search(selector):
                return PermissionLevel.CONFIRM, f"Clicking sensitive element '{selector}'"

        # Sensitive typing
        if tool_name == "browser_type":
            selector = str(args.get("selector", ""))
            if SENSITIVE_SELECTORS.search(selector):
                return PermissionLevel.CONFIRM, f"Typing into sensitive field '{selector}'"

        # Sensitive navigation
        if tool_name == "browser_navigate":
            url = str(args.get("url", "")).lower()
            if any(scheme in url for scheme in ("javascript:", "file:", "data:")):
                return PermissionLevel.CONFIRM, f"Navigation to sensitive scheme in '{url}'"

        # By default, normal requested browser operations are SAFE under BROWSER_CONTROL policy
        return PermissionLevel.SAFE, ""

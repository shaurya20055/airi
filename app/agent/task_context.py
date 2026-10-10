"""Active task and browser context management for contextual reference resolution."""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any, Optional

import structlog

logger = structlog.get_logger(__name__)


@dataclass
class BrowserTaskContext:
    """Explicit context describing active browser session and search/navigation state."""
    active_browser_name: str = ""
    current_url: str = ""
    current_title: str = ""
    last_search_query: str = ""
    last_search_site: str = ""
    relevant_result_type: str = ""  # "video", "result", "option", "webpage"
    pending_operation: str = ""
    last_observed_state: dict[str, Any] = field(default_factory=dict)
    updated_at: float = 0.0

    def has_active_session(self) -> bool:
        """Check if an active browser session exists in the browser automation module."""
        try:
            from app.tools.browser.automation import _page, _active_browser_name
            if _page and not _page.is_closed():
                return True
        except Exception:
            pass
        return bool(self.active_browser_name and (self.current_url or self.last_search_query))

    def update_search(self, browser_name: str, query: str, site: str, url: str = "", title: str = "") -> None:
        self.active_browser_name = browser_name or self.active_browser_name or "Firefox"
        self.last_search_query = query
        self.last_search_site = site
        self.current_url = url or self.current_url
        self.current_title = title or self.current_title
        if "youtube" in site.lower() or "youtube.com" in url.lower():
            self.relevant_result_type = "video"
        else:
            self.relevant_result_type = "result"
        self.updated_at = time.time()
        logger.info(
            "browser_context_updated",
            browser=self.active_browser_name,
            query=self.last_search_query,
            site=self.last_search_site,
            result_type=self.relevant_result_type,
            url=self.current_url,
        )

    def update_navigation(self, url: str, title: str = "") -> None:
        self.current_url = url
        self.current_title = title or self.current_title
        if "youtube.com" in url.lower():
            self.relevant_result_type = "video"
        self.updated_at = time.time()

    def clear(self) -> None:
        self.active_browser_name = ""
        self.current_url = ""
        self.current_title = ""
        self.last_search_query = ""
        self.last_search_site = ""
        self.relevant_result_type = ""
        self.pending_operation = ""
        self.last_observed_state.clear()
        self.updated_at = 0.0


# Regex patterns matching browser result references
_ORDINAL_MAP = {
    "first": 1, "1st": 1, "one": 1, "1": 1,
    "second": 2, "2nd": 2, "two": 2, "2": 2,
    "third": 3, "3rd": 3, "three": 3, "3": 3,
    "fourth": 4, "4th": 4, "four": 4, "4": 4,
    "fifth": 5, "5th": 5, "five": 5, "5": 5,
}

_BROWSER_REF_PATTERN = re.compile(
    r"\b(?:the\s+)?(first|second|third|fourth|fifth|1st|2nd|3rd|4th|5th|1|2|3)\s+"
    r"(video|result|search\s+result|option)"
    r"(?:\s+(?:that\s+comes\s+in\s+the\s+result|in\s+the\s+results?|on\s+the\s+page|in\s+the\s+browser|on\s+youtube))?",
    re.I
)

_PRONOUN_REF_PATTERN = re.compile(
    r"^(?:open|play|click|select)\s+(?:it|that\s+video|that\s+result|that\s+page)[.!?]?$",
    re.I
)


def is_browser_result_reference(text: str) -> bool:
    """Check if utterance refers to a browser result, video, or page element."""
    clean = text.strip()
    if _BROWSER_REF_PATTERN.search(clean):
        return True
    if _PRONOUN_REF_PATTERN.search(clean):
        return True
    # "open the first video", "play the first video", "open the first video that comes in the result"
    if re.search(r"\b(?:open|play|click|select)\s+(?:the\s+)?(?:first|second|third|1st|2nd)\s+(?:video|result|option)\b", clean, re.I):
        return True
    return False


def parse_browser_reference(text: str, context: Optional[BrowserTaskContext] = None) -> dict[str, Any]:
    """Parse item_type, index, and query from a reference expression."""
    clean = text.strip()
    ctx = context or get_browser_task_context()

    index = 1
    item_type = "video" if (ctx.relevant_result_type == "video" or "video" in clean.lower()) else "result"

    match = _BROWSER_REF_PATTERN.search(clean)
    if match:
        ord_str = match.group(1).lower()
        index = _ORDINAL_MAP.get(ord_str, 1)
        raw_type = match.group(2).lower()
        if "video" in raw_type:
            item_type = "video"
        elif "option" in raw_type:
            item_type = "option"
        else:
            item_type = "result"
    elif re.search(r"\bsecond\b", clean, re.I):
        index = 2
    elif re.search(r"\bthird\b", clean, re.I):
        index = 3

    # If context has search query e.g. "ElectroBOOM", propagate it
    query = ctx.last_search_query or ""
    # Check if user mentioned query in the utterance e.g. "on the ElectroBoom page"
    q_match = re.search(r"(?:on|for)\s+(?:the\s+)?([a-zA-Z0-9_\-\s]+?)(?:\s+page|\s+results?)?$", clean, re.I)
    if q_match:
        extracted = q_match.group(1).strip()
        if extracted and extracted.lower() not in ("youtube", "browser", "result", "page", "firefox", "chrome"):
            query = extracted

    return {
        "item_type": item_type,
        "index": index,
        "query": query,
        "browser_name": ctx.active_browser_name or "Firefox",
        "has_active_session": ctx.has_active_session(),
    }


_global_context = BrowserTaskContext()


def get_browser_task_context() -> BrowserTaskContext:
    """Return singleton BrowserTaskContext instance."""
    return _global_context


def set_browser_task_context(ctx: BrowserTaskContext) -> None:
    """Set singleton BrowserTaskContext instance (useful for testing)."""
    global _global_context
    _global_context = ctx

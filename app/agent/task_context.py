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
    active_tab_count: int = 0
    last_observed_state: dict[str, Any] = field(default_factory=dict)
    last_inspected_elements: list[Any] = field(default_factory=list)
    last_inspection_time: float = 0.0
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

    def update_inspection(self, elements: list[Any], url: str = "", title: str = "") -> None:
        """Cache inspected elements and update page state."""
        self.last_inspected_elements = elements
        self.last_inspection_time = time.time()
        if url:
            self.current_url = url
        if title:
            self.current_title = title
        self.updated_at = time.time()

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
        self.active_browser_name = self.active_browser_name or "Firefox"
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
        self.active_tab_count = 0
        self.last_observed_state.clear()
        self.last_inspected_elements.clear()
        self.last_inspection_time = 0.0
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
    r"(video|result|search\s+result|option|item|one|link)"
    r"(?:\s+(?:that\s+comes\s+in\s+the\s+result|in\s+the\s+results?|on\s+the\s+page|in\s+the\s+browser|on\s+youtube))?",
    re.I
)

_PRONOUN_REF_PATTERN = re.compile(
    r"^(?:just\s+|please\s+)?(?:open|play|click(?:\s+on)?|select)\s+(?:it|that\s+video|that\s+result|that\s+page|that\s+one)[.!?]?$",
    re.I
)


def is_browser_result_reference(text: str) -> bool:
    """Check if utterance refers to a browser result, video, or page element."""
    clean = text.strip()
    # If the user is referring to a specific sidebar/recommendation section, let interaction/resolver handle it
    if re.search(r"\b(?:sidebar|recommendations?|related\s+videos?|right(?:\s+hand)?\s+side)\b", clean, re.I):
        return False
    # If the user specifies an explicit title (e.g. "video featuring the title ..."), use semantic element resolution
    if re.search(r"\b(?:featuring\s+(?:the\s+)?title|with\s+(?:the\s+)?title|titled|called|named)\b", clean, re.I):
        return False
    if _BROWSER_REF_PATTERN.search(clean):
        return True
    if _PRONOUN_REF_PATTERN.search(clean):
        return True
    # "just click the first video", "click on the first video", "play the first video", "open the first video that comes in the result"
    if re.search(
        r"\b(?:just\s+|please\s+)?(?:open|play|click(?:\s+on)?|select)\s+(?:the\s+)?(?:first|second|third|fourth|fifth|1st|2nd|3rd|4th|5th)\s*(?:video|result|option|item|one|link)?\b",
        clean,
        re.I,
    ):
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
    elif re.search(r"\b(?:first|1st)\b", clean, re.I):
        index = 1
    elif re.search(r"\b(?:second|2nd)\b", clean, re.I):
        index = 2
    elif re.search(r"\b(?:third|3rd)\b", clean, re.I):
        index = 3
    elif re.search(r"\b(?:fourth|4th)\b", clean, re.I):
        index = 4
    elif re.search(r"\b(?:fifth|5th)\b", clean, re.I):
        index = 5

    # If context has search query e.g. "ElectroBOOM", propagate it
    query = ctx.last_search_query or ""

    # Do not treat "on" in "click on / tap on / press on" as a query preposition
    clean_no_verb = re.sub(r"\b(?:click|tap|press)\s+on\b", "", clean, flags=re.I)
    # Check if user mentioned a query or target in the utterance e.g. "for ElectroBOOM" or "on the ElectroBOOM page"
    q_match = re.search(r"(?:on|for)\s+(?:the\s+)?([a-zA-Z0-9_\-\s]+?)(?:\s+page|\s+results?)?$", clean_no_verb, re.I)
    if q_match:
        extracted = q_match.group(1).strip()
        generic_tokens = {
            "first", "second", "third", "fourth", "fifth", "1st", "2nd", "3rd", "4th", "5th",
            "video", "videos", "result", "results", "option", "options", "item", "items", "one",
            "page", "browser", "youtube", "firefox", "chrome", "screen", "link",
        }
        tokens = set(extracted.lower().split())
        # Only accept if not composed of ordinal or generic tokens
        if extracted and not tokens.issubset(generic_tokens) and not any(o in tokens for o in ("first", "second", "third", "1st", "2nd", "3rd")):
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


def _is_navigation_or_new_tab_request(text: str) -> bool:
    """Return True if utterance is requesting a new tab or navigating to a website/domain."""
    clean = text.strip()
    low = clean.lower()
    if re.search(r"\bnew\s+(?:browser\s+)?tab\b", low):
        return True
    nav_m = re.match(
        r"^(?:please\s+|just\s+)?(?:open|navigate\s+to|go\s+to|visit)\s+(.+?)[.!?]?$",
        clean,
        re.I,
    )
    if nav_m:
        cand = nav_m.group(1).strip()
        if re.search(r"\b(?:and|then)\b", cand, re.I):
            return False
        # Exclude in-page UI element phrases like "open the settings menu" or "open the third problem"
        if not re.search(r"\b(?:menu|button|icon|section|accordion|problem|video|dropdown|modal|dialog)\b", cand, re.I):
            try:
                from app.tools.browser.domain_aliases import normalize_domain_url
                norm_url, was_alias = normalize_domain_url(cand)
                if was_alias or norm_url.startswith("http://") or norm_url.startswith("https://"):
                    return True
            except Exception:
                pass
            if re.match(r"^[a-zA-Z0-9_\-]+(?:\.[a-zA-Z0-9_\-]+)+(/.*)?$", cand):
                return True
    return False


def is_browser_interaction_command(text: str, context: Optional[BrowserTaskContext] = None) -> bool:
    """Check if utterance refers to an interaction on the active webpage."""
    ctx = context or get_browser_task_context()
    if not ctx.has_active_session():
        return False

    clean = text.strip()
    low = clean.lower()

    # Never hijack new-tab or explicit domain navigation commands
    if _is_navigation_or_new_tab_request(clean):
        return False

    # Compound multi-step requests starting with open/launch/start/run or containing and/then are not simple in-page clicks
    if re.search(r"^(?:open|launch|start|run)\s+.*?\s+(?:and|then)\b", low):
        return False
    if re.search(r"\b(?:and|then)\s+(?:subscribe|like|dislike|search|run|execute|open|launch|navigate|go\s+to|type)\b", low):
        return False

    # In-page search on active session
    if re.search(r"^(?:please\s+|just\s+)?(?:search(?:\s+for)?|look\s+up)\s+(.+)$", low):
        return True

    # 1. Like / Subscribe / Dislike / Share / Toggles (including "click on the like button", "click share button on the same screen")
    if re.search(
        r"^(?:please\s+|just\s+)?(?:(?:click|tap|press|hit)(?:\s+on)?\s+(?:the\s+)?)?"
        r"(?:share|like|unlike|thumbs[\s\-]+up|thumbs[\s\-]+down|dislike)"
        r"(?:\s+(?:this|the)\s+(?:video|page|song|track)|\s+it|\s+button|\s+icon)"
        r"*(?:\s+on\s+(?:the\s+|this\s+)?(?:same\s+)?(?:screen|page))?[.!?]?$",
        low,
    ):
        return True
    if re.search(
        r"^(?:please\s+|just\s+)?(?:(?:click|tap|press|hit)(?:\s+on)?\s+(?:the\s+)?)?"
        r"(?:subscribe|unsubscribe)"
        r"(?:\s+(?:to|from)\s+(?:this\s+|the\s+)?channel|\s+button|\s+icon)"
        r"*(?:\s+on\s+(?:the\s+|this\s+)?(?:same\s+)?(?:screen|page))?[.!?]?$",
        low,
    ):
        return True

    # 2. Expand / Collapse
    if re.search(r"^(?:please\s+|just\s+)?(?:expand|collapse|uncollapse)\b", low):
        return True

    # 3. Sidebar / Right-side / Titled video on page
    if re.search(
        r"\b(?:on\s+the\s+right(?:\s+hand)?\s+side|in\s+the\s+(?:right\s+)?sidebar|in\s+(?:the\s+)?recommendations?|"
        r"video\s+(?:featuring\s+(?:the\s+)?title|with\s+(?:the\s+)?title|titled|called|named))\b",
        low,
    ):
        return True

    # 4. Contextual icon / button click ("Click the LeetCode icon beside Two Sum", "Click the LeetCode icon beside this problem")
    if re.search(r"\b(?:click(?:\s+on)?)\s+(?:the\s+)?(?:[a-zA-Z0-9_\-\s]+?)\s+(?:beside|next\s+to|under)\s+(.+)", low):
        return True
    if re.search(r"\b(?:click(?:\s+on)?|open)\s+(?:the\s+)?(?:icon|link|button)\s+(?:beside|next\s+to|for|in|under)\s+(.+)", low):
        return True

    # 5. Ordinal element click ("Open the third problem in this section", "Click the 2nd problem", "Open the second video in the recommendations")
    if re.search(r"\b(?:open|click(?:\s+on)?|select|play)\s+(?:the\s+)?(?:first|second|third|fourth|fifth|1st|2nd|3rd|4th|5th)\s+(?:problem|row|card|item|accordion|section|video)\b", low):
        return True

    # 6. Direct element click ("Open the Settings menu", "Click Settings", "Open Binary Search")
    if re.search(r"^(?:please\s+|just\s+)?(?:click(?:\s+on)?|tap(?:\s+on)?|press(?:\s+on)?|open|select|play)\s+(?:the\s+)?([a-zA-Z0-9_\-\s\"'\.]+?)(?:\s+button|\s+link|\s+menu|\s+tab|\s+icon|\s+option)?(?:\s+on\s+(?:the\s+|this\s+)?(?:same\s+)?(?:screen|page))?[.!?]?$", low):
        if any(kw in low for kw in ("menu", "tab", "button", "link", "icon", "section", "problem", "settings", "search", "like", "dislike", "subscribe", "share", "video")):
            return True
        if ctx.last_inspected_elements:
            t_low = re.sub(r"^(?:please\s+|just\s+)?(?:click(?:\s+on)?|tap(?:\s+on)?|press(?:\s+on)?|open|select|play)\s+(?:the\s+)?", "", low).strip()
            for el in ctx.last_inspected_elements:
                name = getattr(el, "accessible_name", "") or (el.get("accessible_name", "") if isinstance(el, dict) else "")
                if t_low and t_low in name.lower():
                    return True
        if re.search(r"^(?:open|click(?:\s+on)?)\s+(?:binary\s+search|[a-zA-Z0-9_\-\s]+)$", low) and not any(app in low for app in ("firefox", "chrome", "kitty", "terminal", "burp", "code")):
            return True

    # 7. Select option
    if re.search(r"^(?:please\s+|just\s+)?(?:select|choose)\s+([a-zA-Z0-9_\-\s]+?)(?:\s+(?:from\s+(?:the\s+)?dropdown|option))?$", low):
        return True

    # 8. Scroll
    if re.search(r"^(?:please\s+|just\s+)?scroll\s+(down|up|to\s+top|to\s+bottom)", low):
        return True

    # 9. Fill input
    if re.search(r"^(?:please\s+|just\s+)?(?:type|fill|enter|input)\s+.*?\s+(?:in|into|for)\s+", low):
        return True

    return False


def parse_browser_interaction(text: str, context: Optional[BrowserTaskContext] = None) -> dict[str, Any]:
    """Parse tool name and arguments from a general browser interaction utterance."""
    clean = text.strip()
    low = clean.lower()

    # Search on active page
    search_m = re.search(r"^(?:please\s+|just\s+)?(?:search(?:\s+for)?|look\s+up)\s+(.+?)(?:\s+(?:on|in)\s+(?:this\s+page|youtube|google))?[.!?]?$", clean, re.I)
    if search_m:
        query = search_m.group(1).strip()
        query = re.sub(r"^for\s+", "", query, flags=re.I).strip()
        return {"tool_name": "browser_search_page", "tool_args": {"query": query}}

    # 1. Like / Dislike / Share / Subscribe (only when not describing a video title)
    is_titled_video_query = bool(
        re.search(r"\b(?:featuring\s+(?:the\s+)?title|with\s+(?:the\s+)?title|titled|called|named)\b", low)
    )
    if not is_titled_video_query:
        if re.search(r"\b(?:dislike|thumbs[\s\-]+down)\b", low):
            return {"tool_name": "browser_click_element", "tool_args": {"target": "dislike", "context": ""}}
        if re.search(r"\b(?:unlike)\b", low):
            return {"tool_name": "browser_click_element", "tool_args": {"target": "unlike", "context": ""}}
        if re.search(r"\b(?:like|thumbs[\s\-]+up)\b", low):
            return {"tool_name": "browser_click_element", "tool_args": {"target": "like", "context": ""}}
        if re.search(r"\b(?:share)\b", low):
            return {"tool_name": "browser_click_element", "tool_args": {"target": "share", "context": ""}}
        if re.search(r"\b(?:unsubscribe)\b", low):
            return {"tool_name": "browser_click_element", "tool_args": {"target": "unsubscribe", "context": ""}}
        if re.search(r"\b(?:subscribe)\b", low):
            return {"tool_name": "browser_click_element", "tool_args": {"target": "subscribe", "context": ""}}

    # 2. Expand / Collapse
    expand_m = re.search(r"^(?:please\s+|just\s+)?(expand|collapse|uncollapse)\s+(?:the\s+)?(.+?)(?:\s+section|\s+list|\s+accordion)?$", clean, re.I)
    if expand_m:
        action = expand_m.group(1).lower()
        target = expand_m.group(2).strip()
        collapse = action == "collapse"
        return {"tool_name": "browser_expand", "tool_args": {"target": target, "collapse": collapse}}

    # 3. Scroll
    scroll_m = re.search(r"^(?:please\s+|just\s+)?scroll\s+(down|up|to\s+top|to\s+bottom)(?:\s+to\s+(?:the\s+)?(.+))?$", clean, re.I)
    if scroll_m:
        direction = scroll_m.group(1).lower()
        target = (scroll_m.group(2) or "").strip()
        if "top" in direction:
            direction = "top"
        elif "bottom" in direction:
            direction = "bottom"
        return {"tool_name": "browser_scroll", "tool_args": {"direction": direction, "target": target}}

    # 4. Fill input
    fill_m = re.search(r"^(?:please\s+|just\s+)?(?:type|fill|enter|input)\s+[\"']?([^\"']+)[\"']?\s+(?:in|into|for)\s+(?:the\s+)?(.+)$", clean, re.I)
    if fill_m:
        value = fill_m.group(1).strip()
        target = fill_m.group(2).strip()
        return {"tool_name": "browser_fill_input", "tool_args": {"target": target, "value": value}}

    # 5. Select dropdown option
    select_m = re.search(r"^(?:please\s+|just\s+)?(?:select|choose)\s+(?:the\s+)?([a-zA-Z0-9_\-\s]+?)(?:\s+(?:from\s+(?:the\s+)?dropdown|option))?$", clean, re.I)
    if select_m and not re.search(r"\b(?:first|second|third|fourth|fifth|1st|2nd|3rd|4th|5th|problem|row|card|video)\b", low):
        option = select_m.group(1).strip()
        return {"tool_name": "browser_select_option", "tool_args": {"target": option, "option": option}}

    # 6. Sidebar / Right-side / Titled video extraction
    has_sidebar_hint = bool(
        re.search(r"\b(?:right(?:\s+hand)?\s+side|sidebar|recommendations?|related\s+videos?|up\s+next)\b", low)
    )
    title_m = re.search(
        r"(?:video\s+)?(?:featuring\s+(?:the\s+)?title|with\s+(?:the\s+)?title|titled|called|named)\s+[\"']?(.+?)[\"']?(?:\s+on\s+the\s+right.*|\s+in\s+the\s+sidebar.*)?[.!?]?$",
        clean,
        re.I,
    )
    if title_m:
        extracted_title = title_m.group(1).strip().strip(" \"'")
        extracted_title = re.sub(r"(?:\s*\.{2,}|\s*…)+$", "", extracted_title).strip(" \"'")
        return {
            "tool_name": "browser_click_element",
            "tool_args": {
                "target": extracted_title,
                "context": "Sidebar" if has_sidebar_hint else "",
            },
        }

    # 7. Ordinal element ("Open the third problem in this section", "Open the second video in the recommendations")
    ord_m = re.search(
        r"^(?:please\s+|just\s+)?(?:open|click(?:\s+on)?|select|play)\s+(?:the\s+)?(first|second|third|fourth|fifth|1st|2nd|3rd|4th|5th)\s+([a-zA-Z0-9_\-\s]+?)(?:\s+in\s+(?:this\s+|the\s+)?(.+?)(?:\s+section|\s+list|\s+row)?)?[.!?]?$",
        clean,
        re.I,
    )
    if ord_m:
        ord_word = ord_m.group(1).lower()
        ord_idx = _ORDINAL_MAP.get(ord_word, 1)
        target = ord_m.group(2).strip()
        ctx_scope = (ord_m.group(3) or "").strip()
        return {
            "tool_name": "browser_click_element",
            "tool_args": {"target": target, "context": ctx_scope, "ordinal": ord_idx},
        }

    # 8. Contextual Click ("Click the LeetCode icon beside Two Sum", "Click the LeetCode icon beside this problem")
    beside_m = re.search(
        r"^(?:please\s+|just\s+)?(?:click(?:\s+on)?|open|select)\s+(?:the\s+)?(.+?)\s+(?:beside|next\s+to|for|in|under)\s+(?:the\s+)?(.+?)(?:\s+section|\s+row|\s+card|\s+problem)?[.!?]?$",
        clean,
        re.I,
    )
    if beside_m:
        target = beside_m.group(1).strip()
        context_target = beside_m.group(2).strip()
        if context_target.lower() not in ("same screen", "this screen", "the screen", "the page", "this page"):
            return {
                "tool_name": "browser_click_element",
                "tool_args": {"target": target, "context": context_target},
            }

    # 9. General Click
    clean_target = re.sub(
        r"^(?:please\s+|just\s+)?(?:click(?:\s+on)?|tap(?:\s+on)?|press(?:\s+on)?|open|select|play)\s+(?:the\s+)?",
        "",
        clean,
        flags=re.I,
    ).strip()
    clean_target = re.sub(r"\s+on\s+(?:the\s+|this\s+)?(?:same\s+)?(?:screen|page)[.!?]?$", "", clean_target, flags=re.I).strip()
    return {
        "tool_name": "browser_click_element",
        "tool_args": {
            "target": clean_target,
            "context": "Sidebar" if has_sidebar_hint else "",
        },
    }
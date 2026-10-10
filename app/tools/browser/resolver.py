"""Semantic element resolution and ambiguity handling for browser interactions."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Optional

import structlog

logger = structlog.get_logger(__name__)


@dataclass
class InspectedElement:
    """Structured representation of an actionable element discovered during inspection."""
    ref_id: str                      # e.g., "@e1", "@e2"
    index: int                       # 1-based index
    tag: str                         # "button", "a", "input", "summary", etc.
    role: str                        # "button", "link", "tab", "menuitem", etc.
    accessible_name: str             # accessible name / label / title / text
    visible_text: str                # visible text
    selector: str                    # stable selector
    element_type: str                # "button", "link", "input", "select", "accordion", "toggle"
    href: str = ""                   # link destination
    input_type: str = ""             # "text", "search", etc.
    placeholder: str = ""
    value: str = ""
    expanded: Optional[bool] = None  # True / False if expandable, None otherwise
    pressed: Optional[bool] = None   # True / False if toggle button
    checked: Optional[bool] = None   # True / False if checkable
    selected: Optional[bool] = None
    disabled: bool = False
    is_icon: bool = False
    icon_name: str = ""              # e.g. "leetcode", "youtube", "github", "settings", "chevron"
    parent_section: str = ""         # container or section title, e.g. "Arrays", "Two Sum"
    container_type: str = ""         # "row", "card", "section", "table", "nav"
    classes: list[str] = field(default_factory=list)
    attributes: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ref_id": self.ref_id,
            "index": self.index,
            "tag": self.tag,
            "role": self.role,
            "accessible_name": self.accessible_name,
            "visible_text": self.visible_text,
            "element_type": self.element_type,
            "href": self.href,
            "placeholder": self.placeholder,
            "expanded": self.expanded,
            "pressed": self.pressed,
            "checked": self.checked,
            "disabled": self.disabled,
            "is_icon": self.is_icon,
            "icon_name": self.icon_name,
            "parent_section": self.parent_section,
            "container_type": self.container_type,
            "selector": self.selector,
        }


@dataclass
class ResolutionResult:
    """Outcome of resolving a natural language target against page elements."""
    status: str                                  # "found", "already_in_state", "ambiguous", "not_found"
    element: Optional[InspectedElement] = None
    candidates: list[InspectedElement] = field(default_factory=list)
    confidence: float = 0.0
    action_intent: str = "click"                 # "click", "expand", "collapse", "like", "subscribe", etc.
    already_in_state: bool = False
    message: str = ""


_ORDINAL_WORDS = {
    "first": 1, "1st": 1, "one": 1,
    "second": 2, "2nd": 2, "two": 2,
    "third": 3, "3rd": 3, "three": 3,
    "fourth": 4, "4th": 4, "four": 4,
    "fifth": 5, "5th": 5, "five": 5,
    "sixth": 6, "6th": 6, "six": 6,
    "seventh": 7, "7th": 7, "seven": 7,
    "eighth": 8, "8th": 8, "eight": 8,
    "ninth": 9, "9th": 9, "nine": 9,
    "tenth": 10, "10th": 10, "ten": 10,
}


class ElementResolver:
    """Resolves natural language element targets against structured inspected elements."""

    @classmethod
    def parse_query(
        cls,
        target: str,
        context: str = "",
        ordinal: int = 0,
        default_intent: str = "click",
    ) -> tuple[str, str, int, str]:
        """Parse raw user query into (clean_target, context, ordinal, intent)."""
        clean_target = target.strip()
        extracted_context = context.strip()
        extracted_ordinal = ordinal
        intent = default_intent

        # 1. Detect explicit action intent
        low = clean_target.lower()
        if re.match(r"^(?:expand|open\s+(?:the\s+)?accordion|uncollapse)\b", low):
            intent = "expand"
            clean_target = re.sub(r"^(?:expand|open\s+(?:the\s+)?accordion|uncollapse)\s+", "", clean_target, flags=re.I).strip()
        elif re.match(r"^(?:collapse|close\s+(?:the\s+)?accordion)\b", low):
            intent = "collapse"
            clean_target = re.sub(r"^(?:collapse|close\s+(?:the\s+)?accordion)\s+", "", clean_target, flags=re.I).strip()
        elif re.match(r"^(?:dislike|thumbs\s+down)\b", low):
            intent = "dislike"
        elif re.match(r"^(?:like|thumbs\s+up)\b", low):
            intent = "like"
        elif re.match(r"^(?:unlike|remove\s+like)\b", low):
            intent = "unlike"
        elif re.match(r"^(?:subscribe)\b", low):
            intent = "subscribe"
        elif re.match(r"^(?:unsubscribe)\b", low):
            intent = "unsubscribe"
        elif re.match(r"^(?:share)\b", low):
            intent = "share"

        # 2. Extract ordinal if present (e.g. "third problem", "the 2nd item")
        ord_match = re.search(
            r"\b(?:the\s+)?(first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth|1st|2nd|3rd|4th|5th|6th|7th|8th|9th|10th)\b",
            clean_target,
            re.I,
        )
        if ord_match and extracted_ordinal <= 0:
            word = ord_match.group(1).lower()
            extracted_ordinal = _ORDINAL_WORDS.get(word, 0)
            # Remove the ordinal word from the target
            clean_target = re.sub(rf"\b(?:the\s+)?{word}\s*", "", clean_target, flags=re.I).strip()

        # 3. Extract contextual scoping phrases:
        # "LeetCode icon beside Two Sum", "icon beside Two Sum", "icon for Two Sum"
        beside_match = re.search(
            r"^(.*?)\s+(?:beside|next\s+to|for|of|in|under)\s+(?:the\s+)?([a-zA-Z0-9_\-\s]+?)(?:\s+section|\s+row|\s+card|\s+problem)?$",
            clean_target,
            re.I,
        )
        if beside_match and not extracted_context:
            sub_target = beside_match.group(1).strip()
            sub_context = beside_match.group(2).strip()
            # Verify sub_context isn't just a generic word
            if sub_context.lower() not in ("current", "active", "this", "page", "browser", "it"):
                clean_target = sub_target
                extracted_context = sub_context

        # 4. Remove common noise words: "button", "icon", "link", "section" if target is more specific
        clean_target = re.sub(r"\b(?:please|just|click|tap|open|select)\b", "", clean_target, flags=re.I).strip()
        if clean_target.lower().startswith("the "):
            clean_target = clean_target[4:].strip()

        words = clean_target.split()
        if len(words) > 1:
            filtered = [w for w in words if w.lower() not in ("button", "btn", "icon", "link")]
            if filtered:
                clean_target = " ".join(filtered)

        # 5. Clean target for like/subscribe/dislike/share
        if intent in ("like", "unlike"):
            clean_target = re.sub(r"\b(?:this\s+)?(?:video|it|song|track)\b", "", clean_target, flags=re.I).strip()
            if not clean_target:
                clean_target = "like"
        elif intent in ("dislike", "undislike"):
            clean_target = re.sub(r"\b(?:this\s+)?(?:video|it|song|track)\b", "", clean_target, flags=re.I).strip()
            if not clean_target:
                clean_target = "dislike"
        elif intent in ("subscribe", "unsubscribe"):
            clean_target = re.sub(r"\b(?:to\s+)?(?:this\s+)?(?:channel|creator|user)\b", "", clean_target, flags=re.I).strip()
            if not clean_target:
                clean_target = "subscribe"
        elif intent == "share":
            clean_target = re.sub(r"\b(?:this\s+)?(?:video|it|page)\b", "", clean_target, flags=re.I).strip()
            if not clean_target:
                clean_target = "share"
        elif intent in ("expand", "collapse"):
            clean_target = re.sub(r"\s+(?:section|accordion|menu|tab)$", "", clean_target, flags=re.I).strip()

        return clean_target, extracted_context, extracted_ordinal, intent

    @classmethod
    def resolve(
        cls,
        elements: list[InspectedElement],
        target: str,
        context: str = "",
        ordinal: int = 0,
        intent: str = "click",
        page_url: str = "",
        page_title: str = "",
    ) -> ResolutionResult:
        """Resolve target to a specific element using semantic attributes and hierarchy."""
        if not elements:
            return ResolutionResult(
                status="not_found",
                message="No actionable elements found on the current page to resolve.",
            )

        clean_target, ctx_scope, ord_idx, action_intent = cls.parse_query(target, context, ordinal, intent)
        logger.info(
            "element_resolution_start",
            raw_target=target,
            clean_target=clean_target,
            context=ctx_scope,
            ordinal=ord_idx,
            intent=action_intent,
        )

        # 1. Direct Ref ID match (e.g. "@e3" or integer index "3")
        ref_id_match = None
        if clean_target.startswith("@e") and clean_target[2:].isdigit():
            ref_id_match = clean_target.lower()
        elif clean_target.isdigit():
            idx = int(clean_target)
            if 1 <= idx <= len(elements):
                ref_id_match = f"@e{idx}"

        if ref_id_match:
            for el in elements:
                if el.ref_id.lower() == ref_id_match:
                    return ResolutionResult(
                        status="found",
                        element=el,
                        confidence=1.0,
                        action_intent=action_intent,
                        message=f"Matched element by reference ID {el.ref_id}: '{el.accessible_name}'.",
                    )

        # 2. Context Filtering / Scoping
        # If a container context was specified (e.g. "Two Sum", "Arrays"), filter or boost elements in that container
        candidate_pool = elements
        if ctx_scope:
            scoped = [
                el for el in elements
                if (ctx_scope.lower() in el.parent_section.lower() or
                    ctx_scope.lower() in el.visible_text.lower())
            ]
            # Only restrict to scoped pool if matching items were found
            if scoped:
                candidate_pool = scoped
                logger.info("element_resolution_context_scoped", context=ctx_scope, count=len(scoped))

        # 3. Score candidate elements
        scored: list[tuple[float, InspectedElement]] = []
        for el in candidate_pool:
            score = cls._score_element(
                el=el,
                target=clean_target,
                context=ctx_scope,
                intent=action_intent,
                page_url=page_url,
                page_title=page_title,
            )
            if score > 0.15:
                scored.append((score, el))

        if not scored:
            # If scoped pool had nothing, fall back to scoring all elements
            if candidate_pool is not elements:
                for el in elements:
                    score = cls._score_element(
                        el=el,
                        target=clean_target,
                        context=ctx_scope,
                        intent=action_intent,
                        page_url=page_url,
                        page_title=page_title,
                    )
                    if score > 0.15:
                        scored.append((score, el))

        if not scored:
            return ResolutionResult(
                status="not_found",
                message=f"Could not find any element matching '{target}' on the current page.",
            )

        # Sort descending by score
        scored.sort(key=lambda x: x[0], reverse=True)

        # 4. Handle Ordinal Selection
        if ord_idx > 0:
            # When an ordinal is requested (e.g. 3rd problem), select the N-th matching item
            # Filter candidates that share the top category/role or are close in score
            top_score = scored[0][0]
            qualifying = [el for s, el in scored if s >= top_score * 0.7]
            if 1 <= ord_idx <= len(qualifying):
                chosen = qualifying[ord_idx - 1]
                return ResolutionResult(
                    status="found",
                    element=chosen,
                    confidence=0.95,
                    action_intent=action_intent,
                    message=f"Selected ordinal item #{ord_idx}: '{chosen.accessible_name}'.",
                )
            else:
                return ResolutionResult(
                    status="not_found",
                    candidates=qualifying,
                    message=f"Requested index {ord_idx}, but only {len(qualifying)} matching items were found.",
                )

        # 5. Check State for Expand / Collapse & Toggles
        top_score, top_el = scored[0]

        # Expand request on an already expanded element
        if action_intent == "expand" and top_el.expanded is True:
            return ResolutionResult(
                status="already_in_state",
                element=top_el,
                confidence=top_score,
                action_intent=action_intent,
                already_in_state=True,
                message=f"Section '{top_el.accessible_name or clean_target}' is already expanded.",
            )

        # Collapse request on an already collapsed element
        if action_intent == "collapse" and top_el.expanded is False:
            return ResolutionResult(
                status="already_in_state",
                element=top_el,
                confidence=top_score,
                action_intent=action_intent,
                already_in_state=True,
                message=f"Section '{top_el.accessible_name or clean_target}' is already collapsed.",
            )

        # Like request on already liked
        if action_intent == "like" and top_el.pressed is True:
            return ResolutionResult(
                status="already_in_state",
                element=top_el,
                confidence=top_score,
                action_intent=action_intent,
                already_in_state=True,
                message="Video is already liked.",
            )

        # Dislike request on already disliked
        if action_intent == "dislike" and top_el.pressed is True:
            return ResolutionResult(
                status="already_in_state",
                element=top_el,
                confidence=top_score,
                action_intent=action_intent,
                already_in_state=True,
                message="Video is already disliked.",
            )

        # 6. Ambiguity Check
        # If top two candidates have very close scores and represent distinct actions without container context
        if len(scored) >= 2:
            second_score, second_el = scored[1]
            if (
                abs(top_score - second_score) < 0.08
                and top_el.accessible_name != second_el.accessible_name
                and not ctx_scope
            ):
                candidate_names = [f"'{s[1].accessible_name}' in {s[1].parent_section or 'page'}" for s in scored[:3]]
                return ResolutionResult(
                    status="ambiguous",
                    candidates=[s[1] for s in scored[:3]],
                    confidence=top_score,
                    action_intent=action_intent,
                    message=f"Multiple elements match '{clean_target}': {', '.join(candidate_names)}. Please specify which one you mean.",
                )

        # 7. Unambiguous Resolution
        if top_score >= 0.4:
            return ResolutionResult(
                status="found",
                element=top_el,
                confidence=top_score,
                action_intent=action_intent,
                message=f"Resolved '{target}' to {top_el.element_type} '{top_el.accessible_name}' ({top_el.ref_id}).",
            )

        return ResolutionResult(
            status="not_found",
            message=f"Could not find a confident match for '{target}' on the page (best match score: {top_score:.2f}).",
        )

    @classmethod
    def _score_element(
        cls,
        el: InspectedElement,
        target: str,
        context: str,
        intent: str,
        page_url: str,
        page_title: str,
    ) -> float:
        """Calculate a relevance score between 0.0 and 1.0 for an element."""
        score = 0.0
        t_low = target.lower().strip()
        name_low = el.accessible_name.lower().strip()
        text_low = el.visible_text.lower().strip()
        parent_low = el.parent_section.lower().strip()
        icon_low = el.icon_name.lower().strip()
        href_low = el.href.lower().strip()

        # A. Intent-Specific Bonuses & Penalties
        if intent in ("expand", "collapse"):
            # Target wants an accordion/disclosure/collapsible control
            if el.expanded is not None or el.tag == "summary" or "accordion" in el.element_type:
                score += 0.35
            elif el.role == "button" and any(k in name_low or k in icon_low for k in ("expand", "collapse", "chevron", "arrow", "toggle")):
                score += 0.35
            elif el.role == "link":
                # A problem link (e.g. "Arrays and Hashing") is NOT an expand button!
                score -= 0.40

        elif intent in ("like", "unlike"):
            if "dislike" in name_low or "dislike" in icon_low or "thumbs down" in name_low or "thumbs-down" in icon_low:
                return 0.0
            if re.search(r"\blike\b", name_low) or icon_low == "like" or "thumbs-up" in icon_low or "thumbs up" in name_low:
                score += 0.50

        elif intent in ("dislike", "undislike"):
            if not ("dislike" in name_low or "dislike" in icon_low or "thumbs down" in name_low or "thumbs-down" in icon_low):
                return 0.0
            score += 0.50

        elif intent == "share":
            if "share" in name_low or "share" in icon_low:
                score += 0.55

        elif intent in ("subscribe", "unsubscribe"):
            if "subscribe" in name_low or "subscribed" in name_low:
                score += 0.50

        elif intent == "fill":
            if el.element_type == "input" or el.tag in ("input", "textarea"):
                score += 0.35
            else:
                score -= 0.30

        elif intent == "select":
            if el.element_type == "select" or el.tag == "select" or el.role in ("combobox", "listbox", "option"):
                score += 0.35

        # Placeholder match
        ph_low = el.placeholder.lower().strip()
        if ph_low and (t_low == ph_low or t_low in ph_low):
            score += 0.40

        # B. Icon / Specific Service Match (e.g. "leetcode", "youtube", "github", "settings", "share")
        is_icon_target = any(k in t_low for k in ("icon", "logo", "leetcode", "github", "settings", "gear", "cog", "share"))
        if is_icon_target:
            for kw in ("leetcode", "github", "youtube", "settings", "search", "filter", "close", "menu", "share"):
                if kw in t_low:
                    if kw in icon_low or kw in href_low or kw in name_low:
                        score += 0.55
                    elif el.is_icon:
                        score += 0.20

        # C. Name and Text Matching
        if t_low:
            # Prevent "like" from matching inside "dislike"
            if t_low == "like" and ("dislike" in name_low or "dislike" in text_low):
                pass
            # Exact match on accessible name or visible text
            elif t_low == name_low or t_low == text_low:
                score += 0.50
            # Substring match (with whole-word check if target is 'like')
            elif (t_low in name_low and (t_low != "like" or re.search(r"\blike\b", name_low))) or (t_low in text_low and (t_low != "like" or re.search(r"\blike\b", text_low))):
                score += 0.35
            # Token overlap
            else:
                t_tokens = set(re.findall(r"\w+", t_low))
                name_tokens = set(re.findall(r"\w+", f"{name_low} {text_low} {icon_low}"))
                if t_tokens and name_tokens:
                    overlap = len(t_tokens.intersection(name_tokens)) / len(t_tokens)
                    score += overlap * 0.35

        # D. Context Match (Container / Section / Row)
        if context:
            c_low = context.lower()
            if c_low == parent_low or c_low in parent_low:
                score += 0.35
            elif c_low in f"{name_low} {text_low}":
                score += 0.20

        # E. Element State & Usability
        if el.disabled:
            score -= 0.30

        return max(0.0, min(1.0, score))

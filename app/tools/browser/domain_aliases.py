"""Domain alias normalization for speech recognition variants.

Only known, high-confidence speech-recognition variants of well-known domains
are corrected using an explicit allowlist. Arbitrary domains are never rewritten.
"""
from __future__ import annotations

import re

# Explicit allowlist of known domain variants from real voice logs
KNOWN_DOMAIN_ALIASES: dict[str, str] = {
    # LeetCode variants (common STT mishearings)
    "leadcode.com": "leetcode.com",
    "leadcode": "leetcode.com",
    "lead code": "leetcode.com",
    "leet code": "leetcode.com",
    "leet code.com": "leetcode.com",
    "lead code.com": "leetcode.com",
    "leet code com": "leetcode.com",
    "lead code com": "leetcode.com",
    "leetcode com": "leetcode.com",
    "leadcode com": "leetcode.com",
    "leet-code": "leetcode.com",
    "leet-code.com": "leetcode.com",
    "leetcode": "leetcode.com",
    "leetcode.com": "leetcode.com",

    # YouTube variants
    "you tube": "youtube.com",
    "you tube.com": "youtube.com",
    "you tube com": "youtube.com",
    "youtube com": "youtube.com",
    "youtub": "youtube.com",
    "youtub.com": "youtube.com",
    "youtube": "youtube.com",
    "youtube.com": "youtube.com",

    # GitHub variants
    "git hub": "github.com",
    "git hub.com": "github.com",
    "git hub com": "github.com",
    "github com": "github.com",
    "gitup": "github.com",
    "gitup.com": "github.com",
    "github": "github.com",
    "github.com": "github.com",

    # Google variants
    "google": "google.com",
    "google com": "google.com",
    "googl.com": "google.com",
    "google.com": "google.com",

    # DuckDuckGo variants
    "duck duck go": "duckduckgo.com",
    "duck duck go.com": "duckduckgo.com",
    "duckduckgo": "duckduckgo.com",
    "duckduckgo.com": "duckduckgo.com",

    # Wikipedia variants
    "wiki pedia": "wikipedia.org",
    "wikepedia": "wikipedia.org",
    "wikipedia": "wikipedia.org",
    "wikipedia.org": "wikipedia.org",
}


def normalize_domain_url(raw_input: str) -> tuple[str, bool]:
    """Normalize a spoken domain or URL using the explicit allowlist.

    Returns:
        (normalized_url, was_corrected)
    """
    if not raw_input:
        return "", False

    clean = raw_input.strip()

    # Strip accidental trailing/leading "in a new tab" phrases if passed in raw URL string
    clean = re.sub(
        r"^(?:(?:in|on|into)\s+(?:a\s+|the\s+|another\s+)?new\s+(?:browser\s+)?tab,?\s*(?:please\s+|just\s+)?(?:open|go\s+to|navigate\s+to|visit)?\s*)|"
        r"(?:\s+(?:in|on|into)\s+(?:a\s+|the\s+|another\s+)?new\s+(?:browser\s+)?tab.*)$",
        "",
        clean,
        flags=re.I,
    ).strip()

    # Strip leading polite words and action verbs ("please open", "navigate to", "go to")
    clean = re.sub(
        r"^(?:please\s+|just\s+)*(?:open\s+up|open|navigate\s+to|go\s+to|visit|launch)\s+",
        "",
        clean,
        flags=re.I,
    ).strip()

    # Strip leading articles/nouns like "the website leetcode.com" or "to leetcode.com"
    clean = re.sub(
        r"^(?:to|at|the\s+website|the\s+site|the\s+page|the\s+url|website|site|url|the)\s+",
        "",
        clean,
        flags=re.I,
    ).strip()

    # Strip trailing filler like "in the browser" or "for me"
    clean = re.sub(
        r"\s+(?:in\s+(?:the\s+|my\s+)?browser|for\s+me)$",
        "",
        clean,
        flags=re.I,
    ).strip()

    # Strip surrounding quotes or trailing sentence punctuation
    clean = re.sub(r"^[\"']+|[\"'.?!,;]+$", "", clean).strip()
    low = clean.lower()

    # Handle explicit http/https URLs whose hostname may be a spoken alias
    if low.startswith("http://") or low.startswith("https://"):
        scheme, rest = clean.split("://", 1)
        parts = rest.split("/", 1)
        host_low = parts[0].lower().strip()
        if host_low.startswith("www."):
            host_low_no_www = host_low[4:]
        else:
            host_low_no_www = host_low
        path = f"/{parts[1]}" if len(parts) > 1 else ""
        if host_low in KNOWN_DOMAIN_ALIASES:
            corrected_host = KNOWN_DOMAIN_ALIASES[host_low]
            was_changed = corrected_host != host_low
            return f"https://{corrected_host}{path}", was_changed
        if host_low_no_www in KNOWN_DOMAIN_ALIASES:
            corrected_host = KNOWN_DOMAIN_ALIASES[host_low_no_www]
            was_changed = corrected_host != host_low_no_www
            return f"https://{corrected_host}{path}", was_changed
        return clean, False

    low_no_www = low[4:] if low.startswith("www.") else low

    # Check explicit allowlist first
    if low in KNOWN_DOMAIN_ALIASES:
        corrected = KNOWN_DOMAIN_ALIASES[low]
        url = f"https://{corrected}" if not corrected.startswith("http") else corrected
        return url, True
    if low_no_www in KNOWN_DOMAIN_ALIASES:
        corrected = KNOWN_DOMAIN_ALIASES[low_no_www]
        url = f"https://{corrected}" if not corrected.startswith("http") else corrected
        return url, True

    # Check if the host part matches an alias (e.g. "leadcode.com/problemset")
    parts = low_no_www.split("/", 1)
    host = parts[0].strip()
    path = f"/{parts[1]}" if len(parts) > 1 else ""

    if host in KNOWN_DOMAIN_ALIASES:
        corrected_host = KNOWN_DOMAIN_ALIASES[host]
        return f"https://{corrected_host}{path}", True

    # If clean resembles a domain (e.g. example.com or sub.example.co.uk)
    if re.match(r"^[a-zA-Z0-9_\-]+(?:\.[a-zA-Z0-9_\-]+)+(/.*)?$", clean):
        return f"https://{clean}", False

    # Default fallback
    return clean, False
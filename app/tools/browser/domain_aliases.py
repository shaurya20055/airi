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
    "leetcode": "leetcode.com",

    # YouTube variants
    "you tube": "youtube.com",
    "you tube.com": "youtube.com",
    "youtub": "youtube.com",
    "youtub.com": "youtube.com",
    "youtube": "youtube.com",

    # GitHub variants
    "git hub": "github.com",
    "git hub.com": "github.com",
    "gitup": "github.com",
    "gitup.com": "github.com",
    "github": "github.com",

    # Google variants
    "google": "google.com",
    "googl.com": "google.com",

    # DuckDuckGo variants
    "duck duck go": "duckduckgo.com",
    "duckduckgo": "duckduckgo.com",

    # Wikipedia variants
    "wiki pedia": "wikipedia.org",
    "wikepedia": "wikipedia.org",
    "wikipedia": "wikipedia.org",
}


def normalize_domain_url(raw_input: str) -> tuple[str, bool]:
    """Normalize a spoken domain or URL using the explicit allowlist.

    Returns:
        (normalized_url, was_corrected)
    """
    clean = raw_input.strip()
    low = clean.lower()

    # Strip surrounding quotes or punctuation
    low = re.sub(r"^[\"']|[\"'.?!]$", "", low).strip()

    # Check explicit allowlist first
    if low in KNOWN_DOMAIN_ALIASES:
        corrected = KNOWN_DOMAIN_ALIASES[low]
        url = f"https://{corrected}" if not corrected.startswith("http") else corrected
        return url, True

    # If it's already a full URL or domain with protocol
    if clean.startswith("http://") or clean.startswith("https://"):
        return clean, False

    # Check if the host part matches an alias
    # e.g. "leadcode.com/problemset"
    parts = low.split("/", 1)
    host = parts[0]
    path = f"/{parts[1]}" if len(parts) > 1 else ""

    if host in KNOWN_DOMAIN_ALIASES:
        corrected_host = KNOWN_DOMAIN_ALIASES[host]
        return f"https://{corrected_host}{path}", True

    # If clean resembles a domain (e.g. example.com)
    if re.match(r"^[a-zA-Z0-9_\-]+\.[a-zA-Z]{2,}(/.*)?$", clean):
        return f"https://{clean}", False

    # Default fallback
    return clean, False

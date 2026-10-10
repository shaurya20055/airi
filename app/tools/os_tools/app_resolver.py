from __future__ import annotations
import difflib
import re
import shutil
from typing import NamedTuple
import structlog

from app.tools.os_tools.desktop_parser import DesktopParser, DesktopEntry

logger = structlog.get_logger(__name__)

CONFIDENCE_THRESHOLD = 0.65


def soundex(word: str) -> str:
    """Compute American Soundex for phonetic application name matching."""
    clean = re.sub(r'[^a-zA-Z]', '', word).upper()
    if not clean:
        return ""
    mapping = {
        'B': '1', 'F': '1', 'P': '1', 'V': '1',
        'C': '2', 'G': '2', 'J': '2', 'K': '2', 'Q': '2', 'S': '2', 'X': '2', 'Z': '2',
        'D': '3', 'T': '3',
        'L': '4',
        'M': '5', 'N': '5',
        'R': '6',
    }
    encoded = [clean[0]]
    prev_code = mapping.get(clean[0], '0')
    for char in clean[1:]:
        code = mapping.get(char, '0')
        if code != '0':
            if code != prev_code:
                encoded.append(code)
            prev_code = code
        else:
            prev_code = '0'
    return ("".join(encoded) + "0000")[:4]


class MatchResult(NamedTuple):
    entry: DesktopEntry | None
    confidence: float
    is_ambiguous: bool
    ambiguous_candidates: list[str]
    method: str
    candidates: list[DesktopEntry] = []
    requires_clarification: bool = False
    clarification_prompt: str = ""


class AppResolver:
    def __init__(self):
        self.parser = DesktopParser()
        self.entries: list[DesktopEntry] = []
        self._initialized = False

    def initialize(self, force: bool = False):
        if not self._initialized or force:
            self.entries = self.parser.discover_all(force_refresh=force)
            self._initialized = True

    def refresh(self):
        """Re-scan the desktop application catalog."""
        self.initialize(force=True)

    def _normalize(self, text: str) -> str:
        text = text.lower()
        # Remove common extraneous words and punctuation
        text = re.sub(r'[^\w\s]', ' ', text)
        text = re.sub(r'\b(launch|open|start|run|a|an|the)\b', ' ', text)
        return " ".join(text.split())

    def _is_category_only(self, text: str) -> bool:
        """Check if the user is just asking for a generic category."""
        categories = {"browser", "editor", "terminal", "player", "calculator", "file manager", "mail", "email"}
        return text in categories

    def _get_category_words(self) -> set[str]:
        return {"browser", "editor", "terminal", "player", "calculator", "mail"}

    def _score_entry(self, core_query: str, orig_query: str, entry: DesktopEntry) -> float:
        """Compute matching score between query and a catalog entry."""
        norm_name = entry.name.lower()
        if core_query == norm_name or orig_query.lower() == norm_name:
            return 1.0

        if entry.app_id and core_query == entry.app_id.lower():
            return 1.0

        q_tokens = [t.lower() for t in re.findall(r"\b\w+\b", core_query)]
        e_tokens = [t.lower() for t in re.findall(r"\b\w+\b", entry.name)]

        # Query is a word-aligned token (e.g. "chrome" in "Google Chrome")
        if len(q_tokens) == 1 and q_tokens[0] in e_tokens:
            return 0.92

        # Soundex full string comparison (e.g. "burpshoot" vs "burp suite", "firebox" vs "firefox")
        q_sx = soundex(core_query)
        e_sx = soundex(entry.name)
        sx_match = (q_sx == e_sx and len(q_sx) == 4)

        # Token-by-token phonetic similarity
        tok_sx_matches = 0
        if q_tokens and e_tokens:
            for qt in q_tokens:
                for et in e_tokens:
                    if soundex(qt) == soundex(et):
                        tok_sx_matches += 1
                        break
            tok_sx_ratio = tok_sx_matches / max(len(q_tokens), len(e_tokens))
        else:
            tok_sx_ratio = 0.0

        # Token overlap
        overlap = len(set(q_tokens) & set(e_tokens)) / max(len(q_tokens), len(e_tokens)) if e_tokens else 0.0

        # SequenceMatcher similarities
        name_ratio = difflib.SequenceMatcher(None, core_query, norm_name).ratio()
        app_id_ratio = difflib.SequenceMatcher(None, core_query, entry.app_id.lower()).ratio() if entry.app_id else 0.0

        exec_bin = entry.exec.split()[0].split('/')[-1].lower() if entry.exec else ""
        exec_ratio = difflib.SequenceMatcher(None, core_query, exec_bin).ratio() if exec_bin else 0.0

        # Generic name similarity
        generic_score = 0.0
        if entry.generic_name:
            if core_query in entry.generic_name.lower():
                generic_score = 0.8
            else:
                generic_score = difflib.SequenceMatcher(None, core_query, entry.generic_name.lower()).ratio() * 0.75

        # Keyword matching
        kw_score = 0.0
        if entry.keywords:
            low_keywords = [k.lower() for k in entry.keywords]
            if q_tokens and all(t in low_keywords for t in q_tokens):
                kw_score = 0.82
            elif q_tokens and any(t in low_keywords for t in q_tokens) and len(q_tokens) > 1:
                kw_score = 0.72

        phonetic_score = 0.0
        if sx_match:
            phonetic_score = max(phonetic_score, 0.88)
        if tok_sx_ratio > 0.5:
            phonetic_score = max(phonetic_score, tok_sx_ratio * 0.85)

        return max(
            name_ratio,
            app_id_ratio,
            exec_ratio,
            generic_score,
            kw_score,
            phonetic_score,
            overlap * 0.85,
        )

    def resolve(self, query: str) -> MatchResult:
        self.initialize()

        orig_query = query.strip()
        norm_query = self._normalize(query)

        if not norm_query:
            return MatchResult(None, 0.0, False, [], "empty", [], False, "")

        # 1. Category only check
        if self._is_category_only(norm_query):
            cat_candidates = [
                e for e in self.entries
                if norm_query in e.generic_name.lower() or norm_query in [k.lower() for k in e.keywords]
            ]
            cand_names = [e.name for e in cat_candidates] if cat_candidates else ["Specify which " + norm_query]
            return MatchResult(
                entry=None,
                confidence=0.0,
                is_ambiguous=True,
                ambiguous_candidates=cand_names,
                method="category_only",
                candidates=cat_candidates,
                requires_clarification=True,
                clarification_prompt=f"Please specify which {norm_query} you would like to open.",
            )

        # 2. Category word stripping: e.g. "helm browser" -> "helm", "chrome browser" -> "chrome"
        core_query = norm_query
        for cat in self._get_category_words():
            if norm_query.endswith(cat) and norm_query != cat:
                core_query = norm_query.replace(cat, "").strip()

        # 3. Exact canonical name match
        for entry in self.entries:
            if orig_query.lower() == entry.name.lower():
                logger.info("application_resolution_exact", query=orig_query, matched=entry.name, app_id=entry.app_id)
                return MatchResult(entry, 1.0, False, [], "exact", [entry], False, "")

        # 4. Exact alias / normalized match
        for entry in self.entries:
            if core_query == entry.name.lower() or (entry.app_id and core_query == entry.app_id.lower()):
                logger.info("application_resolution_exact", query=orig_query, matched=entry.name, app_id=entry.app_id)
                return MatchResult(entry, 1.0, False, [], "exact_normalized", [entry], False, "")

        # 5. Known ASR correction / Phonetic / Alias mappings
        ASR_MAPPINGS = {
            "helm": "helium",
            "helem": "helium",
            "helim": "helium",
            "helium": "helium",
            "helium browser": "helium",
            "helm browser": "helium",
            "helium rouse": "helium",
            "shillium": "helium",
            "chillium": "helium",
            "kilium": "helium",
            "krom": "chrome",
            "fox": "firefox",
            "fire fox": "firefox",
        }

        mapped_query = ASR_MAPPINGS.get(core_query, core_query)
        if mapped_query != core_query:
            for entry in self.entries:
                if mapped_query == entry.name.lower() or mapped_query in entry.name.lower():
                    logger.info("application_resolution_exact", query=orig_query, matched=entry.name, app_id=entry.app_id)
                    return MatchResult(entry, 0.95, False, [], "asr_correction", [entry], False, "")

        # 6. Rank plausible candidates in installed catalog
        scored_candidates: list[tuple[float, DesktopEntry]] = []
        seen_names = set()

        for entry in self.entries:
            if entry.name in seen_names:
                continue
            score = self._score_entry(core_query, orig_query, entry)
            if score >= CONFIDENCE_THRESHOLD:
                scored_candidates.append((score, entry))
                seen_names.add(entry.name)

        scored_candidates.sort(key=lambda x: x[0], reverse=True)

        if scored_candidates:
            top_score, top_entry = scored_candidates[0]
            candidate_entries = [c[1] for c in scored_candidates]
            logger.info(
                "application_resolution_candidates",
                query=orig_query,
                candidates=[c.name for c in candidate_entries],
                count=len(candidate_entries),
            )

            # Check if multiple candidates are close in score (within 0.12)
            if len(scored_candidates) > 1:
                second_score, second_entry = scored_candidates[1]
                if top_score - second_score < 0.12 and top_entry.name != second_entry.name:
                    top_candidates = candidate_entries[:3]
                    cand_names = [c.name for c in top_candidates]
                    return MatchResult(
                        entry=None,
                        confidence=top_score,
                        is_ambiguous=True,
                        ambiguous_candidates=cand_names,
                        method="fuzzy_ambiguous",
                        candidates=top_candidates,
                        requires_clarification=True,
                        clarification_prompt=f"Multiple applications match '{orig_query}': {', '.join(cand_names)}. Which one did you mean?",
                    )

            # Single prominent candidate: requires confirmation
            return MatchResult(
                entry=top_entry,
                confidence=top_score,
                is_ambiguous=False,
                ambiguous_candidates=[],
                method="candidate",
                candidates=[top_entry],
                requires_clarification=True,
                clarification_prompt=f"I couldn't find {orig_query}, but I found {top_entry.name}. Did you mean that?",
            )

        # 7. Fallback: PATH executable lookup
        path_bin = shutil.which(core_query)
        if path_bin:
            synthetic = DesktopEntry(
                path=path_bin,
                name=core_query,
                exec=path_bin,
                app_id=core_query,
            )
            logger.info("application_resolution_exact", query=orig_query, matched=core_query, app_id=core_query)
            return MatchResult(synthetic, 0.8, False, [], "path", [synthetic], False, "")

        logger.info("application_resolution_candidates", query=orig_query, candidates=[], count=0)
        return MatchResult(None, 0.0, False, [], "not_found", [], False, "")

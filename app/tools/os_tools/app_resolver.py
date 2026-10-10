from __future__ import annotations
import difflib
import re
import shutil
from typing import NamedTuple
from app.tools.os_tools.desktop_parser import DesktopParser, DesktopEntry

class MatchResult(NamedTuple):
    entry: DesktopEntry | None
    confidence: float
    is_ambiguous: bool
    ambiguous_candidates: list[str]
    method: str

class AppResolver:
    def __init__(self):
        self.parser = DesktopParser()
        self.entries = []
        self._initialized = False

    def initialize(self):
        if not self._initialized:
            self.entries = self.parser.discover_all()
            self._initialized = True
            
    def _normalize(self, text: str) -> str:
        text = text.lower()
        # Remove common extraneous words
        text = re.sub(r'\b(launch|open|start|run|a|an|the)\b', '', text)
        return text.strip()
        
    def _is_category_only(self, text: str) -> bool:
        """Check if the user is just asking for a generic category."""
        categories = {"browser", "editor", "terminal", "player", "calculator", "file manager", "mail", "email"}
        return text in categories

    def _get_category_words(self) -> set[str]:
        return {"browser", "editor", "terminal", "player", "calculator", "mail"}

    def resolve(self, query: str) -> MatchResult:
        self.initialize()
        
        orig_query = query.strip()
        norm_query = self._normalize(query)
        
        if not norm_query:
            return MatchResult(None, 0.0, False, [], "empty")

        # Constraint: If it's a generic category word only, we should ask the user
        if self._is_category_only(norm_query):
            # We don't want to silently resolve "browser" to Firefox unless configured, which we don't have.
            return MatchResult(None, 0.0, True, ["Specify which " + norm_query], "category_only")

        # Constraint: if query contains a specific name AND a category word, strip the category word for matching
        # Example: "helm browser" -> "helm"
        core_query = norm_query
        for cat in self._get_category_words():
            if norm_query.endswith(cat) and norm_query != cat:
                core_query = norm_query.replace(cat, "").strip()

        # 1. Exact canonical name match
        for entry in self.entries:
            if orig_query.lower() == entry.name.lower():
                return MatchResult(entry, 1.0, False, [], "exact")

        # 2. Exact alias / normalized match
        for entry in self.entries:
            if core_query == entry.name.lower():
                return MatchResult(entry, 1.0, False, [], "exact_normalized")

        # 3. Known ASR correction / Phonetic / Alias mapping
        # E.g. "helm" -> "helium", "krom" -> "chrome"
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
                if mapped_query in entry.name.lower():
                    return MatchResult(entry, 0.95, False, [], "asr_correction")

        # 4. Fuzzy / Edit-distance match
        # We check against Name, GenericName, and Exec name
        candidates = []
        for entry in self.entries:
            name_score = difflib.SequenceMatcher(None, mapped_query, entry.name.lower()).ratio()
            
            # If query is a word-aligned substring of the name (e.g., "chrome" in "google chrome")
            if mapped_query in entry.name.lower().split():
                name_score = max(name_score, 0.9)
                
            # Exec score (e.g. 'google-chrome-stable' vs 'chrome')
            exec_bin = entry.exec.split()[0].split('/')[-1].lower() if entry.exec else ""
            exec_score = difflib.SequenceMatcher(None, mapped_query, exec_bin).ratio()
            # If query is substring of exec binary
            if mapped_query in exec_bin and len(mapped_query) > 3:
                exec_score = max(exec_score, 0.85)

            # Keyword score
            kw_score = 0
            if mapped_query in [k.lower() for k in entry.keywords]:
                kw_score = 0.8
                
            best_score = max(name_score, exec_score, kw_score)
            
            # Penalty if it's a purely category match but the user specified a specific app
            # (To satisfy: "helm browser" MUST NOT match Firefox)
            # If the best score came from a keyword like "browser", but the query was "helm", we shouldn't rank it high.
            # We already stripped 'browser', so mapped_query is 'helm'. 'helm' won't match 'browser' keyword anyway.
            
            if best_score > 0.6:
                candidates.append((best_score, entry))
                
        if candidates:
            candidates.sort(key=lambda x: x[0], reverse=True)
            best_score, best_entry = candidates[0]
            
            if best_score >= 0.75:
                # Check for ambiguity
                if len(candidates) > 1:
                    second_score, second_entry = candidates[1]
                    # If very close in score, it's ambiguous
                    if best_score - second_score < 0.1 and best_entry.name != second_entry.name:
                        return MatchResult(None, best_score, True, [best_entry.name, second_entry.name], "fuzzy_ambiguous")
                
                return MatchResult(best_entry, best_score, False, [], "fuzzy")

        # 5. PATH executable lookup as fallback
        path_bin = shutil.which(core_query)
        if path_bin:
            # Create a synthetic desktop entry for the path binary
            synthetic = DesktopEntry(
                path=path_bin,
                name=core_query,
                exec=path_bin
            )
            return MatchResult(synthetic, 0.8, False, [], "path")
            
        return MatchResult(None, 0.0, False, [], "not_found")

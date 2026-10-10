from __future__ import annotations
import configparser
import glob
import os
import shlex
import shutil
from dataclasses import dataclass, field
import structlog

logger = structlog.get_logger(__name__)


@dataclass
class DesktopEntry:
    path: str
    name: str = ""
    generic_name: str = ""
    keywords: list[str] = field(default_factory=list)
    comment: str = ""
    exec: str = ""
    try_exec: str = ""
    no_display: bool = False
    hidden: bool = False
    app_id: str = ""

    def __post_init__(self):
        if not self.app_id and self.path:
            base = os.path.basename(self.path)
            self.app_id = base[:-8] if base.endswith(".desktop") else base


class DesktopParser:
    def __init__(self):
        self.search_paths = [
            os.path.expanduser("~/.local/share/applications/"),
            os.path.expanduser("~/.local/share/flatpak/exports/share/applications/"),
            "/usr/local/share/applications/",
            "/usr/share/applications/",
            "/var/lib/flatpak/exports/share/applications/",
        ]
        self._cached_entries: list[DesktopEntry] | None = None

    def _clean_exec(self, exec_str: str) -> str:
        if not exec_str:
            return ""
        # Remove %f, %F, %u, %U etc.
        parts = []
        for p in exec_str.split():
            if p.startswith("%") and len(p) == 2:
                continue
            parts.append(p)
        return " ".join(parts)

    def parse_file(self, path: str) -> DesktopEntry | None:
        try:
            parser = configparser.ConfigParser(interpolation=None)
            # .desktop files often have duplicate keys in different languages, strict=False helps
            parser.read(path, encoding='utf-8')
            
            if not parser.has_section("Desktop Entry"):
                return None
                
            entry = parser["Desktop Entry"]
            
            if entry.get("Type", "Application") != "Application":
                return None
                
            name = entry.get("Name", "")
            if not name:
                return None
                
            generic_name = entry.get("GenericName", "")
            keywords_str = entry.get("Keywords", "")
            keywords = [k.strip() for k in keywords_str.split(";") if k.strip()]
            comment = entry.get("Comment", "")
            exec_str = self._clean_exec(entry.get("Exec", ""))
            try_exec = entry.get("TryExec", "")
            no_display = entry.getboolean("NoDisplay", fallback=False)
            hidden = entry.getboolean("Hidden", fallback=False)
            base = os.path.basename(path)
            app_id = base[:-8] if base.endswith(".desktop") else base

            return DesktopEntry(
                path=path,
                name=name,
                generic_name=generic_name,
                keywords=keywords,
                comment=comment,
                exec=exec_str,
                try_exec=try_exec,
                no_display=no_display,
                hidden=hidden,
                app_id=app_id,
            )
        except Exception:
            return None

    def discover_all(self, force_refresh: bool = False) -> list[DesktopEntry]:
        if not force_refresh and self._cached_entries is not None:
            return self._cached_entries

        entries = []
        seen_ids = set()
        
        for base_path in self.search_paths:
            if not os.path.isdir(base_path):
                continue
                
            for filepath in glob.glob(os.path.join(base_path, "**/*.desktop"), recursive=True):
                entry = self.parse_file(filepath)
                if entry and not entry.hidden and not entry.no_display:
                    # Avoid duplicates by app_id / filename
                    if entry.app_id not in seen_ids:
                        entries.append(entry)
                        seen_ids.add(entry.app_id)

        self._cached_entries = entries
        logger.info("application_catalog_refresh", count=len(entries), paths=self.search_paths)
        return entries

    def refresh(self) -> list[DesktopEntry]:
        """Invalidate cache and re-scan application catalog."""
        return self.discover_all(force_refresh=True)

    @staticmethod
    def is_valid_candidate(entry: DesktopEntry) -> bool:
        """Validate if a discovered candidate's executable exists on the system."""
        if entry.try_exec:
            if shutil.which(entry.try_exec) or os.path.isfile(entry.try_exec):
                return True
        if entry.exec:
            try:
                parts = shlex.split(entry.exec)
                if parts:
                    bin_name = parts[0]
                    if shutil.which(bin_name) or (os.path.isfile(bin_name) and os.access(bin_name, os.X_OK)):
                        return True
            except Exception:
                pass
        return False


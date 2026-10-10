from __future__ import annotations
import os
import glob
from dataclasses import dataclass, field
import configparser

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

class DesktopParser:
    def __init__(self):
        self.search_paths = [
            os.path.expanduser("~/.local/share/applications/"),
            "/usr/local/share/applications/",
            "/usr/share/applications/"
        ]

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
            
            return DesktopEntry(
                path=path,
                name=name,
                generic_name=generic_name,
                keywords=keywords,
                comment=comment,
                exec=exec_str,
                try_exec=try_exec,
                no_display=no_display,
                hidden=hidden
            )
        except Exception:
            return None

    def discover_all(self) -> list[DesktopEntry]:
        entries = []
        seen_names = set()
        
        for base_path in self.search_paths:
            if not os.path.isdir(base_path):
                continue
                
            for filepath in glob.glob(os.path.join(base_path, "**/*.desktop"), recursive=True):
                entry = self.parse_file(filepath)
                if entry and not entry.hidden and not entry.no_display:
                    # Avoid duplicates by path basename
                    basename = os.path.basename(filepath)
                    if basename not in seen_names:
                        entries.append(entry)
                        seen_names.add(basename)
                        
        return entries

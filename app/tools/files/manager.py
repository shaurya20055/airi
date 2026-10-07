from __future__ import annotations

import asyncio
import os
import subprocess
from pathlib import Path

from app.tools.registry import PermissionLevel, ToolParameter, ToolRegistry, ToolResult, tool


@tool(
    name="read_file",
    description="Read the contents of a file.",
    category="Files",
    permission_level=PermissionLevel.CONFIRM,
    parameters=[
        ToolParameter(name="path", type="string", description="Absolute path to the file.")
    ]
)
async def read_file(path: str) -> ToolResult:
    try:
        p = Path(path).resolve()
        if not p.is_file():
            return ToolResult(success=False, error=f"File not found: {path}")
            
        with open(p, 'r', encoding='utf-8') as f:
            content = f.read()
        return ToolResult(success=True, data=content)
    except Exception as e:
        return ToolResult(success=False, error=str(e))


@tool(
    name="list_directory",
    description="List contents of a directory.",
    category="Files",
    permission_level=PermissionLevel.SAFE,
    parameters=[
        ToolParameter(name="path", type="string", description="Absolute path to the directory.")
    ]
)
async def list_directory(path: str) -> ToolResult:
    try:
        p = Path(path).resolve()
        if not p.is_dir():
            return ToolResult(success=False, error=f"Directory not found: {path}")
            
        entries = [str(entry.name) for entry in p.iterdir()]
        return ToolResult(success=True, data=entries)
    except Exception as e:
        return ToolResult(success=False, error=str(e))


@tool(
    name="search_files",
    description="Search for files in a directory.",
    category="Files",
    permission_level=PermissionLevel.SAFE,
    parameters=[
        ToolParameter(name="pattern", type="string", description="Glob pattern (e.g. *.txt)."),
        ToolParameter(name="directory", type="string", description="Directory to search in.")
    ]
)
async def search_files(pattern: str, directory: str) -> ToolResult:
    try:
        p = Path(directory).resolve()
        if not p.is_dir():
            return ToolResult(success=False, error=f"Directory not found: {directory}")
            
        matches = [str(m) for m in p.rglob(pattern)]
        return ToolResult(success=True, data=matches)
    except Exception as e:
        return ToolResult(success=False, error=str(e))


@tool(
    name="open_file",
    description="Open a file using the system default application.",
    category="Files",
    permission_level=PermissionLevel.SAFE,
    parameters=[
        ToolParameter(name="path", type="string", description="Absolute path to the file.")
    ]
)
async def open_file(path: str) -> ToolResult:
    try:
        p = Path(path).resolve()
        if not p.exists():
            return ToolResult(success=False, error=f"File not found: {path}")
            
        subprocess.Popen(['xdg-open', str(p)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return ToolResult(success=True, message=f"Opened {path}")
    except Exception as e:
        return ToolResult(success=False, error=str(e))


def register(registry: ToolRegistry) -> None:
    pass

"""Grep tool - Search file contents."""
from __future__ import annotations

import asyncio
import os
import re
import sys
from pathlib import Path
from typing import Any, Callable

from ..tool import Tool, ToolResult
from ..config import MAX_GREP_RESULTS


class GrepTool(Tool):
    """Search for text patterns in files."""

    name = "grep"
    description_text = (
        "Search for a pattern in files. "
        "Supports regular expressions. "
        "Searches recursively through directories."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "pattern": {
                "type": "string",
                "description": "Search pattern (regex supported).",
            },
            "path": {
                "type": "string",
                "description": "File or directory to search. Defaults to CWD.",
            },
            "include": {
                "type": "string",
                "description": "File pattern to include (e.g. '*.py').",
            },
        },
        "required": ["pattern"],
    }

    def is_read_only(self, tool_input: dict[str, Any]) -> bool:
        return True

    def is_concurrency_safe(self, tool_input: dict[str, Any]) -> bool:
        return True

    def get_tool_use_summary(self, tool_input: dict[str, Any]) -> str | None:
        pattern = tool_input.get("pattern", "")
        return f"Grep '{pattern}'"

    async def call(
        self,
        tool_input: dict[str, Any],
        cwd: str,
        on_progress: Callable[[dict[str, Any]], None] | None = None,
    ) -> ToolResult:
        pattern = tool_input.get("pattern", "")
        search_path = tool_input.get("path", cwd)
        include = tool_input.get("include")

        if not pattern:
            return ToolResult(output="Error: pattern is required", is_error=True)

        base = Path(search_path)
        if not base.is_absolute():
            base = Path(cwd) / search_path
        base = base.resolve()

        if not base.exists():
            return ToolResult(output=f"Error: Path not found: {base}", is_error=True)

        # Try using ripgrep (rg) if available
        try:
            rg_result = await self._search_with_rg(pattern, str(base), include, cwd)
            if rg_result is not None:
                return rg_result
        except FileNotFoundError:
            pass

        # Fallback to Python-based search
        return await self._search_python(pattern, base, include)

    async def _search_with_rg(
        self, pattern: str, path: str, include: str | None, cwd: str,
    ) -> ToolResult | None:
        """Search using ripgrep."""
        cmd = ["rg", "--line-number", "--no-heading", "--color=never", "-S"]
        if include:
            cmd.extend(["--glob", include])
        cmd.extend(["--max-count", "250", pattern, path])

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
            output = stdout.decode("utf-8", errors="replace")

            if proc.returncode == 1:  # no matches
                return ToolResult(output=f"No matches found for '{pattern}'")
            if proc.returncode == 0:
                lines = output.strip().split("\n")
                if len(lines) > MAX_GREP_RESULTS:
                    lines = lines[:MAX_GREP_RESULTS]
                    output = "\n".join(lines) + f"\n\n... (truncated at {MAX_GREP_RESULTS} results)"
                else:
                    output = "\n".join(lines)
                return ToolResult(output=f"Found {len(lines)} matches:\n{output}")
            return None  # fallback to Python
        except (asyncio.TimeoutError, FileNotFoundError):
            return None

    async def _search_python(
        self, pattern: str, base: Path, include: str | None,
    ) -> ToolResult:
        """Search using Python regex."""
        try:
            regex = re.compile(pattern, re.IGNORECASE)
        except re.error as e:
            return ToolResult(output=f"Error: Invalid regex pattern: {e}", is_error=True)

        results = []
        skip_dirs = {".git", "node_modules", "__pycache__", ".venv", "venv", ".mypy_cache"}

        if base.is_file():
            files = [base]
        else:
            files = []
            for root, dirs, filenames in os.walk(base):
                dirs[:] = [d for d in dirs if d not in skip_dirs and not d.startswith(".")]
                for fname in filenames:
                    if include:
                        import fnmatch
                        if not fnmatch.fnmatch(fname, include):
                            continue
                    files.append(Path(root) / fname)

        for filepath in files:
            if len(results) >= MAX_GREP_RESULTS:
                break
            try:
                content = filepath.read_text(encoding="utf-8", errors="replace")
                for line_num, line in enumerate(content.splitlines(), 1):
                    if regex.search(line):
                        rel = filepath.relative_to(base) if not base.is_file() else filepath.name
                        results.append(f"{rel}:{line_num}: {line.rstrip()}")
                        if len(results) >= MAX_GREP_RESULTS:
                            break
            except (OSError, UnicodeDecodeError):
                continue

        if not results:
            return ToolResult(output=f"No matches found for '{pattern}'")

        output = "\n".join(results)
        header = f"Found {len(results)} matches"
        if len(results) >= MAX_GREP_RESULTS:
            header += f" (truncated at {MAX_GREP_RESULTS})"
        return ToolResult(output=f"{header}:\n{output}")

"""Glob tool - Find files by pattern."""
from __future__ import annotations

import fnmatch
import os
from pathlib import Path
from typing import Any, Callable

from ..tool import Tool, ToolResult
from ..config import MAX_GLOB_RESULTS


class GlobTool(Tool):
    """Find files matching a glob pattern."""

    name = "glob"
    description_text = (
        "Find files matching a glob pattern. "
        "Searches from the current working directory. "
        "Returns up to 100 matching file paths."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "pattern": {
                "type": "string",
                "description": "Glob pattern to match (e.g. '**/*.py', 'src/**/*.ts').",
            },
            "path": {
                "type": "string",
                "description": "Directory to search in. Defaults to CWD.",
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
        return f"Glob {pattern}"

    async def call(
        self,
        tool_input: dict[str, Any],
        cwd: str,
        on_progress: Callable[[dict[str, Any]], None] | None = None,
    ) -> ToolResult:
        pattern = tool_input.get("pattern", "")
        search_path = tool_input.get("path", cwd)

        if not pattern:
            return ToolResult(output="Error: pattern is required", is_error=True)

        # Resolve search path
        base = Path(search_path)
        if not base.is_absolute():
            base = Path(cwd) / search_path
        base = base.resolve()

        if not base.exists():
            return ToolResult(output=f"Error: Directory not found: {base}", is_error=True)

        try:
            matches = []
            for path in base.glob(pattern):
                if len(matches) >= MAX_GLOB_RESULTS:
                    break
                # Skip hidden and common excluded directories
                parts = path.relative_to(base).parts
                skip = False
                for part in parts:
                    if part.startswith(".") and part not in (".", ".."):
                        skip = True
                        break
                    if part in ("node_modules", "__pycache__", ".git", "venv", ".venv"):
                        skip = True
                        break
                if skip:
                    continue
                matches.append(str(path.relative_to(base)))

            if not matches:
                return ToolResult(output=f"No files matched pattern '{pattern}' in {base}")

            result = "\n".join(sorted(matches))
            header = f"Found {len(matches)} matches"
            if len(matches) >= MAX_GLOB_RESULTS:
                header += f" (truncated at {MAX_GLOB_RESULTS})"
            return ToolResult(output=f"{header}:\n{result}")

        except Exception as e:
            return ToolResult(output=f"Error during glob: {e}", is_error=True)

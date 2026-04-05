"""List Directory tool."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Callable

from ..tool import Tool, ToolResult


class ListDirTool(Tool):
    """List directory contents."""

    name = "list_dir"
    description_text = (
        "List the contents of a directory. "
        "Returns names of files and subdirectories."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Directory path. Defaults to CWD.",
            },
        },
        "required": [],
    }

    def is_read_only(self, tool_input: dict[str, Any]) -> bool:
        return True

    def is_concurrency_safe(self, tool_input: dict[str, Any]) -> bool:
        return True

    async def call(
        self,
        tool_input: dict[str, Any],
        cwd: str,
        on_progress: Callable[[dict[str, Any]], None] | None = None,
    ) -> ToolResult:
        dir_path = tool_input.get("path", cwd)

        resolved = Path(dir_path)
        if not resolved.is_absolute():
            resolved = Path(cwd) / dir_path
        resolved = resolved.resolve()

        if not resolved.exists():
            return ToolResult(output=f"Error: Directory not found: {resolved}", is_error=True)

        if not resolved.is_dir():
            return ToolResult(output=f"Error: {resolved} is not a directory", is_error=True)

        try:
            entries = sorted(resolved.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
            lines = []
            for entry in entries:
                if entry.name.startswith("."):
                    continue
                suffix = "/" if entry.is_dir() else ""
                lines.append(f"  {entry.name}{suffix}")

            if not lines:
                return ToolResult(output=f"Directory {resolved} is empty")

            return ToolResult(output=f"{resolved}:\n" + "\n".join(lines))

        except PermissionError:
            return ToolResult(output=f"Error: Permission denied: {resolved}", is_error=True)

"""File Write tool - Create or overwrite files."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any, Callable

from ..tool import Tool, ToolResult


class FileWriteTool(Tool):
    """Create a new file or overwrite an existing file."""

    name = "file_write"
    description_text = (
        "Create a new file or completely overwrite an existing file with the provided content. "
        "Use file_edit for targeted edits to existing files."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "file_path": {
                "type": "string",
                "description": "Absolute path or path relative to CWD for the file.",
            },
            "content": {
                "type": "string",
                "description": "The full content to write to the file.",
            },
        },
        "required": ["file_path", "content"],
    }

    def is_read_only(self, tool_input: dict[str, Any]) -> bool:
        return False

    def is_concurrency_safe(self, tool_input: dict[str, Any]) -> bool:
        return False

    def get_tool_use_summary(self, tool_input: dict[str, Any]) -> str | None:
        path = tool_input.get("file_path", "")
        return f"Write {path}"

    async def call(
        self,
        tool_input: dict[str, Any],
        cwd: str,
        on_progress: Callable[[dict[str, Any]], None] | None = None,
    ) -> ToolResult:
        file_path = tool_input.get("file_path", "")
        content = tool_input.get("content", "")

        if not file_path:
            return ToolResult(output="Error: file_path is required", is_error=True)

        # Resolve path
        resolved = Path(file_path)
        if not resolved.is_absolute():
            resolved = Path(cwd) / file_path
        resolved = resolved.resolve()

        # Create parent directories
        try:
            resolved.parent.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            return ToolResult(output=f"Error creating directories: {e}", is_error=True)

        # Check if file exists (for reporting)
        existed = resolved.exists()

        # Atomic write
        try:
            dir_path = resolved.parent
            fd, tmp_path = tempfile.mkstemp(dir=str(dir_path), suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
                    f.write(content)
                if os.name == "nt" and resolved.exists():
                    resolved.unlink()
                os.replace(tmp_path, str(resolved))
            except Exception:
                os.unlink(tmp_path)
                raise
        except Exception as e:
            return ToolResult(output=f"Error writing file: {e}", is_error=True)

        lines = content.count("\n") + 1
        action = "Updated" if existed else "Created"
        return ToolResult(output=f"{action} {resolved} ({lines} lines)")

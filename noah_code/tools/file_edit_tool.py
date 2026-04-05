"""File Edit tool - Edit file contents with search and replace."""
from __future__ import annotations

import difflib
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Callable

from ..tool import Tool, ToolResult


class FileEditTool(Tool):
    """Edit an existing file by replacing a specific string."""

    name = "file_edit"
    description_text = (
        "Edit an existing file by replacing an exact string match with new content. "
        "The old_string must match exactly (including whitespace and indentation). "
        "Only the first occurrence is replaced. Use this for targeted edits."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "file_path": {
                "type": "string",
                "description": "Absolute path or path relative to CWD of the file to edit.",
            },
            "old_string": {
                "type": "string",
                "description": "The exact string to find and replace. Must match exactly.",
            },
            "new_string": {
                "type": "string",
                "description": "The replacement string.",
            },
        },
        "required": ["file_path", "old_string", "new_string"],
    }

    def is_read_only(self, tool_input: dict[str, Any]) -> bool:
        return False

    def is_concurrency_safe(self, tool_input: dict[str, Any]) -> bool:
        return False

    def get_tool_use_summary(self, tool_input: dict[str, Any]) -> str | None:
        path = tool_input.get("file_path", "")
        return f"Edit {path}"

    async def call(
        self,
        tool_input: dict[str, Any],
        cwd: str,
        on_progress: Callable[[dict[str, Any]], None] | None = None,
    ) -> ToolResult:
        file_path = tool_input.get("file_path", "")
        old_string = tool_input.get("old_string", "")
        new_string = tool_input.get("new_string", "")

        if not file_path:
            return ToolResult(output="Error: file_path is required", is_error=True)
        if not old_string:
            return ToolResult(output="Error: old_string is required", is_error=True)

        # Resolve path
        resolved = Path(file_path)
        if not resolved.is_absolute():
            resolved = Path(cwd) / file_path
        resolved = resolved.resolve()

        if not resolved.exists():
            return ToolResult(output=f"Error: File not found: {resolved}", is_error=True)

        if not resolved.is_file():
            return ToolResult(output=f"Error: {resolved} is not a file", is_error=True)

        try:
            content = resolved.read_text(encoding="utf-8")
        except Exception as e:
            return ToolResult(output=f"Error reading file: {e}", is_error=True)

        # Find the old string
        count = content.count(old_string)
        if count == 0:
            return ToolResult(
                output=f"Error: The old_string was not found in {resolved}. Make sure it matches exactly including whitespace.",
                is_error=True,
            )
        if count > 1:
            return ToolResult(
                output=f"Error: old_string found {count} times in {resolved}. It must be unique. Add more context to make it unique.",
                is_error=True,
            )

        # Perform replacement
        new_content = content.replace(old_string, new_string, 1)

        # Generate diff for display
        old_lines = content.splitlines(keepends=True)
        new_lines = new_content.splitlines(keepends=True)
        diff = difflib.unified_diff(
            old_lines, new_lines,
            fromfile=str(resolved),
            tofile=str(resolved),
            lineterm="",
        )
        diff_text = "\n".join(diff)

        # Atomic write
        try:
            dir_path = resolved.parent
            fd, tmp_path = tempfile.mkstemp(dir=str(dir_path), suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
                    f.write(new_content)
                # On Windows, need to remove target first
                if os.name == "nt" and resolved.exists():
                    resolved.unlink()
                os.replace(tmp_path, str(resolved))
            except Exception:
                os.unlink(tmp_path)
                raise
        except Exception as e:
            return ToolResult(output=f"Error writing file: {e}", is_error=True)

        return ToolResult(output=f"Successfully edited {resolved}\n\n{diff_text}")

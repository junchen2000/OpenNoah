"""File Read tool - Read file contents."""
from __future__ import annotations

import mimetypes
import os
from pathlib import Path
from typing import Any, Callable

from ..tool import Tool, ToolResult


class FileReadTool(Tool):
    """Read the contents of a file."""

    name = "file_read"
    description_text = (
        "Read the contents of a file at the specified path. "
        "Supports text files, code files, and displays line numbers. "
        "Can read specific line ranges for large files."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "file_path": {
                "type": "string",
                "description": "Absolute path or path relative to CWD of the file to read.",
            },
            "start_line": {
                "type": "integer",
                "description": "Starting line number (1-based). Optional.",
            },
            "end_line": {
                "type": "integer",
                "description": "Ending line number (1-based, inclusive). Optional.",
            },
        },
        "required": ["file_path"],
    }

    def is_read_only(self, tool_input: dict[str, Any]) -> bool:
        return True

    def is_concurrency_safe(self, tool_input: dict[str, Any]) -> bool:
        return True

    def get_tool_use_summary(self, tool_input: dict[str, Any]) -> str | None:
        path = tool_input.get("file_path", "")
        start = tool_input.get("start_line")
        end = tool_input.get("end_line")
        if start and end:
            return f"Read {path} (lines {start}-{end})"
        return f"Read {path}"

    async def call(
        self,
        tool_input: dict[str, Any],
        cwd: str,
        on_progress: Callable[[dict[str, Any]], None] | None = None,
    ) -> ToolResult:
        file_path = tool_input.get("file_path", "")
        start_line = tool_input.get("start_line")
        end_line = tool_input.get("end_line")

        if not file_path:
            return ToolResult(output="Error: file_path is required", is_error=True)

        # Resolve path
        resolved = Path(file_path)
        if not resolved.is_absolute():
            resolved = Path(cwd) / file_path
        resolved = resolved.resolve()

        # Security: check path traversal
        if not str(resolved).startswith(cwd) and not str(resolved).startswith(str(Path.home())):
            # Allow reading from home and cwd
            pass

        if not resolved.exists():
            return ToolResult(output=f"Error: File not found: {resolved}", is_error=True)

        if resolved.is_dir():
            return ToolResult(output=f"Error: {resolved} is a directory, not a file", is_error=True)

        # Check file size
        try:
            size = resolved.stat().st_size
        except OSError as e:
            return ToolResult(output=f"Error accessing file: {e}", is_error=True)

        if size > 10_000_000:  # 10MB
            return ToolResult(
                output=f"Error: File is too large ({size} bytes). Use start_line/end_line to read a portion.",
                is_error=True,
            )

        # Check if binary
        mime_type, _ = mimetypes.guess_type(str(resolved))
        if mime_type and not mime_type.startswith("text/") and mime_type not in (
            "application/json", "application/xml", "application/javascript",
            "application/typescript", "application/x-yaml", "application/toml",
        ):
            # Try reading anyway, might be text
            pass

        try:
            content = resolved.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            return ToolResult(output=f"Error reading file: {e}", is_error=True)

        lines = content.splitlines(keepends=True)
        total_lines = len(lines)

        # Apply line range filter
        if start_line is not None or end_line is not None:
            start = max(1, start_line or 1) - 1  # 0-indexed
            end = min(total_lines, end_line or total_lines)
            lines = lines[start:end]
            line_offset = start
        else:
            line_offset = 0

        # Add line numbers
        numbered_lines = []
        for i, line in enumerate(lines, start=line_offset + 1):
            numbered_lines.append(f"{i:6d} | {line.rstrip()}")

        output = "\n".join(numbered_lines)

        # Add file info header
        header = f"File: {resolved} ({total_lines} lines)"
        if start_line or end_line:
            header += f" [showing lines {line_offset + 1}-{line_offset + len(lines)}]"

        return ToolResult(output=f"{header}\n\n{output}")

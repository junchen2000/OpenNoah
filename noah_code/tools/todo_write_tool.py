"""Todo Write tool - manage a todo/task list."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from ..tool import Tool, ToolResult


class TodoWriteTool(Tool):
    """Create or update a todo list file for tracking tasks."""

    name = "todo_write"
    description_text = (
        "Create or update a todo list. Useful for tracking multi-step tasks. "
        "The todo list is stored as a JSON file in the working directory."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "todos": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "integer"},
                        "title": {"type": "string"},
                        "status": {"type": "string", "enum": ["not-started", "in-progress", "completed"]},
                    },
                    "required": ["id", "title", "status"],
                },
                "description": "The complete todo list.",
            },
        },
        "required": ["todos"],
    }

    def is_read_only(self, tool_input: dict[str, Any]) -> bool:
        return False

    def get_tool_use_summary(self, tool_input: dict[str, Any]) -> str | None:
        todos = tool_input.get("todos", [])
        done = sum(1 for t in todos if t.get("status") == "completed")
        return f"Todo: {done}/{len(todos)} done"

    async def call(
        self,
        tool_input: dict[str, Any],
        cwd: str,
        on_progress: Callable[[dict[str, Any]], None] | None = None,
    ) -> ToolResult:
        todos = tool_input.get("todos", [])
        if not todos:
            return ToolResult(output="Error: todos list is required", is_error=True)

        path = Path(cwd) / ".noah" / "todos.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(todos, indent=2), encoding="utf-8")

        done = sum(1 for t in todos if t.get("status") == "completed")
        in_prog = sum(1 for t in todos if t.get("status") == "in-progress")
        lines = [f"Todo list updated ({done}/{len(todos)} completed, {in_prog} in progress):"]
        for t in todos:
            icon = {"completed": "✓", "in-progress": "→", "not-started": "○"}.get(t.get("status", ""), "?")
            lines.append(f"  {icon} [{t.get('id', '?')}] {t.get('title', '')}")
        return ToolResult(output="\n".join(lines))

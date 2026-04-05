"""Task management tools - create, list, get, stop background tasks."""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Callable

from ..config import get_config_dir
from ..tool import Tool, ToolResult


def _tasks_file() -> Path:
    return get_config_dir() / "tasks.json"


def _load_tasks() -> list[dict[str, Any]]:
    path = _tasks_file()
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text("utf-8"))
    except (json.JSONDecodeError, OSError):
        return []


def _save_tasks(tasks: list[dict[str, Any]]) -> None:
    path = _tasks_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(tasks, indent=2), encoding="utf-8")


class TaskCreateTool(Tool):
    """Create a new background task."""

    name = "task_create"
    description_text = "Create a background task to track asynchronous work."
    input_schema = {
        "type": "object",
        "properties": {
            "description": {"type": "string", "description": "Task description."},
            "type": {"type": "string", "enum": ["shell", "agent", "reminder"], "description": "Task type."},
        },
        "required": ["description"],
    }

    async def call(self, tool_input: dict[str, Any], cwd: str,
                   on_progress: Callable[[dict[str, Any]], None] | None = None) -> ToolResult:
        desc = tool_input.get("description", "")
        task_type = tool_input.get("type", "reminder")
        tasks = _load_tasks()
        task_id = f"task_{int(time.time())}_{len(tasks)}"
        task = {
            "id": task_id, "description": desc, "type": task_type,
            "status": "pending", "created_at": time.time(), "output": "",
        }
        tasks.append(task)
        _save_tasks(tasks)
        return ToolResult(output=f"Created task {task_id}: {desc}")


class TaskListTool(Tool):
    """List all tasks."""

    name = "task_list"
    description_text = "List all background tasks and their status."
    input_schema = {"type": "object", "properties": {}}

    def is_read_only(self, tool_input: dict[str, Any]) -> bool:
        return True

    def is_concurrency_safe(self, tool_input: dict[str, Any]) -> bool:
        return True

    async def call(self, tool_input: dict[str, Any], cwd: str,
                   on_progress: Callable[[dict[str, Any]], None] | None = None) -> ToolResult:
        tasks = _load_tasks()
        if not tasks:
            return ToolResult(output="No tasks.")
        lines = ["Tasks:"]
        for t in tasks:
            icon = {"pending": "○", "running": "→", "completed": "✓", "failed": "✗", "killed": "⊘"}.get(t["status"], "?")
            lines.append(f"  {icon} {t['id'][:20]}  {t['status']:<10}  {t['description'][:50]}")
        return ToolResult(output="\n".join(lines))


class TaskGetTool(Tool):
    """Get details of a specific task."""

    name = "task_get"
    description_text = "Get detailed information about a specific task."
    input_schema = {
        "type": "object",
        "properties": {"task_id": {"type": "string", "description": "Task ID."}},
        "required": ["task_id"],
    }

    def is_read_only(self, tool_input: dict[str, Any]) -> bool:
        return True

    async def call(self, tool_input: dict[str, Any], cwd: str,
                   on_progress: Callable[[dict[str, Any]], None] | None = None) -> ToolResult:
        task_id = tool_input.get("task_id", "")
        tasks = _load_tasks()
        for t in tasks:
            if t["id"] == task_id or t["id"].startswith(task_id):
                lines = [f"Task: {t['id']}", f"Status: {t['status']}", f"Type: {t['type']}",
                         f"Description: {t['description']}"]
                if t.get("output"):
                    lines.append(f"Output:\n{t['output'][:2000]}")
                return ToolResult(output="\n".join(lines))
        return ToolResult(output=f"Task not found: {task_id}", is_error=True)


class TaskStopTool(Tool):
    """Stop/kill a running task."""

    name = "task_stop"
    description_text = "Stop a running background task."
    input_schema = {
        "type": "object",
        "properties": {"task_id": {"type": "string", "description": "Task ID to stop."}},
        "required": ["task_id"],
    }

    async def call(self, tool_input: dict[str, Any], cwd: str,
                   on_progress: Callable[[dict[str, Any]], None] | None = None) -> ToolResult:
        task_id = tool_input.get("task_id", "")
        tasks = _load_tasks()
        for t in tasks:
            if t["id"] == task_id or t["id"].startswith(task_id):
                t["status"] = "killed"
                _save_tasks(tasks)
                return ToolResult(output=f"Stopped task {t['id']}")
        return ToolResult(output=f"Task not found: {task_id}", is_error=True)

"""Tool use summary service - generate human-readable summaries of tool calls."""
from __future__ import annotations

from typing import Any


def summarize_tool_use(tool_name: str, tool_input: dict[str, Any], result_output: str) -> str:
    """Generate a concise human-readable summary of a tool call."""
    summaries = {
        "bash": lambda i, o: f"Ran: {i.get('command', '')[:80]}",
        "file_read": lambda i, o: f"Read {i.get('file_path', '')}",
        "file_edit": lambda i, o: f"Edited {i.get('file_path', '')}",
        "file_write": lambda i, o: f"Wrote {i.get('file_path', '')}",
        "glob": lambda i, o: f"Found files matching {i.get('pattern', '')}",
        "grep": lambda i, o: f"Searched for '{i.get('pattern', '')}'",
        "list_dir": lambda i, o: f"Listed {i.get('path', 'cwd')}",
        "web_fetch": lambda i, o: f"Fetched {i.get('url', '')}",
        "web_search": lambda i, o: f"Searched: {i.get('query', '')}",
        "agent": lambda i, o: f"Subagent: {i.get('task', i.get('prompt', ''))[:60]}",
        "notebook_edit": lambda i, o: f"Notebook: {i.get('action', '')} cell in {i.get('file_path', '')}",
        "repl": lambda i, o: f"Ran {i.get('language', 'python')} code",
        "todo_write": lambda i, o: f"Updated todo list ({len(i.get('todos', []))} items)",
        "powershell": lambda i, o: f"PowerShell: {i.get('command', '')[:60]}",
        "config": lambda i, o: f"Config: {i.get('action', '')} {i.get('key', '')}",
        "task_create": lambda i, o: f"Created task: {i.get('description', '')[:50]}",
        "task_list": lambda i, o: "Listed tasks",
        "task_stop": lambda i, o: f"Stopped task {i.get('task_id', '')}",
        "sleep": lambda i, o: f"Slept {i.get('seconds', 0)}s",
    }

    formatter = summaries.get(tool_name)
    if formatter:
        try:
            return formatter(tool_input, result_output)
        except Exception:
            pass

    return f"{tool_name}: {str(tool_input)[:60]}"


def summarize_tool_batch(tools: list[tuple[str, dict[str, Any], str]]) -> str:
    """Summarize a batch of tool calls."""
    if not tools:
        return "No tools used"
    if len(tools) == 1:
        name, inp, out = tools[0]
        return summarize_tool_use(name, inp, out)

    lines = [f"Used {len(tools)} tools:"]
    for name, inp, out in tools:
        lines.append(f"  • {summarize_tool_use(name, inp, out)}")
    return "\n".join(lines)

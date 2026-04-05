"""Agent tool - spawn a subagent for isolated tasks."""
from __future__ import annotations

import asyncio
from typing import Any, Callable

from ..tool import Tool, ToolResult


class AgentTool(Tool):
    """Spawn a subagent to handle a task in an isolated context."""

    name = "agent"
    description_text = (
        "Spawn a subagent to handle a complex task. The subagent gets its own "
        "conversation context and can use all available tools. Use this for "
        "tasks that require focused exploration without polluting the main context."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "task": {
                "type": "string",
                "description": "Description of the task for the subagent to perform.",
            },
            "prompt": {
                "type": "string",
                "description": "The detailed prompt/instructions for the subagent.",
            },
        },
        "required": ["prompt"],
    }

    def is_read_only(self, tool_input: dict[str, Any]) -> bool:
        return False

    def is_concurrency_safe(self, tool_input: dict[str, Any]) -> bool:
        return False

    def get_tool_use_summary(self, tool_input: dict[str, Any]) -> str | None:
        task = tool_input.get("task", tool_input.get("prompt", ""))
        return f"Agent: {task[:60]}..."

    async def call(
        self,
        tool_input: dict[str, Any],
        cwd: str,
        on_progress: Callable[[dict[str, Any]], None] | None = None,
    ) -> ToolResult:
        prompt = tool_input.get("prompt", "")
        task = tool_input.get("task", "")

        if not prompt:
            return ToolResult(output="Error: prompt is required", is_error=True)

        # For now, subagent is implemented as a single-shot query
        # A full implementation would create a new QueryEngine with isolated state
        return ToolResult(
            output=f"[Subagent task received: {task or prompt[:100]}]\n"
                   f"Note: Full subagent isolation not yet implemented in Python port. "
                   f"The prompt has been noted and should be addressed in the main conversation.",
        )

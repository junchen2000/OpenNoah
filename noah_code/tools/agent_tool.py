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

        from ..services.subagent import run_subagent, SubagentConfig
        from ..state import get_state
        from ..tools.registry import create_tool_registry

        state = get_state()
        # Create a fresh tool registry for the subagent
        tool_registry = create_tool_registry()

        config = SubagentConfig(
            system_prompt=(
                "You are a subagent for Noah Code. Complete the given task fully "
                "using the tools available. Be concise in your final report."
            ),
            max_iterations=10,
        )

        try:
            result = await run_subagent(
                api_client=self._get_api_client(state),
                tool_registry=tool_registry,
                prompt=prompt,
                config=config,
                cwd=cwd,
            )
            output = result.text
            if result.error:
                output += f"\n\nError: {result.error}"
            return ToolResult(output=output)
        except Exception as e:
            return ToolResult(output=f"Subagent error: {e}", is_error=True)

    @staticmethod
    def _get_api_client(state):
        from ..services.claude_api import NoahAPIClient
        return NoahAPIClient(
            model=state.model,
            base_url=state.base_url,
            api_key=state.api_key,
        )

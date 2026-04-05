"""Plan Mode tools - enter/exit planning mode."""
from __future__ import annotations

from typing import Any, Callable

from ..tool import Tool, ToolResult


class EnterPlanModeTool(Tool):
    """Enter plan mode - all tool calls require explicit approval."""

    name = "enter_plan_mode"
    description_text = (
        "Enter plan mode where you describe what you want to do before doing it. "
        "All tool uses will be listed for review before execution."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "reason": {
                "type": "string",
                "description": "Why entering plan mode (optional).",
            },
        },
    }

    def is_read_only(self, tool_input: dict[str, Any]) -> bool:
        return True

    async def call(
        self, tool_input: dict[str, Any], cwd: str,
        on_progress: Callable[[dict[str, Any]], None] | None = None,
    ) -> ToolResult:
        reason = tool_input.get("reason", "")
        msg = "Entered plan mode. I'll describe my plan before making any changes."
        if reason:
            msg += f"\nReason: {reason}"
        return ToolResult(output=msg, metadata={"plan_mode": True})


class ExitPlanModeTool(Tool):
    """Exit plan mode and return to normal execution."""

    name = "exit_plan_mode"
    description_text = "Exit plan mode and resume normal tool execution."
    input_schema = {"type": "object", "properties": {}}

    def is_read_only(self, tool_input: dict[str, Any]) -> bool:
        return True

    async def call(
        self, tool_input: dict[str, Any], cwd: str,
        on_progress: Callable[[dict[str, Any]], None] | None = None,
    ) -> ToolResult:
        return ToolResult(output="Exited plan mode. Resuming normal execution.",
                         metadata={"plan_mode": False})

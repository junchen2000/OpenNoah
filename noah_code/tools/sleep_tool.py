"""Sleep tool - pause execution for a specified duration."""
from __future__ import annotations

import asyncio
from typing import Any, Callable

from ..tool import Tool, ToolResult


class SleepTool(Tool):
    """Pause execution for a specified number of seconds."""

    name = "sleep"
    description_text = (
        "Pause execution for a specified duration. Useful for waiting for "
        "background processes, rate limiting, or timed operations."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "seconds": {
                "type": "number",
                "description": "Number of seconds to sleep (max 300).",
            },
        },
        "required": ["seconds"],
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
        seconds = tool_input.get("seconds", 0)
        if not isinstance(seconds, (int, float)) or seconds <= 0:
            return ToolResult(output="Error: seconds must be a positive number", is_error=True)

        seconds = min(seconds, 300)  # Cap at 5 minutes
        await asyncio.sleep(seconds)
        return ToolResult(output=f"Slept for {seconds} seconds")

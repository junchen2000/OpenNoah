"""Tool Search - search available tools by keyword/description."""
from __future__ import annotations

from typing import Any, Callable

from ..tool import Tool, ToolResult


class ToolSearchTool(Tool):
    """Search for available tools by name or description."""

    name = "tool_search"
    description_text = (
        "Search for available tools by keyword. Useful when you're not sure "
        "which tool to use for a task."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Keyword to search for in tool names and descriptions.",
            },
        },
        "required": ["query"],
    }

    # Will be set by registry after creation
    _registry = None

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
        query = tool_input.get("query", "").lower()
        if not query:
            return ToolResult(output="Error: query is required", is_error=True)

        if self._registry is None:
            return ToolResult(output="Error: tool registry not available", is_error=True)

        matches = []
        for tool in self._registry.get_all():
            name = tool.name.lower()
            desc = tool.get_description().lower()
            if query in name or query in desc:
                matches.append(f"  {tool.name}: {tool.get_description()[:80]}")

        if not matches:
            return ToolResult(output=f"No tools matching '{query}'")

        return ToolResult(output=f"Found {len(matches)} tools:\n" + "\n".join(matches))

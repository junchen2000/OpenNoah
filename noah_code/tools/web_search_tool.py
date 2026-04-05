"""Web Search tool - Search the web."""
from __future__ import annotations

from typing import Any, Callable

from ..tool import Tool, ToolResult


class WebSearchTool(Tool):
    """Search the web for information."""

    name = "web_search"
    description_text = (
        "Search the web for information using a query. "
        "Returns search results with titles and snippets."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The search query.",
            },
        },
        "required": ["query"],
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
        """Web search - uses the Anthropic API's built-in web search when available."""
        query = tool_input.get("query", "")
        if not query:
            return ToolResult(output="Error: query is required", is_error=True)

        # Web search is typically handled via the API's server-side tool
        # This is a fallback that explains the limitation
        return ToolResult(
            output=f"Web search for '{query}' - this tool requires the Anthropic API's "
                   f"server-side web search capability. Use web_fetch with a specific URL instead.",
        )

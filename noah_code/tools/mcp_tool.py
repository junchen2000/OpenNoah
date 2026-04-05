"""MCP Tool wrapper - wraps MCP server tools as Noah Code tools."""
from __future__ import annotations

from typing import Any, Callable, TYPE_CHECKING

from ..tool import Tool, ToolResult

if TYPE_CHECKING:
    from ..services.mcp_client import MCPManager, MCPToolInfo


class MCPTool(Tool):
    """Wraps an MCP server tool as a Noah Code tool."""

    def __init__(self, mcp_manager: "MCPManager", tool_info: "MCPToolInfo") -> None:
        super().__init__()
        self._mcp = mcp_manager
        self._info = tool_info
        # Name format: mcp__{server}__{tool} (matches Claude Code convention)
        self.name = f"mcp__{tool_info.server_name}__{tool_info.tool_name}"
        self.description_text = tool_info.description or f"MCP tool from {tool_info.server_name}"
        self.input_schema = tool_info.input_schema or {"type": "object", "properties": {}}

    def is_read_only(self, tool_input: dict[str, Any]) -> bool:
        return False  # Can't know — be conservative

    def is_concurrency_safe(self, tool_input: dict[str, Any]) -> bool:
        return True  # MCP servers handle their own concurrency

    def get_tool_use_summary(self, tool_input: dict[str, Any]) -> str | None:
        return f"MCP:{self._info.server_name}/{self._info.tool_name}"

    async def call(
        self,
        tool_input: dict[str, Any],
        cwd: str,
        on_progress: Callable[[dict[str, Any]], None] | None = None,
    ) -> ToolResult:
        try:
            output = await self._mcp.call_tool(
                self._info.server_name,
                self._info.tool_name,
                tool_input,
            )
            return ToolResult(output=output)
        except Exception as e:
            return ToolResult(output=f"MCP error: {e}", is_error=True)


def create_mcp_tools(mcp_manager: "MCPManager") -> list[MCPTool]:
    """Create Tool wrappers for all discovered MCP tools."""
    tools = []
    for tool_info in mcp_manager.get_all_tools():
        tools.append(MCPTool(mcp_manager, tool_info))
    return tools

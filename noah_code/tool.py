"""Tool base class and registry for Noah Code."""
from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator, Callable, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from .state import AppState


@dataclass
class ToolResult:
    """Result from a tool execution."""
    output: str = ""
    is_error: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


class Tool(abc.ABC):
    """Base class for all tools."""

    name: str = ""
    description_text: str = ""
    input_schema: dict[str, Any] = {}

    def __init__(self) -> None:
        pass

    @abc.abstractmethod
    async def call(
        self,
        tool_input: dict[str, Any],
        cwd: str,
        on_progress: Callable[[dict[str, Any]], None] | None = None,
    ) -> ToolResult:
        """Execute the tool with the given input."""
        ...

    def get_description(self) -> str:
        """Return tool description for system prompt."""
        return self.description_text

    def get_prompt(self) -> str:
        """Return tool-specific prompt instructions."""
        return ""

    def is_enabled(self) -> bool:
        """Whether this tool is currently available."""
        return True

    def is_read_only(self, tool_input: dict[str, Any]) -> bool:
        """Whether this invocation is read-only."""
        return False

    def is_concurrency_safe(self, tool_input: dict[str, Any]) -> bool:
        """Whether this tool can run concurrently with others."""
        return False

    def get_tool_use_summary(self, tool_input: dict[str, Any]) -> str | None:
        """Short summary of what this tool invocation does."""
        return None

    def to_api_schema(self) -> dict[str, Any]:
        """Convert to Anthropic API tool schema format."""
        return {
            "name": self.name,
            "description": self.get_description(),
            "input_schema": self.input_schema,
        }


class ToolRegistry:
    """Registry of available tools."""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        """Register a tool."""
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        """Get a tool by name."""
        return self._tools.get(name)

    def get_all(self) -> list[Tool]:
        """Get all registered tools."""
        return [t for t in self._tools.values() if t.is_enabled()]

    def get_api_schemas(self) -> list[dict[str, Any]]:
        """Get all tool schemas for the API."""
        return [t.to_api_schema() for t in self.get_all()]

    def find_by_name(self, name: str) -> Tool | None:
        """Find a tool by name."""
        return self._tools.get(name)

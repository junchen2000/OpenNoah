"""Tool registry - register all available tools."""
from __future__ import annotations

import sys

from ..tool import ToolRegistry
from .agent_tool import AgentTool
from .ask_user_tool import AskUserQuestionTool
from .bash_tool import BashTool
from .config_tool import ConfigTool
from .file_read_tool import FileReadTool
from .file_edit_tool import FileEditTool
from .file_write_tool import FileWriteTool
from .glob_tool import GlobTool
from .grep_tool import GrepTool
from .list_dir_tool import ListDirTool
from .notebook_edit_tool import NotebookEditTool
from .plan_mode_tools import EnterPlanModeTool, ExitPlanModeTool
from .powershell_tool import PowerShellTool
from .repl_tool import REPLTool
from .sleep_tool import SleepTool
from .task_tools import TaskCreateTool, TaskListTool, TaskGetTool, TaskStopTool
from .todo_write_tool import TodoWriteTool
from .tool_search_tool import ToolSearchTool
from .web_fetch_tool import WebFetchTool
from .web_search_tool import WebSearchTool


def create_tool_registry() -> ToolRegistry:
    """Create and populate the tool registry with all available tools."""
    registry = ToolRegistry()

    # Core file tools
    registry.register(BashTool())
    registry.register(FileReadTool())
    registry.register(FileEditTool())
    registry.register(FileWriteTool())
    registry.register(GlobTool())
    registry.register(GrepTool())
    registry.register(ListDirTool())

    # Web tools
    registry.register(WebFetchTool())
    registry.register(WebSearchTool())

    # Advanced tools
    registry.register(AgentTool())
    registry.register(NotebookEditTool())
    registry.register(REPLTool())
    registry.register(TodoWriteTool())
    registry.register(SleepTool())
    registry.register(AskUserQuestionTool())
    registry.register(ConfigTool())
    registry.register(EnterPlanModeTool())
    registry.register(ExitPlanModeTool())

    # Task management
    registry.register(TaskCreateTool())
    registry.register(TaskListTool())
    registry.register(TaskGetTool())
    registry.register(TaskStopTool())

    # Platform-specific
    if sys.platform == "win32":
        registry.register(PowerShellTool())

    # Tool search (needs reference to registry)
    tool_search = ToolSearchTool()
    tool_search._registry = registry
    registry.register(tool_search)

    return registry

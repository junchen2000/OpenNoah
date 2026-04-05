"""Notebook Edit tool - Edit Jupyter notebooks."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from ..tool import Tool, ToolResult


class NotebookEditTool(Tool):
    """Edit Jupyter notebook cells."""

    name = "notebook_edit"
    description_text = (
        "Edit a Jupyter notebook (.ipynb) file. Can add, edit, or delete cells."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "file_path": {
                "type": "string",
                "description": "Path to the .ipynb file.",
            },
            "action": {
                "type": "string",
                "enum": ["add", "edit", "delete"],
                "description": "Action to perform on the notebook.",
            },
            "cell_index": {
                "type": "integer",
                "description": "Cell index (0-based). Required for edit/delete.",
            },
            "cell_type": {
                "type": "string",
                "enum": ["code", "markdown"],
                "description": "Cell type for add/edit.",
            },
            "content": {
                "type": "string",
                "description": "Cell content for add/edit.",
            },
        },
        "required": ["file_path", "action"],
    }

    def is_read_only(self, tool_input: dict[str, Any]) -> bool:
        return False

    async def call(
        self,
        tool_input: dict[str, Any],
        cwd: str,
        on_progress: Callable[[dict[str, Any]], None] | None = None,
    ) -> ToolResult:
        file_path = tool_input.get("file_path", "")
        action = tool_input.get("action", "")
        cell_index = tool_input.get("cell_index")
        cell_type = tool_input.get("cell_type", "code")
        content = tool_input.get("content", "")

        resolved = Path(file_path)
        if not resolved.is_absolute():
            resolved = Path(cwd) / file_path
        resolved = resolved.resolve()

        if action == "add":
            return await self._add_cell(resolved, cell_type, content)
        elif action == "edit":
            if cell_index is None:
                return ToolResult(output="Error: cell_index required for edit", is_error=True)
            return await self._edit_cell(resolved, cell_index, cell_type, content)
        elif action == "delete":
            if cell_index is None:
                return ToolResult(output="Error: cell_index required for delete", is_error=True)
            return await self._delete_cell(resolved, cell_index)
        return ToolResult(output=f"Unknown action: {action}", is_error=True)

    async def _add_cell(self, path: Path, cell_type: str, content: str) -> ToolResult:
        nb = self._load_or_create(path)
        cell = self._make_cell(cell_type, content)
        nb["cells"].append(cell)
        path.write_text(json.dumps(nb, indent=1), encoding="utf-8")
        return ToolResult(output=f"Added {cell_type} cell at index {len(nb['cells'])-1}")

    async def _edit_cell(self, path: Path, index: int, cell_type: str, content: str) -> ToolResult:
        nb = self._load_or_create(path)
        if index < 0 or index >= len(nb["cells"]):
            return ToolResult(output=f"Error: cell index {index} out of range (0-{len(nb['cells'])-1})", is_error=True)
        nb["cells"][index] = self._make_cell(cell_type, content)
        path.write_text(json.dumps(nb, indent=1), encoding="utf-8")
        return ToolResult(output=f"Edited cell {index}")

    async def _delete_cell(self, path: Path, index: int) -> ToolResult:
        nb = self._load_or_create(path)
        if index < 0 or index >= len(nb["cells"]):
            return ToolResult(output=f"Error: cell index {index} out of range", is_error=True)
        nb["cells"].pop(index)
        path.write_text(json.dumps(nb, indent=1), encoding="utf-8")
        return ToolResult(output=f"Deleted cell {index}")

    @staticmethod
    def _load_or_create(path: Path) -> dict:
        if path.exists():
            return json.loads(path.read_text("utf-8"))
        return {
            "nbformat": 4, "nbformat_minor": 5,
            "metadata": {"kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"}},
            "cells": [],
        }

    @staticmethod
    def _make_cell(cell_type: str, content: str) -> dict:
        return {
            "cell_type": cell_type,
            "metadata": {},
            "source": content.splitlines(True),
            **({"outputs": [], "execution_count": None} if cell_type == "code" else {}),
        }

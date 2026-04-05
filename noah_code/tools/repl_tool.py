"""REPL Tool - run code in a subprocess REPL (Python, Node, etc)."""
from __future__ import annotations

import asyncio
import sys
from typing import Any, Callable

from ..tool import Tool, ToolResult


class REPLTool(Tool):
    """Run code snippets in an interactive REPL subprocess."""

    name = "repl"
    description_text = (
        "Execute a code snippet in a subprocess REPL. Supports Python and Node.js. "
        "Useful for quick calculations, testing code, or exploring APIs."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "code": {
                "type": "string",
                "description": "The code to execute.",
            },
            "language": {
                "type": "string",
                "enum": ["python", "node", "bash"],
                "description": "Language/runtime to use (default: python).",
            },
        },
        "required": ["code"],
    }

    def is_read_only(self, tool_input: dict[str, Any]) -> bool:
        return False

    def get_tool_use_summary(self, tool_input: dict[str, Any]) -> str | None:
        lang = tool_input.get("language", "python")
        code = tool_input.get("code", "")
        first_line = code.strip().split("\n")[0][:50]
        return f"REPL ({lang}): {first_line}"

    async def call(
        self,
        tool_input: dict[str, Any],
        cwd: str,
        on_progress: Callable[[dict[str, Any]], None] | None = None,
    ) -> ToolResult:
        code = tool_input.get("code", "")
        language = tool_input.get("language", "python")

        if not code.strip():
            return ToolResult(output="Error: code is required", is_error=True)

        if language == "python":
            cmd = [sys.executable, "-c", code]
        elif language == "node":
            cmd = ["node", "-e", code]
        elif language == "bash":
            if sys.platform == "win32":
                cmd = ["cmd", "/c", code]
            else:
                cmd = ["bash", "-c", code]
        else:
            return ToolResult(output=f"Unsupported language: {language}", is_error=True)

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
            stdout_text = stdout.decode("utf-8", errors="replace") if stdout else ""
            stderr_text = stderr.decode("utf-8", errors="replace") if stderr else ""

            output = stdout_text
            if stderr_text:
                output += f"\nstderr:\n{stderr_text}" if output else stderr_text

            if not output.strip():
                output = "(no output)"

            if proc.returncode != 0:
                output = f"Exit code: {proc.returncode}\n{output}"

            return ToolResult(output=output, is_error=proc.returncode != 0)
        except asyncio.TimeoutError:
            return ToolResult(output="Execution timed out (30s)", is_error=True)
        except Exception as e:
            return ToolResult(output=f"Error: {e}", is_error=True)

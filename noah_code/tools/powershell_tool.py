"""PowerShell tool - Execute PowerShell commands (Windows-aware)."""
from __future__ import annotations

import asyncio
import os
import sys
from typing import Any, Callable

from ..tool import Tool, ToolResult


class PowerShellTool(Tool):
    """Execute PowerShell commands."""

    name = "powershell"
    description_text = (
        "Execute a PowerShell command. Use this for Windows-specific operations, "
        "registry access, WMI queries, and .NET operations."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "The PowerShell command to execute.",
            },
            "timeout": {
                "type": "integer",
                "description": "Timeout in seconds. Default 300.",
            },
        },
        "required": ["command"],
    }

    def is_enabled(self) -> bool:
        return sys.platform == "win32"

    def is_read_only(self, tool_input: dict[str, Any]) -> bool:
        cmd = tool_input.get("command", "").lower()
        read_cmds = {"get-", "select-", "where-", "measure-", "format-", "sort-", "compare-",
                      "test-path", "resolve-path", "split-path", "join-path", "write-host"}
        return any(cmd.strip().lower().startswith(r) for r in read_cmds)

    def is_concurrency_safe(self, tool_input: dict[str, Any]) -> bool:
        return self.is_read_only(tool_input)

    async def call(
        self, tool_input: dict[str, Any], cwd: str,
        on_progress: Callable[[dict[str, Any]], None] | None = None,
    ) -> ToolResult:
        command = tool_input.get("command", "")
        timeout = tool_input.get("timeout", 300)

        if not command.strip():
            return ToolResult(output="Error: Empty command", is_error=True)

        try:
            proc = await asyncio.create_subprocess_exec(
                "powershell", "-NoProfile", "-NonInteractive", "-Command", command,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, cwd=cwd,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            out = stdout.decode("utf-8", errors="replace") if stdout else ""
            err = stderr.decode("utf-8", errors="replace") if stderr else ""
            output = out + (f"\nstderr:\n{err}" if err else "") or "(no output)"
            if len(output) > 100_000:
                half = 50_000
                output = output[:half] + f"\n... truncated ...\n" + output[-half:]
            is_error = proc.returncode != 0
            if is_error:
                output = f"Exit code: {proc.returncode}\n{output}"
            return ToolResult(output=output, is_error=is_error)
        except asyncio.TimeoutError:
            return ToolResult(output=f"Timed out after {timeout}s", is_error=True)
        except Exception as e:
            return ToolResult(output=f"Error: {e}", is_error=True)

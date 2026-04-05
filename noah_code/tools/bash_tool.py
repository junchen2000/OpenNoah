"""Bash tool - Execute shell commands."""
from __future__ import annotations

import asyncio
import os
import signal
import sys
from typing import Any, Callable

from ..tool import Tool, ToolResult


class BashTool(Tool):
    """Execute shell commands in the system shell."""

    name = "bash"
    description_text = (
        "Execute a shell command. Use this to run programs, install packages, "
        "search for files, compile code, run tests, and perform other shell operations. "
        "The command runs in the current working directory. "
        "For long-running commands, consider using background execution."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "The shell command to execute.",
            },
            "timeout": {
                "type": "integer",
                "description": "Timeout in seconds. Default 120.",
            },
        },
        "required": ["command"],
    }

    def is_read_only(self, tool_input: dict[str, Any]) -> bool:
        cmd = tool_input.get("command", "")
        read_commands = {
            "cat", "head", "tail", "less", "more", "wc", "find", "grep",
            "rg", "ls", "dir", "tree", "du", "df", "file", "stat",
            "which", "where", "type", "echo", "pwd", "env", "printenv",
            "date", "whoami", "hostname", "uname", "git log", "git show",
            "git diff", "git status", "git branch",
        }
        cmd_start = cmd.strip().split()[0] if cmd.strip() else ""
        return cmd_start in read_commands

    def is_concurrency_safe(self, tool_input: dict[str, Any]) -> bool:
        return self.is_read_only(tool_input)

    def get_tool_use_summary(self, tool_input: dict[str, Any]) -> str | None:
        cmd = tool_input.get("command", "")
        if len(cmd) > 80:
            return cmd[:77] + "..."
        return cmd

    async def call(
        self,
        tool_input: dict[str, Any],
        cwd: str,
        on_progress: Callable[[dict[str, Any]], None] | None = None,
    ) -> ToolResult:
        command = tool_input.get("command", "")
        timeout = tool_input.get("timeout", 120)

        if not command.strip():
            return ToolResult(output="Error: Empty command", is_error=True)

        try:
            # Choose shell based on OS
            if sys.platform == "win32":
                shell_cmd = command
                proc = await asyncio.create_subprocess_shell(
                    shell_cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=cwd,
                    env={**os.environ},
                )
            else:
                proc = await asyncio.create_subprocess_exec(
                    "bash", "-c", command,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=cwd,
                    env={**os.environ},
                )

            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(), timeout=timeout
                )
            except asyncio.TimeoutError:
                try:
                    proc.terminate()
                    await asyncio.sleep(0.5)
                    if proc.returncode is None:
                        proc.kill()
                except ProcessLookupError:
                    pass
                return ToolResult(
                    output=f"Command timed out after {timeout} seconds",
                    is_error=True,
                )

            stdout_text = stdout.decode("utf-8", errors="replace") if stdout else ""
            stderr_text = stderr.decode("utf-8", errors="replace") if stderr else ""

            # Build output
            output_parts = []
            if stdout_text:
                output_parts.append(stdout_text)
            if stderr_text:
                output_parts.append(f"stderr:\n{stderr_text}")

            output = "\n".join(output_parts) if output_parts else "(no output)"

            # Truncate large outputs
            max_chars = 100_000
            if len(output) > max_chars:
                half = max_chars // 2
                output = (
                    output[:half]
                    + f"\n\n... ({len(output) - max_chars} characters truncated) ...\n\n"
                    + output[-half:]
                )

            is_error = proc.returncode != 0
            if is_error:
                output = f"Exit code: {proc.returncode}\n{output}"

            return ToolResult(output=output, is_error=is_error)

        except Exception as e:
            return ToolResult(output=f"Error executing command: {e}", is_error=True)

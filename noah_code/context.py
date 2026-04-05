"""Context management - system prompt, git status, user context."""
from __future__ import annotations

import asyncio
import os
import subprocess
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

from .config import SYSTEM_PROMPT_PREFIX, TOOL_USE_INSTRUCTIONS, get_noah_md_path, get_config_dir


async def get_git_status(cwd: str) -> str:
    """Get git branch and status information."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "git", "branch", "--show-current",
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        branch = stdout.decode().strip() if proc.returncode == 0 else ""

        proc = await asyncio.create_subprocess_exec(
            "git", "status", "--short",
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        status = stdout.decode().strip() if proc.returncode == 0 else ""

        proc = await asyncio.create_subprocess_exec(
            "git", "log", "--oneline", "-5",
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        recent_log = stdout.decode().strip() if proc.returncode == 0 else ""

        parts = []
        if branch:
            parts.append(f"Current branch: {branch}")
        if status:
            parts.append(f"Status:\n{status}")
        if recent_log:
            parts.append(f"Recent commits:\n{recent_log}")
        return "\n".join(parts)
    except FileNotFoundError:
        return ""


def get_user_context(cwd: str) -> str:
    """Get user context from NOAH.md files."""
    noah_md_content = ""

    # Check project-level NOAH.md
    project_md = get_noah_md_path(cwd)
    if project_md.exists():
        try:
            noah_md_content = project_md.read_text(encoding="utf-8")
        except OSError:
            pass

    # Check home directory NOAH.md
    home_md = Path.home() / ".noah" / "NOAH.md"
    if home_md.exists():
        try:
            home_content = home_md.read_text(encoding="utf-8")
            if home_content:
                if noah_md_content:
                    noah_md_content = home_content + "\n\n" + noah_md_content
                else:
                    noah_md_content = home_content
        except OSError:
            pass

    return noah_md_content


async def build_system_prompt(
    cwd: str,
    tools_description: str = "",
    custom_system_prompt: str | None = None,
    append_system_prompt: str | None = None,
    skills_description: str = "",
) -> str:
    """Build the complete system prompt."""
    if custom_system_prompt:
        prompt = custom_system_prompt
    else:
        prompt = SYSTEM_PROMPT_PREFIX

    # Add tool use instructions
    prompt += TOOL_USE_INSTRUCTIONS

    # Add tools description
    if tools_description:
        prompt += f"\n{tools_description}\n"

    # Add user context from NOAH.md
    user_context = get_user_context(cwd)
    if user_context:
        prompt += f"\n# User's Project Instructions (NOAH.md)\n\n{user_context}\n"

    # Add cross-session memories
    from .services.memories import get_memory_context
    memory_context = get_memory_context()
    if memory_context:
        prompt += f"\n{memory_context}\n"

    # Add git status
    git_status = await get_git_status(cwd)
    if git_status:
        prompt += f"\n# Git Status\n\n{git_status}\n"

    # Add current date and working directory
    prompt += f"\n# Environment\n"
    prompt += f"- Working directory: {cwd}\n"
    prompt += f"- Current date: {datetime.now().strftime('%Y-%m-%d')}\n"
    prompt += f"- Operating system: {os.name}\n"
    prompt += f"- Platform: {_get_platform()}\n"
    prompt += f"- Noah config directory: {get_config_dir()}\n"
    prompt += f"- Skills directory: {get_config_dir() / 'skills'}\n"

    # Platform-specific tool guidance
    if os.name == "nt":
        prompt += ("\nIMPORTANT: On Windows, prefer the `powershell` tool over `bash` for running commands. "
                   "The `bash` tool uses cmd.exe on Windows and does not support bash/unix syntax.\n"
                   "IMPORTANT: On Windows, do NOT use ~ for home paths. Use the exact Noah config directory shown above.\n")

    # Add skills description
    if skills_description:
        prompt += f"\n{skills_description}\n"

    # Add appended system prompt
    if append_system_prompt:
        prompt += f"\n{append_system_prompt}\n"

    return prompt


def _get_platform() -> str:
    """Get platform description."""
    import platform
    return f"{platform.system()} {platform.release()}"

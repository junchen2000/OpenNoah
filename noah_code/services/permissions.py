"""Permission checking for tool execution.

Modes:
  default          — YOLO: auto-approve everything except dangerous/codebase paths
  acceptEdits      — auto-approve file edits; prompt for shell commands
  dontAsk          — never prompt; deny anything that would need permission
  bypassPermissions — skip all permission checks (for sandboxes only)

Hard rule: Noah's own codebase is NEVER writable, regardless of mode.
"""
from __future__ import annotations

import fnmatch
import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING

from ..types import PermissionBehavior, PermissionMode, PermissionResult
from ..config import get_config_dir

if TYPE_CHECKING:
    from ..state import AppState
    from ..tool import Tool

logger = logging.getLogger(__name__)

# Noah's own package directory — NEVER allow writes here
_NOAH_PACKAGE_DIR: str = str(Path(__file__).resolve().parent.parent)

# Dangerous files that should prompt in non-bypass modes
DANGEROUS_FILES = frozenset({
    ".gitconfig", ".gitmodules", ".bashrc", ".bash_profile",
    ".zshrc", ".zprofile", ".profile",
})

# Dangerous directories
DANGEROUS_DIRECTORIES = frozenset({
    ".git", ".noah", ".vscode", ".idea",
})

# Tools that never need permission
ALWAYS_ALLOW_TOOLS = frozenset({
    "file_read", "glob", "grep", "list_dir",
    "web_fetch", "web_search", "todo_write", "tool_search",
    "ask_user", "enter_plan_mode", "exit_plan_mode", "sleep",
    "file_write", "file_edit", "notebook_edit",
    "bash", "powershell",
    "agent", "task_create", "task_list", "task_get", "task_stop",
    "repl", "config",
})

# File-editing tools (for acceptEdits mode distinction)
FILE_EDIT_TOOLS = frozenset({"file_write", "file_edit", "notebook_edit"})


def _resolve_path(path_str: str, cwd: str = "") -> str:
    """Resolve a path to absolute, normalized form."""
    p = Path(path_str)
    if not p.is_absolute() and cwd:
        p = Path(cwd) / p
    return str(p.resolve()).replace("\\", "/").lower()


def _is_noah_codebase(path_str: str, cwd: str = "") -> bool:
    """Check if a path is inside Noah's own package directory."""
    resolved = _resolve_path(path_str, cwd)
    pkg_dir = _NOAH_PACKAGE_DIR.replace("\\", "/").lower()
    return resolved.startswith(pkg_dir + "/") or resolved == pkg_dir


def _is_dangerous_path(path_str: str) -> bool:
    """Check if a path targets a dangerous file or directory.

    Exception: ~/.noah/skills/ and ~/.noah/mcp.json are allowed (skill/MCP installation).
    """
    normalized = path_str.replace("\\", "/")

    # Allow writes to ~/.noah/skills/ and ~/.noah/mcp.json (skill/MCP installation)
    noah_dir = str(get_config_dir()).replace("\\", "/")
    if normalized.startswith(noah_dir + "/skills/") or normalized.endswith("/mcp.json"):
        return False

    basename = os.path.basename(normalized)
    if basename.lower() in {f.lower() for f in DANGEROUS_FILES}:
        return True
    parts = normalized.split("/")
    for part in parts:
        if part.lower() in {d.lower() for d in DANGEROUS_DIRECTORIES}:
            return True
    return False


def _matches_allowed_pattern(tool_name: str, tool_input: dict, patterns: list[str]) -> bool:
    """Check if a tool call matches any allowed-tools pattern."""
    for pattern in patterns:
        if "(" in pattern and pattern.endswith(")"):
            paren_idx = pattern.index("(")
            pat_name = pattern[:paren_idx].strip().lower()
            arg_glob = pattern[paren_idx + 1:-1].strip()
            if not fnmatch.fnmatch(tool_name.lower(), pat_name):
                continue
            cmd = tool_input.get("command", "") or tool_input.get("content", "") or ""
            if fnmatch.fnmatch(cmd, arg_glob):
                return True
        else:
            if fnmatch.fnmatch(tool_name.lower(), pattern.lower()):
                return True
    return False


def check_permission(
    tool: "Tool",
    tool_input: dict,
    state: "AppState",
) -> PermissionResult:
    """Determine whether a tool call should be allowed, denied, or prompt the user."""
    tool_name = tool.name
    mode = state.permission_mode

    # ── HARD DENY: Noah's own codebase is NEVER writable ──────────
    if tool_name in FILE_EDIT_TOOLS:
        for key in ("file_path", "path"):
            path = tool_input.get(key, "")
            if path and _is_noah_codebase(path, state.cwd):
                return PermissionResult(
                    behavior=PermissionBehavior.DENY,
                    message=f"BLOCKED: Cannot modify Noah's codebase ({path}). "
                            f"Install skills to ~/.noah/skills/ or MCP to ~/.noah/mcp.json.",
                )

    if tool_name in ("bash", "powershell"):
        cmd = tool_input.get("command", "")
        pkg_lower = _NOAH_PACKAGE_DIR.replace("\\", "/").lower()
        if pkg_lower in cmd.lower().replace("\\", "/"):
            read_prefixes = ("cat ", "type ", "get-content", "select-string",
                             "grep ", "rg ", "find ", "head ", "tail ", "less ", "more ")
            if not any(cmd.lower().strip().startswith(r) for r in read_prefixes):
                return PermissionResult(
                    behavior=PermissionBehavior.DENY,
                    message=f"BLOCKED: Cannot modify Noah's codebase via shell.",
                )

    # ── 1. Always-safe tools (+ MCP tools) ────────────────────────
    if tool_name in ALWAYS_ALLOW_TOOLS or tool_name.startswith("mcp__"):
        # Still check dangerous paths on file-edit tools
        if tool_name in FILE_EDIT_TOOLS and mode != PermissionMode.BYPASS:
            for key in ("file_path", "path"):
                path = tool_input.get(key, "")
                if path and _is_dangerous_path(path):
                    return PermissionResult(
                        behavior=PermissionBehavior.ASK,
                        message=f"Write to protected path: {path}",
                    )
        return PermissionResult(behavior=PermissionBehavior.ALLOW)

    # ── 2. Read-only invocations ──────────────────────────────────
    if tool.is_read_only(tool_input):
        return PermissionResult(behavior=PermissionBehavior.ALLOW)

    # ── 3. Pre-approved tool patterns (--allowed-tools) ───────────
    if state.allowed_tools and _matches_allowed_pattern(tool_name, tool_input, state.allowed_tools):
        return PermissionResult(behavior=PermissionBehavior.ALLOW)

    # ── 4. Mode-specific ──────────────────────────────────────────
    if mode == PermissionMode.BYPASS:
        return PermissionResult(behavior=PermissionBehavior.ALLOW)

    if mode == PermissionMode.ACCEPT_EDITS:
        if tool_name in FILE_EDIT_TOOLS:
            return PermissionResult(behavior=PermissionBehavior.ALLOW)
        return PermissionResult(behavior=PermissionBehavior.ASK, message=f"Allow '{tool_name}'?")

    if mode == PermissionMode.DONT_ASK:
        return PermissionResult(
            behavior=PermissionBehavior.DENY,
            message=f"Tool '{tool_name}' denied (dontAsk mode).",
        )

    # DEFAULT (YOLO): allow everything that passed codebase protection
    return PermissionResult(behavior=PermissionBehavior.ALLOW)

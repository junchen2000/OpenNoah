"""Commands system - slash commands for the REPL."""
from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Coroutine

from .config import VERSION, get_config_dir, get_noah_md_path
from .state import AppState


@dataclass
class Command:
    """A slash command."""
    name: str
    description: str
    handler: Callable[..., Coroutine[Any, Any, str | None]]
    aliases: list[str] | None = None


async def cmd_help(state: AppState, args: str, commands: dict[str, Command]) -> str | None:
    """Show available commands."""
    lines = ["Available commands:", ""]
    for name, cmd in sorted(commands.items()):
        aliases = f" (aliases: {', '.join(cmd.aliases)})" if cmd.aliases else ""
        lines.append(f"  /{name:<16} {cmd.description}{aliases}")
    return "\n".join(lines)


async def cmd_exit(state: AppState, args: str, commands: dict[str, Command]) -> str | None:
    """Exit Noah Code."""
    raise SystemExit(0)


async def cmd_clear(state: AppState, args: str, commands: dict[str, Command]) -> str | None:
    """Clear conversation history."""
    count = len(state.messages)
    state.clear_messages()
    return f"Cleared {count} messages."


async def cmd_model(state: AppState, args: str, commands: dict[str, Command]) -> str | None:
    """Show or change the current model."""
    if args.strip():
        state.model = args.strip()
        return f"Model set to: {state.model}"
    return f"Current model: {state.model}"


async def cmd_cost(state: AppState, args: str, commands: dict[str, Command]) -> str | None:
    """Show cost and token usage."""
    return (
        f"Token usage:\n"
        f"  Input tokens:  {state.total_input_tokens:,}\n"
        f"  Output tokens: {state.total_output_tokens:,}\n"
        f"  Total cost:    ${state.total_cost:.4f}\n"
        f"  Turns:         {state.turn_count}"
    )


async def cmd_version(state: AppState, args: str, commands: dict[str, Command]) -> str | None:
    """Show version."""
    return f"Noah Code v{VERSION} (Python port)"


async def cmd_cwd(state: AppState, args: str, commands: dict[str, Command]) -> str | None:
    """Show or change working directory."""
    if args.strip():
        new_cwd = os.path.abspath(os.path.expanduser(args.strip()))
        if os.path.isdir(new_cwd):
            state.cwd = new_cwd
            os.chdir(new_cwd)
            return f"Working directory: {new_cwd}"
        return f"Error: Not a directory: {new_cwd}"
    return f"Working directory: {state.cwd}"


async def cmd_compact(state: AppState, args: str, commands: dict[str, Command]) -> str | None:
    """Compact conversation history using LLM-powered summarization."""
    if len(state.messages) <= 4:
        return "Nothing to compact (need more than 4 messages)."

    from .services.compact import compact_with_llm
    from .services.claude_api import NoahAPIClient

    original_count = len(state.messages)
    try:
        client = NoahAPIClient(model=state.model, base_url=state.base_url, api_key=state.api_key)
        compacted = await compact_with_llm(state.messages, client)
        state.messages = compacted
        return f"Compacted: {original_count} → {len(compacted)} messages (LLM summary + recent)."
    except Exception as e:
        # Fallback: simple truncation
        kept = state.messages[-4:]
        removed = len(state.messages) - len(kept)
        state.messages = kept
        return f"Compacted (simple fallback): removed {removed} messages. (LLM failed: {e})"


async def cmd_verbose(state: AppState, args: str, commands: dict[str, Command]) -> str | None:
    """Toggle verbose mode."""
    state.verbose = not state.verbose
    return f"Verbose mode: {'on' if state.verbose else 'off'}"


async def cmd_debug(state: AppState, args: str, commands: dict[str, Command]) -> str | None:
    """Toggle debug mode."""
    state.debug = not state.debug
    import logging
    logging.getLogger().setLevel(logging.DEBUG if state.debug else logging.WARNING)
    return f"Debug mode: {'on' if state.debug else 'off'}"


# ── Buddy ─────────────────────────────────────────────────────

async def cmd_buddy(state: AppState, args: str, commands: dict[str, Command]) -> str | None:
    """View or interact with your companion pet."""
    from .buddy import get_companion, hatch_companion, render_sprite, RARITY_STARS
    uid = os.environ.get("USER", os.environ.get("USERNAME", "anon"))
    subcmd = args.strip().split(maxsplit=1) if args else [""]
    action = subcmd[0].lower()

    if action == "hatch":
        companion = hatch_companion(uid)
        sprite = render_sprite(companion)
        return f"{sprite}\n\nHatched: {companion.name} the {companion.species}! {RARITY_STARS.get(companion.rarity, '')}"

    companion = get_companion(uid)
    if not companion:
        return "No companion yet! Use /buddy hatch to get one."

    sprite = render_sprite(companion)
    return f"{sprite}\n\n{companion.name} the {companion.species} {RARITY_STARS.get(companion.rarity, '')}"


# ── Session Management ────────────────────────────────────────

async def cmd_session(state: AppState, args: str, commands: dict[str, Command]) -> str | None:
    """Session management: save, load, list."""
    from .history import save_session, load_session, list_sessions

    subcmd = args.strip().split(maxsplit=1) if args else [""]
    action = subcmd[0].lower()

    if action == "save":
        save_session(
            state.session_id,
            state.messages,
            model=state.model, total_cost=state.total_cost, cwd=state.cwd,
        )
        return f"Session saved: {state.session_id[:8]}..."

    elif action == "load":
        if len(subcmd) < 2:
            return "Usage: /session load <session-id>"
        sid = subcmd[1].strip()
        data = load_session(sid)
        if not data:
            return f"Session not found: {sid}"
        state.messages = data.get("messages", [])
        return f"Loaded session {sid[:8]}... ({len(state.messages)} messages)"

    elif action == "list":
        sessions = list_sessions()
        if not sessions:
            return "No saved sessions."
        lines = ["Saved sessions:", ""]
        for s in sessions[:20]:
            lines.append(f"  {s['id'][:8]}  {s.get('date', '?')}  {s.get('model', '?')}  ${s.get('cost', 0):.4f}")
        return "\n".join(lines)

    return "Usage: /session [save|load <id>|list]"


# ── Memory (NOAH.md) ─────────────────────────────────────────

async def cmd_memory(state: AppState, args: str, commands: dict[str, Command]) -> str | None:
    """View or edit NOAH.md memory file."""
    subcmd = args.strip().split(maxsplit=1) if args else [""]
    action = subcmd[0].lower()

    project_md = get_noah_md_path(state.cwd)
    home_md = get_config_dir() / "NOAH.md"

    if action == "show" or action == "":
        lines = []
        if home_md.exists():
            lines.append(f"~/.noah/NOAH.md:\n{home_md.read_text('utf-8')[:1000]}")
        if project_md.exists():
            lines.append(f"\n{project_md}:\n{project_md.read_text('utf-8')[:1000]}")
        return "\n".join(lines) if lines else "No NOAH.md files found."

    elif action == "add":
        if len(subcmd) < 2:
            return "Usage: /memory add <text to remember>"
        text = subcmd[1]
        project_md.parent.mkdir(parents=True, exist_ok=True)
        with open(project_md, "a", encoding="utf-8") as f:
            f.write(f"\n{text}\n")
        return f"Added to {project_md}"

    elif action == "save":
        # Save a cross-session memory note
        if len(subcmd) < 2:
            return "Usage: /memory save <text to remember across sessions>"
        from .services.memories import save_memory
        path = save_memory(subcmd[1], category="user", source_session=state.session_id)
        return f"Memory saved to {path}"

    elif action == "list":
        # List cross-session memories
        from .services.memories import load_memories
        mems = load_memories(limit=10)
        if not mems:
            return "No cross-session memories saved yet. Use /memory save <text>."
        lines = ["Cross-session memories:", ""]
        for m in mems:
            content = m["content"].strip().split("\n")
            text = next((l for l in content if not l.startswith("<!--")), "")[:80]
            lines.append(f"  [{m['category']}] {text}")
        return "\n".join(lines)

    return "Usage: /memory [show|add <text>|save <text>|list]"


# ── Doctor (diagnostics) ─────────────────────────────────────

async def cmd_doctor(state: AppState, args: str, commands: dict[str, Command]) -> str | None:
    """Run environment diagnostics."""
    lines = ["Noah Code Diagnostics:", ""]

    lines.append(f"  Version:   {VERSION}")
    lines.append(f"  CWD:       {state.cwd}")
    lines.append(f"  Model:     {state.model}")

    # API connectivity
    from .services.claude_api import NoahAPIClient
    client = NoahAPIClient(model=state.model, base_url=state.base_url, api_key=state.api_key)
    lines.append(f"  API URL:   {client._build_url()}")
    lines.append(f"  Azure:     {'yes' if client.is_azure else 'no'}")

    # Git
    import shutil
    lines.append(f"  Git:       {'found' if shutil.which('git') else 'not found'}")
    lines.append(f"  Ripgrep:   {'found' if shutil.which('rg') else 'not found'}")

    # Config
    config_dir = get_config_dir()
    lines.append(f"  Config:    {config_dir}")
    lines.append(f"  NOAH.md: {'found' if get_noah_md_path(state.cwd).exists() else 'not found'}")

    # Buddy
    from .buddy import get_companion
    uid = os.environ.get("USER", os.environ.get("USERNAME", "anon"))
    companion = get_companion(uid)
    lines.append(f"  Companion: {companion.name + ' (' + companion.species + ')' if companion else 'none (try /buddy hatch)'}")

    lines.append("\n  ✓ All checks passed")
    return "\n".join(lines)


# ── Status ────────────────────────────────────────────────────

async def cmd_status(state: AppState, args: str, commands: dict[str, Command]) -> str | None:
    """Show session status."""
    elapsed = time.time() - state.start_time
    mins = int(elapsed // 60)
    return "\n".join([
        f"Session: {state.session_id[:8]}...",
        f"Model:   {state.model}",
        f"Turns:   {state.turn_count}",
        f"Tokens:  {state.total_input_tokens:,}↑  {state.total_output_tokens:,}↓",
        f"Cost:    ${state.total_cost:.4f}",
        f"Time:    {mins}m",
    ])


# ── Think ─────────────────────────────────────────────────────

async def cmd_think(state: AppState, args: str, commands: dict[str, Command]) -> str | None:
    """Send a message with extended thinking enabled."""
    if not args.strip():
        return "Usage: /think <your message>"
    # Set a flag so the REPL processes this with thinking enabled
    state._pending_think_message = args.strip()
    return None  # handled by REPL as a message with thinking flag


# ── Commit ────────────────────────────────────────────────────

async def cmd_commit(state: AppState, args: str, commands: dict[str, Command]) -> str | None:
    """Generate a commit message and create a commit."""
    import asyncio

    # Check for changes
    proc = await asyncio.create_subprocess_exec(
        "git", "diff", "--cached", "--stat",
        cwd=state.cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await proc.communicate()
    staged = stdout.decode().strip()

    if not staged:
        proc = await asyncio.create_subprocess_exec(
            "git", "diff", "--stat",
            cwd=state.cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        unstaged = stdout.decode().strip()
        if unstaged:
            return "No staged changes. Stage files with `git add` first.\n\nUnstaged changes:\n" + unstaged
        return "No changes to commit."

    # Return info - model will generate commit message
    state._pending_skill_prompt = (
        f"Generate a concise commit message for the following staged changes and "
        f"run `git commit -m '<message>'`:\n\n{staged}"
    )
    return None


# ── Review ────────────────────────────────────────────────────

async def cmd_review(state: AppState, args: str, commands: dict[str, Command]) -> str | None:
    """Review recent code changes."""
    import asyncio

    proc = await asyncio.create_subprocess_exec(
        "git", "diff", "HEAD~1", "--stat",
        cwd=state.cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await proc.communicate()
    diff_stat = stdout.decode().strip()

    if not diff_stat:
        return "No recent changes found."

    # Return info - the model will review the actual diffs
    return None  # Handled by REPL


# ── Init / Onboarding ────────────────────────────────────────

async def cmd_init(state: AppState, args: str, commands: dict[str, Command]) -> str | None:
    """Initialize a project with NOAH.md."""
    noah_md = get_noah_md_path(state.cwd)
    if noah_md.exists():
        return f"NOAH.md already exists at {noah_md}"

    template = """# Project Instructions

## Overview
<!-- Describe your project here -->

## Code Style
<!-- Describe coding conventions -->

## Key Files
<!-- List important files and their purpose -->

## Build & Test
<!-- How to build and test the project -->
"""
    noah_md.write_text(template, encoding="utf-8")
    return f"Created {noah_md} with template. Edit it to teach Noah about your project."


# ── Brief Mode ───────────────────────────────────────────────

async def cmd_brief(state: AppState, args: str, commands: dict[str, Command]) -> str | None:
    """Toggle brief response mode."""
    if not hasattr(state, '_brief_mode'):
        state._brief_mode = False
    state._brief_mode = not state._brief_mode
    if state._brief_mode:
        state.append_system_prompt = (state.append_system_prompt or "") + "\nBe extremely concise. Use minimal words.\n"
    return f"Brief mode: {'on' if state._brief_mode else 'off'}"


# ── Insights ─────────────────────────────────────────────────

async def cmd_insights(state: AppState, args: str, commands: dict[str, Command]) -> str | None:
    """Show usage insights and satisfaction analytics."""
    try:
        from .insights import load_insights, format_insights
        insights = load_insights()
        return format_insights(insights)
    except Exception as e:
        return f"Error loading insights: {e}"


# ── Security Review ──────────────────────────────────────────

async def cmd_security_review(state: AppState, args: str, commands: dict[str, Command]) -> str | None:
    """Run a security review of recent changes."""
    state._pending_skill_prompt = (
        "Review the recent code changes in this project for security vulnerabilities. "
        "Check for OWASP Top 10 issues, hardcoded secrets, injection flaws, "
        "and insecure configurations. Use git diff and file reading tools."
    )
    return None


# ── Plan Mode ────────────────────────────────────────────────

async def cmd_plan(state: AppState, args: str, commands: dict[str, Command]) -> str | None:
    """Toggle plan mode."""
    from .types import PermissionMode
    if state.permission_mode == PermissionMode.PLAN:
        state.permission_mode = PermissionMode.DEFAULT
        return "Plan mode: off (switched to default)"
    state.permission_mode = PermissionMode.PLAN
    return "Plan mode: on (read-only, use tools to explore before acting)"


# ── Tips ─────────────────────────────────────────────────────

async def cmd_tips(state: AppState, args: str, commands: dict[str, Command]) -> str | None:
    """Show a random tip."""
    from .services.tips import get_random_tip
    return get_random_tip()


# ── MCP ──────────────────────────────────────────────────────

async def cmd_mcp(state: AppState, args: str, commands: dict[str, Command]) -> str | None:
    """Manage MCP servers - list, connect, status."""
    from .services.mcp_client import MCPManager

    subcmd = args.strip().split(maxsplit=1) if args else [""]
    action = subcmd[0].lower()

    if action == "status" or action == "":
        # Show status of connected MCP servers; auto-connect if not yet done
        if not hasattr(state, '_mcp_manager') or state._mcp_manager is None:
            state._mcp_manager = MCPManager()
            conns = await state._mcp_manager.connect_all(state.cwd)
            if not conns:
                config_path = get_config_dir() / "mcp.json"
                return f"No MCP servers configured. Add servers to {config_path}"
        mgr: MCPManager = state._mcp_manager
        conns = mgr.get_connections()
        if not conns:
            return "No MCP servers connected."
        lines = ["MCP Servers:"]
        for c in conns:
            status = "✓ connected" if c.connected else f"✗ {c.error}"
            lines.append(f"  {c.config.name} ({c.config.type}): {status}")
            for t in c.tools:
                lines.append(f"    - {t.tool_name}: {t.description[:60]}")
        return "\n".join(lines)

    elif action == "connect":
        # Connect to all configured servers
        if not hasattr(state, '_mcp_manager') or state._mcp_manager is None:
            state._mcp_manager = MCPManager()
        mgr = state._mcp_manager
        conns = await mgr.connect_all(state.cwd)
        if not conns:
            return "No MCP servers found in config. Add servers to ~/.noah/mcp.json"
        tools = mgr.get_all_tools()
        lines = [f"Connected to {len(conns)} MCP server(s), {len(tools)} tools discovered:"]
        for c in conns:
            status = "✓" if c.connected else f"✗ {c.error}"
            lines.append(f"  {status} {c.config.name}: {len(c.tools)} tools")
        return "\n".join(lines)

    elif action == "disconnect":
        if hasattr(state, '_mcp_manager') and state._mcp_manager:
            await state._mcp_manager.disconnect_all()
            state._mcp_manager = None
        return "Disconnected from all MCP servers."

    elif action == "config":
        # Show config file location and contents
        config_path = get_config_dir() / "mcp.json"
        if not config_path.exists():
            return f"No MCP config found. Create {config_path} with:\n" + json.dumps({
                "mcpServers": {
                    "microsoft-learn": {
                        "type": "http",
                        "url": "https://learn.microsoft.com/api/mcp"
                    },
                    "example": {
                        "type": "stdio",
                        "command": "npx",
                        "args": ["-y", "@modelcontextprotocol/server-filesystem", "/path"]
                    }
                }
            }, indent=2)
        content = config_path.read_text("utf-8")
        return f"MCP config ({config_path}):\n{content}"

    return "Usage: /mcp [status|connect|disconnect|config]"


# ── Create Commands ──────────────────────────────────────────

def create_commands() -> dict[str, Command]:
    """Create all available slash commands."""
    commands: dict[str, Command] = {}

    defs = [
        ("help", "Show available commands", cmd_help, ["h", "?"]),
        ("exit", "Exit Noah Code", cmd_exit, ["quit", "q"]),
        ("clear", "Clear conversation history", cmd_clear, None),
        ("model", "Show/change the model", cmd_model, None),
        ("cost", "Show token usage and cost", cmd_cost, ["usage"]),
        ("version", "Show version", cmd_version, None),
        ("cd", "Show/change working directory", cmd_cwd, ["cwd"]),
        ("compact", "Compact conversation history", cmd_compact, None),
        ("verbose", "Toggle verbose mode", cmd_verbose, None),
        ("debug", "Toggle debug mode", cmd_debug, None),
        ("buddy", "Your companion pet", cmd_buddy, ["pet", "companion"]),
        ("session", "Session save/load/list", cmd_session, ["sessions"]),
        ("memory", "View/edit NOAH.md", cmd_memory, ["mem"]),
        ("doctor", "Run environment diagnostics", cmd_doctor, None),
        ("status", "Show session status", cmd_status, None),
        ("think", "Send with extended thinking", cmd_think, None),
        ("commit", "Generate commit message & commit", cmd_commit, None),
        ("review", "Review recent changes", cmd_review, None),
        ("init", "Initialize project (create NOAH.md)", cmd_init, None),
        ("brief", "Toggle brief response mode", cmd_brief, None),
        ("insights", "Show usage insights & satisfaction", cmd_insights, ["analytics"]),
        ("security-review", "Security review of changes", cmd_security_review, ["sec"]),
        ("plan", "Toggle plan mode", cmd_plan, None),
        ("tips", "Show a random tip", cmd_tips, ["tip"]),
        ("mcp", "MCP server management", cmd_mcp, None),
        ("skills", "List available skills", cmd_skills, ["skill"]),
    ]

    for name, desc, handler, aliases in defs:
        cmd = Command(name=name, description=desc, handler=handler, aliases=aliases)
        commands[name] = cmd
        if aliases:
            for alias in aliases:
                commands[alias] = cmd

    return commands


# ── Skills ────────────────────────────────────────────────────

async def cmd_skills(state: AppState, args: str, commands: dict[str, Command]) -> str | None:
    """List or manage skills."""
    from .services.skills import discover_skills

    subcmd = args.strip().split(maxsplit=1) if args else [""]
    action = subcmd[0].lower()

    if action == "" or action == "list":
        skills = discover_skills(state.cwd)
        if not skills:
            lines = ["No skills found.", ""]
            lines.append("Create a skill:")
            lines.append("  Personal: ~/.noah/skills/<name>/SKILL.md")
            lines.append("  Project:  .noah/skills/<name>/SKILL.md")
            return "\n".join(lines)

        lines = ["Available skills:", ""]
        for s in skills:
            invoke = "user-only" if s.disable_model_invocation else "auto"
            hint = f" {s.argument_hint}" if s.argument_hint else ""
            lines.append(f"  /{s.name}{hint}  ({s.source}, {invoke})")
            if s.description:
                lines.append(f"    {s.description[:80]}")
        return "\n".join(lines)

    elif action == "show":
        if len(subcmd) < 2:
            return "Usage: /skills show <name>"
        target = subcmd[1].strip().lower()
        skills = discover_skills(state.cwd)
        for s in skills:
            if s.name == target:
                return f"Skill: {s.name} ({s.source})\nDir: {s.base_dir}\n\n{s.content[:2000]}"
        return f"Skill '{target}' not found."

    elif action == "init":
        if len(subcmd) < 2:
            return "Usage: /skills init <name>"
        skill_name = subcmd[1].strip().lower()
        skill_dir = get_config_dir() / "skills" / skill_name
        skill_file = skill_dir / "SKILL.md"
        if skill_file.exists():
            return f"Skill '{skill_name}' already exists at {skill_dir}"
        skill_dir.mkdir(parents=True, exist_ok=True)
        skill_file.write_text(
            f"---\nname: {skill_name}\ndescription: Describe what this skill does\n---\n\n"
            f"# {skill_name}\n\nYour instructions here.\n",
            encoding="utf-8",
        )
        return f"Created skill template at {skill_file}"

    elif action == "import":
        # Import a skill from ~/.agents/skills/ (after npx skills add)
        from .services.skills import install_skill_from_agents_dir
        if len(subcmd) < 2:
            # List what's available to import
            from pathlib import Path
            agents_dir = Path.home() / ".agents" / "skills"
            if not agents_dir.is_dir():
                return "No skills found in ~/.agents/skills/. Run 'npx skills add <source>' first."
            available = [d.name for d in agents_dir.iterdir() if d.is_dir() and (d / "SKILL.md").exists()]
            if not available:
                return "No skills found in ~/.agents/skills/."
            return "Available to import:\n" + "\n".join(f"  {n}" for n in available) + "\n\nUsage: /skills import <name> or /skills import all"

        target = subcmd[1].strip().lower()
        if target == "all":
            from pathlib import Path
            agents_dir = Path.home() / ".agents" / "skills"
            imported = []
            for d in agents_dir.iterdir():
                if d.is_dir() and (d / "SKILL.md").exists():
                    if install_skill_from_agents_dir(d.name):
                        imported.append(d.name)
            if imported:
                return f"Imported {len(imported)} skills: {', '.join(imported)}"
            return "No skills to import."
        else:
            if install_skill_from_agents_dir(target):
                return f"Imported skill '{target}' to {get_config_dir() / 'skills' / target}"
            return f"Skill '{target}' not found in ~/.agents/skills/. Run 'npx skills add <source>' first."

    return "Usage: /skills [list|show <name>|init <name>|import [name|all]]"


def register_skill_commands(
    commands: dict[str, Command],
    skills: list,
) -> None:
    """Register discovered skills as slash commands."""
    from .services.skills import render_skill_prompt

    for skill in skills:
        if not skill.user_invocable:
            continue
        if skill.name in commands:
            continue

        def _make_handler(sk):
            async def handler(state: AppState, args: str, cmds: dict[str, Command]) -> str | None:
                prompt = render_skill_prompt(sk, args)
                state._pending_skill_prompt = prompt
                return None
            return handler

        cmd = Command(
            name=skill.name,
            description=skill.description[:80] if skill.description else "Skill",
            handler=_make_handler(skill),
        )
        commands[skill.name] = cmd


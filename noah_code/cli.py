"""CLI entry point for Noah Code."""
from __future__ import annotations

import asyncio
import logging
import os
import sys
import uuid
from typing import Any

import click

from .config import DEFAULT_MODEL, DEFAULT_BASE_URL, VERSION, get_config_dir
from .query_engine import QueryEngine
from .repl import REPL, run_print_mode
from .services.claude_api import NoahAPIClient
from .state import AppState, get_state, set_state, register_session, unregister_session
from .tools.registry import create_tool_registry

logger = logging.getLogger(__name__)


def _resolve_api_key() -> str:
    """Resolve the API key from environment or config file."""
    # Check common env vars
    for var in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "API_KEY"):
        key = os.environ.get(var, "")
        if key:
            return key

    # Check config file
    config_dir = get_config_dir()
    key_file = config_dir / "api_key"
    if key_file.exists():
        return key_file.read_text().strip()

    return ""


def _setup_logging(verbose: bool, debug: bool) -> None:
    """Configure logging."""
    if debug:
        level = logging.DEBUG
    elif verbose:
        level = logging.INFO
    else:
        level = logging.WARNING

    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def _fix_path() -> None:
    """Auto-detect common tools not in PATH and add them."""
    import shutil
    if sys.platform != "win32":
        return

    # Common install locations to check
    candidates = [
        ("node", r"C:\Program Files\nodejs"),
        ("git", r"C:\Program Files\Git\cmd"),
        ("rg", r"C:\Program Files\ripgrep"),
    ]
    for cmd, directory in candidates:
        if shutil.which(cmd) is None and os.path.isdir(directory):
            os.environ["PATH"] = directory + ";" + os.environ.get("PATH", "")
            logger.debug("Added %s to PATH", directory)


@click.command(context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option(VERSION, "-v", "--version")
@click.option(
    "-p", "--print", "print_mode",
    is_flag=True,
    help="Print mode: output response and exit (non-interactive).",
)
@click.option(
    "--model", "-m",
    default=None,
    help=f"Model to use (default: {DEFAULT_MODEL}).",
)
@click.option(
    "--api-key",
    default=None,
    envvar="OPENAI_API_KEY",
    help="API key (env: OPENAI_API_KEY).",
)
@click.option(
    "--base-url",
    default=None,
    envvar="OPENAI_BASE_URL",
    help=f"API base URL (default: {DEFAULT_BASE_URL}).",
)
@click.option(
    "--max-turns",
    default=0,
    type=int,
    help="Maximum number of agentic turns (0 = unlimited).",
)
@click.option(
    "--max-budget",
    default=0.0,
    type=float,
    help="Maximum budget in USD (0 = unlimited).",
)
@click.option(
    "--system-prompt",
    default=None,
    help="Custom system prompt (replaces default).",
)
@click.option(
    "--append-system-prompt",
    default=None,
    help="Append to the system prompt.",
)
@click.option(
    "--verbose", is_flag=True, help="Verbose output.",
)
@click.option(
    "--debug", is_flag=True, help="Debug mode with full logging.",
)
@click.option(
    "--output-format",
    type=click.Choice(["text", "json"]),
    default="text",
    help="Output format for print mode.",
)
@click.option(
    "--cwd",
    default=None,
    type=click.Path(exists=True, file_okay=False),
    help="Working directory.",
)
@click.option(
    "--permission-mode",
    type=click.Choice(["default", "acceptEdits", "dontAsk"], case_sensitive=False),
    default=None,
    help="Permission mode: default, acceptEdits, dontAsk.",
)
@click.option(
    "--dangerously-skip-permissions",
    is_flag=True,
    default=False,
    help="Bypass all permission checks. Only for sandboxes without internet.",
)
@click.option(
    "--allowed-tools",
    default=None,
    help='Pre-approve tool patterns, comma-separated. E.g. "file_edit,bash(git *)".',
)
@click.option(
    "--mcp-config",
    default=None,
    type=click.Path(exists=True),
    help="Additional MCP config file for this session only.",
)
@click.argument("prompt", nargs=-1)
def main(
    print_mode: bool,
    model: str | None,
    api_key: str | None,
    base_url: str | None,
    max_turns: int,
    max_budget: float,
    system_prompt: str | None,
    append_system_prompt: str | None,
    verbose: bool,
    debug: bool,
    output_format: str,
    cwd: str | None,
    permission_mode: str | None,
    dangerously_skip_permissions: bool,
    allowed_tools: str | None,
    mcp_config: str | None,
    prompt: tuple[str, ...],
) -> None:
    """Noah Code - An agentic coding tool powered by LLMs (OpenAI-compatible API).

    Start an interactive session, or pass a prompt for single-query mode.

    Supports any OpenAI-compatible API endpoint. Set OPENAI_API_KEY and
    optionally OPENAI_BASE_URL to point at your preferred provider.

    Examples:

        noah                       # Interactive REPL

        noah "explain this code"   # Single query (print mode)

        noah -p "fix the bug"     # Explicit print mode

        echo "query" | noah -p    # Pipe input
    """
    _setup_logging(verbose, debug)

    # Auto-detect common tools not in PATH (Node.js, etc.)
    _fix_path()

    # Resolve working directory
    work_dir = cwd or os.getcwd()
    os.chdir(work_dir)

    # Resolve API key (optional for Azure AD auth)
    resolved_key = api_key or _resolve_api_key()
    resolved_base = base_url or DEFAULT_BASE_URL
    is_azure = "openai.azure.com" in resolved_base
    if not resolved_key and not is_azure:
        click.echo(
            "Error: No API key found. Set OPENAI_API_KEY environment variable, "
            "save it to ~/.noah/api_key, or use an Azure OpenAI endpoint "
            "(auto-authenticates via Azure CLI / VS Code).",
            err=True,
        )
        sys.exit(1)

    # Build prompt from arguments or stdin
    user_prompt = " ".join(prompt) if prompt else ""

    # Check for piped input
    if not sys.stdin.isatty() and not user_prompt:
        user_prompt = sys.stdin.read().strip()
        if user_prompt:
            print_mode = True

    # If user provided a prompt without -p flag, auto-enable print mode
    if user_prompt and not print_mode:
        print_mode = True

    # Initialize state
    from .types import PermissionMode

    # Resolve permission mode
    resolved_perm_mode = PermissionMode.DEFAULT
    if dangerously_skip_permissions:
        resolved_perm_mode = PermissionMode.BYPASS
        click.echo("⚠ Permission checks bypassed (--dangerously-skip-permissions)", err=True)
    elif permission_mode:
        mode_map = {
            "default": PermissionMode.DEFAULT,
            "acceptedits": PermissionMode.ACCEPT_EDITS,
            "dontask": PermissionMode.DONT_ASK,
        }
        resolved_perm_mode = mode_map.get(permission_mode.lower(), PermissionMode.DEFAULT)

    # Parse allowed tools
    resolved_allowed_tools = []
    if allowed_tools:
        resolved_allowed_tools = [t.strip() for t in allowed_tools.split(",") if t.strip()]

    state = AppState(
        cwd=work_dir,
        session_id=str(uuid.uuid4()),
        model=model or DEFAULT_MODEL,
        verbose=verbose,
        debug=debug,
        max_turns=max_turns,
        max_budget_usd=max_budget,
        custom_system_prompt=system_prompt,
        append_system_prompt=append_system_prompt,
        api_key=resolved_key,
        base_url=base_url,
        permission_mode=resolved_perm_mode,
        allowed_tools=resolved_allowed_tools,
    )
    set_state(state)
    register_session(state)

    # Create API client
    api_client = NoahAPIClient(
        api_key=resolved_key,
        model=state.model,
        base_url=base_url,
    )

    # Create tool registry
    tool_registry = create_tool_registry()

    # Load skills (auto-import from ~/.agents/skills/ first)
    from .services.skills import discover_skills, get_skills_description, auto_import_from_agents_dir
    from .commands import register_skill_commands
    imported = auto_import_from_agents_dir()
    if imported:
        click.echo(f"Skills: imported {len(imported)} from ~/.agents/: {', '.join(imported)}", err=True)
    discovered_skills = discover_skills(work_dir)
    if discovered_skills:
        click.echo(f"Skills: {len(discovered_skills)} loaded", err=True)
    state._skills_description = get_skills_description(discovered_skills)
    state._skills = discovered_skills

    # Connect MCP servers and add their tools
    async def _setup_mcp():
        try:
            from .services.mcp_client import MCPManager
            from .tools.mcp_tool import create_mcp_tools
            mgr = MCPManager()
            conns = await mgr.connect_all(work_dir, extra_config=mcp_config)
            if conns:
                mcp_tools = create_mcp_tools(mgr)
                for t in mcp_tools:
                    tool_registry.register(t)
                state._mcp_manager = mgr
                connected = sum(1 for c in conns if c.connected)
                if connected:
                    click.echo(f"MCP: {connected} server(s), {len(mcp_tools)} tools", err=True)
        except Exception as e:
            logger.debug("MCP setup skipped: %s", e)
            click.echo(f"MCP: setup failed ({e})", err=True)

    # Create query engine
    query_engine = QueryEngine(
        api_client=api_client,
        tool_registry=tool_registry,
        state=state,
    )

    # Run — MCP setup must share the same event loop as the REPL/print mode
    # because HTTP MCP connections are tied to the async context.
    if print_mode and user_prompt:
        async def _run_print():
            await _setup_mcp()
            await run_print_mode(query_engine, state, user_prompt, output_format)
        asyncio.run(_run_print())
    elif print_mode and not user_prompt:
        click.echo("Error: No prompt provided for print mode.", err=True)
        sys.exit(1)
    else:
        # Interactive REPL
        repl = REPL(query_engine=query_engine, state=state)
        register_skill_commands(repl.commands, discovered_skills)
        async def _run_repl():
            await _setup_mcp()
            await repl.run()
        try:
            asyncio.run(_run_repl())
        except KeyboardInterrupt:
            pass


def entry_point() -> None:
    """Package entry point."""
    main()


if __name__ == "__main__":
    entry_point()

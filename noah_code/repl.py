"""REPL - Interactive terminal interface for Noah Code."""
from __future__ import annotations

import asyncio
import os
import sys
import time
from typing import Any

from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.syntax import Syntax
from rich.text import Text
from rich.theme import Theme

from .commands import Command, create_commands
from .config import VERSION
from .query_engine import QueryEngine
from .state import AppState

# Custom theme matching Noah Code style
CLAUDE_THEME = Theme({
    "info": "dim cyan",
    "warning": "magenta",
    "error": "bold red",
    "success": "bold green",
    "tool_name": "bold yellow",
    "thinking": "dim italic",
    "prompt": "bold blue",
    "cost": "dim green",
})


class REPL:
    """Interactive REPL for Noah Code."""

    def __init__(
        self,
        query_engine: QueryEngine,
        state: AppState,
    ) -> None:
        self.query_engine = query_engine
        self.state = state
        self.console = Console(theme=CLAUDE_THEME)
        self.commands = create_commands()
        self._running = False

    def print_welcome(self) -> None:
        """Print welcome banner."""
        self.console.print()

        # Show companion if hatched
        companion_line = ""
        try:
            import os as _os
            from .buddy import get_companion, render_sprite, RARITY_STARS
            uid = _os.environ.get("USER", _os.environ.get("USERNAME", "anon"))
            companion = get_companion(uid)
            if companion:
                sprite = render_sprite(companion)
                color = {"common": "dim", "uncommon": "green", "rare": "blue",
                         "epic": "magenta", "legendary": "yellow"}.get(companion.rarity, "dim")
                self.console.print(f"[{color}]{sprite}[/{color}]")
                companion_line = f"\n[dim]{companion.name} the {companion.species} is here! {RARITY_STARS[companion.rarity]}[/dim]"
        except Exception:
            pass

        self.console.print(
            Panel(
                f"[bold blue]Noah Code[/bold blue] v{VERSION} (Python)\n"
                f"[dim]Model: {self.state.model}[/dim]\n"
                f"[dim]CWD: {self.state.cwd}[/dim]{companion_line}\n\n"
                f"[dim]Type [bold]/help[/bold] for commands, or start chatting.[/dim]\n"
                f"[dim]Press [bold]Ctrl+C[/bold] to interrupt, [bold]Ctrl+D[/bold] to exit.[/dim]",
                title="[bold]Welcome[/bold]",
                border_style="blue",
            )
        )
        self.console.print()

    async def run(self) -> None:
        """Run the interactive REPL loop."""
        self._running = True
        self.print_welcome()

        while self._running:
            try:
                user_input = await self._get_input()
                if user_input is None:
                    break

                user_input = user_input.strip()
                if not user_input:
                    continue

                # Handle slash commands
                if user_input.startswith("/"):
                    await self._handle_command(user_input)
                    continue

                # Process the message
                await self._process_message(user_input)

            except KeyboardInterrupt:
                self.console.print("\n[warning]Interrupted[/warning]")
                self.query_engine.interrupt()
                continue
            except EOFError:
                break
            except SystemExit:
                break

        # Clean up MCP connections before exit
        await self._cleanup_mcp()
        self._print_goodbye()

    async def _get_input(self) -> str | None:
        """Get user input, supporting multi-line."""
        try:
            # Use prompt_toolkit for better input handling
            try:
                from prompt_toolkit import PromptSession
                from prompt_toolkit.history import FileHistory
                from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
                from prompt_toolkit.completion import Completer, Completion

                # Build slash command completer
                class SlashCompleter(Completer):
                    def __init__(self, commands):
                        self._commands = commands

                    def get_completions(self, document, complete_event):
                        text = document.text_before_cursor
                        # Only complete after /
                        if not text.startswith("/"):
                            return
                        prefix = text[1:].lower()
                        for name, cmd in sorted(self._commands.items()):
                            if name.startswith(prefix):
                                desc = cmd.description[:40] if hasattr(cmd, 'description') else ""
                                yield Completion(
                                    "/" + name,
                                    start_position=-len(text),
                                    display=f"/{name}",
                                    display_meta=desc,
                                )

                history_file = os.path.join(
                    os.path.expanduser("~"), ".noah", "repl_history"
                )
                os.makedirs(os.path.dirname(history_file), exist_ok=True)

                session = PromptSession(
                    history=FileHistory(history_file),
                    auto_suggest=AutoSuggestFromHistory(),
                    completer=SlashCompleter(self.commands),
                    multiline=False,
                )

                # Run prompt_toolkit in executor for async compat
                result = await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: session.prompt(
                        [("class:prompt", "noah> ")],
                        style=_get_prompt_style(),
                    ),
                )
                return result

            except ImportError:
                # Fallback to basic input
                loop = asyncio.get_event_loop()
                return await loop.run_in_executor(None, lambda: input("noah> "))

        except (EOFError, KeyboardInterrupt):
            return None

    async def _handle_command(self, input_text: str) -> None:
        """Handle a slash command."""
        parts = input_text[1:].split(maxsplit=1)
        cmd_name = parts[0].lower() if parts else ""
        args = parts[1] if len(parts) > 1 else ""

        cmd = self.commands.get(cmd_name)
        if not cmd:
            self.console.print(f"[error]Unknown command: /{cmd_name}[/error]")
            self.console.print("[dim]Type /help for available commands[/dim]")
            return

        try:
            result = await cmd.handler(self.state, args, self.commands)
            if result:
                # Use markup=False to prevent Rich from interpreting ASCII art
                # (e.g. buddy sprites with brackets/slashes) as markup
                self.console.print(result, markup=False, highlight=False)

            # If a skill set a pending prompt, process it as a message
            pending = getattr(self.state, '_pending_skill_prompt', None)
            if pending:
                self.state._pending_skill_prompt = None
                self.console.print(f"[dim]Running skill /{cmd_name}...[/dim]")
                await self._process_message(pending)
        except SystemExit:
            self._running = False
            raise

    async def _process_message(self, user_input: str) -> None:
        """Process a user message through the query engine."""
        self.state.is_busy = True
        self.console.print()

        # Accumulators for streaming display
        current_text = ""
        current_thinking = ""
        tool_depth = 0

        def on_text(text: str) -> None:
            nonlocal current_text
            current_text += text
            # Print incrementally
            sys.stdout.write(text)
            sys.stdout.flush()

        def on_thinking(text: str) -> None:
            nonlocal current_thinking
            if not current_thinking:
                self.console.print("[thinking]Thinking...[/thinking]", end="")
            current_thinking += text

        def on_tool_start(name: str, tool_id: str, tool_input: dict = None) -> None:
            nonlocal tool_depth
            tool_depth += 1
            if current_text:
                sys.stdout.write("\n")
                sys.stdout.flush()
            # Show tool name + key arguments
            detail = _format_tool_detail(name, tool_input or {})
            self.console.print(f"  [tool_name]⚡ {name}[/tool_name] {detail}", end="")

        def on_tool_end(name: str, tool_id: str, tool_input: dict, result: Any) -> None:
            nonlocal tool_depth
            if result and hasattr(result, "is_error") and result.is_error:
                # Show error snippet
                err = result.output[:80].replace("\n", " ") if hasattr(result, "output") else "error"
                self.console.print(f" [error]✗ {err}[/error]")
            else:
                # Show brief result summary
                summary = _format_tool_result(name, tool_input, result)
                self.console.print(f" [success]✓[/success]{summary}")
            tool_depth -= 1

        def on_error(error: str) -> None:
            self.console.print(f"\n[error]Error: {error}[/error]")

        try:
            result = await self.query_engine.submit_message(
                user_input,
                on_text=on_text,
                on_tool_start=on_tool_start,
                on_tool_end=on_tool_end,
                on_thinking=on_thinking,
                on_error=on_error,
            )

            # Print final newline after streaming text
            if current_text:
                sys.stdout.write("\n")
                sys.stdout.flush()

            # Print cost info
            if self.state.total_cost > 0 and self.state.verbose:
                self.console.print(
                    f"\n[cost]Tokens: {self.state.total_input_tokens:,}↑ "
                    f"{self.state.total_output_tokens:,}↓ "
                    f"Cost: ${self.state.total_cost:.4f}[/cost]"
                )

        except KeyboardInterrupt:
            self.console.print("\n[warning]Interrupted[/warning]")
            self.query_engine.interrupt()
        except Exception as e:
            self.console.print(f"\n[error]Error: {e}[/error]")
        finally:
            self.state.is_busy = False
            self.console.print()

    async def _cleanup_mcp(self) -> None:
        """Gracefully disconnect MCP servers and unregister session."""
        if hasattr(self.state, '_mcp_manager') and self.state._mcp_manager:
            try:
                await self.state._mcp_manager.disconnect_all()
            except Exception:
                pass
        # Unregister session PID
        from .state import unregister_session
        unregister_session()

    def _print_goodbye(self) -> None:
        """Print goodbye message with stats and auto-save session."""
        stats = self.query_engine.get_conversation_stats()

        # Auto-save session if there were any messages
        if stats["message_count"] > 0:
            try:
                from .history import save_session
                save_session(
                    self.state.session_id,
                    self.state.messages,
                    model=self.state.model,
                    total_cost=self.state.total_cost,
                    cwd=self.state.cwd,
                )
            except Exception:
                pass

        # Auto-analyze satisfaction and save insights
        satisfaction_label = ""
        try:
            from .insights import analyze_session, save_session_insight, SATISFACTION_LABELS
            insight = analyze_session(self.state.session_id, self.state.messages)
            save_session_insight(insight)
            satisfaction_label = f" | {SATISFACTION_LABELS.get(insight.satisfaction, '')}"
        except Exception:
            pass

        self.console.print()
        duration = stats.get("session_duration", 0)
        mins = int(duration // 60) if duration else 0
        self.console.print(
            Panel(
                f"[dim]Turns: {stats['turns']} | "
                f"Tokens: {stats['total_input_tokens']:,}↑ {stats['total_output_tokens']:,}↓ | "
                f"Cost: ${stats['total_cost']:.4f} | "
                f"Time: {mins}m{satisfaction_label}[/dim]",
                title="[bold]Session Saved[/bold]",
                border_style="blue",
            )
        )


def _format_tool_detail(name: str, tool_input: dict) -> str:
    """Format tool input as a concise detail string shown at execution start."""
    detail_map = {
        "bash": lambda i: f"[dim]$ {i.get('command', '')[:80]}[/dim]",
        "file_read": lambda i: f"[dim]{i.get('file_path', '')}"
                               + (f" L{i.get('start_line')}-{i.get('end_line')}" if i.get('start_line') else "")
                               + "[/dim]",
        "file_edit": lambda i: f"[dim]{i.get('file_path', '')}[/dim]",
        "file_write": lambda i: f"[dim]{i.get('file_path', '')}[/dim]",
        "glob": lambda i: f"[dim]{i.get('pattern', '')}[/dim]",
        "grep": lambda i: f"[dim]'{i.get('pattern', '')}'"
                          + (f" in {i.get('path', '')}" if i.get('path') else "")
                          + (f" --include={i.get('include')}" if i.get('include') else "")
                          + "[/dim]",
        "list_dir": lambda i: f"[dim]{i.get('path', '.')}[/dim]",
        "web_fetch": lambda i: f"[dim]{i.get('url', '')[:60]}[/dim]",
        "web_search": lambda i: f"[dim]'{i.get('query', '')}'[/dim]",
        "agent": lambda i: f"[dim]{i.get('task', i.get('prompt', ''))[:60]}[/dim]",
        "repl": lambda i: f"[dim]({i.get('language', 'python')}) {i.get('code', '').split(chr(10))[0][:50]}[/dim]",
        "notebook_edit": lambda i: f"[dim]{i.get('action', '')} {i.get('file_path', '')}[/dim]",
        "todo_write": lambda i: f"[dim]{len(i.get('todos', []))} items[/dim]",
        "sleep": lambda i: f"[dim]{i.get('seconds', 0)}s[/dim]",
        "ask_user": lambda i: f"[dim]{i.get('question', '')[:60]}[/dim]",
        "config": lambda i: f"[dim]{i.get('action', '')} {i.get('key', '')}[/dim]",
        "powershell": lambda i: f"[dim]PS> {i.get('command', '')[:70]}[/dim]",
        "task_create": lambda i: f"[dim]{i.get('description', '')[:60]}[/dim]",
        "task_stop": lambda i: f"[dim]{i.get('task_id', '')}[/dim]",
        "tool_search": lambda i: f"[dim]'{i.get('query', '')}'[/dim]",
    }
    formatter = detail_map.get(name)
    if formatter:
        try:
            return " " + formatter(tool_input)
        except Exception:
            pass
    # Fallback: show first key=value
    if tool_input:
        first_key = next(iter(tool_input))
        val = str(tool_input[first_key])[:50]
        return f" [dim]{first_key}={val}[/dim]"
    return ""


def _format_tool_result(name: str, tool_input: dict, result) -> str:
    """Format a brief result summary shown after tool completion."""
    if not result or not hasattr(result, "output"):
        return ""
    output = result.output

    # For specific tools, show a meaningful summary
    if name == "grep":
        # Extract match count
        if "Found " in output:
            count_part = output.split("\n")[0]
            return f" [dim]{count_part}[/dim]"
        if "No matches" in output:
            return " [dim]no matches[/dim]"
    elif name == "glob":
        if "Found " in output:
            count_part = output.split("\n")[0]
            return f" [dim]{count_part}[/dim]"
    elif name == "bash":
        lines = output.strip().split("\n")
        if len(lines) == 1 and len(lines[0]) < 60:
            return f" [dim]→ {lines[0]}[/dim]"
        elif len(lines) > 1:
            return f" [dim]({len(lines)} lines)[/dim]"
    elif name == "file_read":
        lines = output.strip().split("\n")
        return f" [dim]({len(lines)} lines)[/dim]"
    elif name in ("file_write", "file_edit"):
        first_line = output.split("\n")[0][:60]
        return f" [dim]{first_line}[/dim]"
    elif name == "list_dir":
        entries = [l for l in output.split("\n") if l.strip().startswith(("  ", "\t"))]
        return f" [dim]({len(entries)} entries)[/dim]"
    elif name == "repl":
        lines = output.strip().split("\n")
        if len(lines) == 1 and len(lines[0]) < 50:
            return f" [dim]→ {lines[0]}[/dim]"

    return ""


def _get_prompt_style():
    """Get prompt_toolkit style."""
    try:
        from prompt_toolkit.styles import Style
        return Style.from_dict({
            "prompt": "#6699ff bold",
        })
    except ImportError:
        return None


async def run_print_mode(
    query_engine: QueryEngine,
    state: AppState,
    prompt: str,
    output_format: str = "text",
) -> None:
    """Run in non-interactive (print) mode - single query, output result, exit."""
    console = Console(theme=CLAUDE_THEME)
    result_text = ""

    def on_text(text: str) -> None:
        nonlocal result_text
        result_text += text

    try:
        result = await query_engine.submit_message(
            prompt,
            on_text=on_text,
        )

        if result:
            if output_format == "json":
                import json
                output = {
                    "result": result_text,
                    "model": state.model,
                    "usage": {
                        "input_tokens": state.total_input_tokens,
                        "output_tokens": state.total_output_tokens,
                    },
                    "cost": state.total_cost,
                }
                print(json.dumps(output, indent=2))
            else:
                print(result_text)
        else:
            console.print("[error]No response received[/error]", file=sys.stderr)
            sys.exit(1)

    except Exception as e:
        console.print(f"[error]Error: {e}[/error]", file=sys.stderr)
        sys.exit(1)

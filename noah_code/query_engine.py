"""Query engine - manages conversation lifecycle and tool execution."""
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from typing import Any, AsyncGenerator

from .config import AUTOCOMPACT_BUFFER_TOKENS, MAX_TOOL_RESULT_CHARS
from .context import build_system_prompt
from .cost_tracker import CostTracker, TurnUsage
from .services.claude_api import NoahAPIClient, StreamEvent, UsageStats, estimate_cost
from .state import AppState, get_state
from .tool import ToolRegistry, ToolResult
from .types import (
    ContentBlock,
    Message,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
)

logger = logging.getLogger(__name__)


class QueryEngine:
    """Manages the conversation loop: sending messages, processing tool calls,
    and maintaining conversation history."""

    def __init__(
        self,
        api_client: NoahAPIClient,
        tool_registry: ToolRegistry,
        state: AppState,
    ) -> None:
        self.api_client = api_client
        self.tool_registry = tool_registry
        self.state = state
        self.cost_tracker = CostTracker()
        self._abort = False
        self._current_turn = 0
        self._compact_failures = 0

        # Session memory
        from .services.session_memory import SessionMemory
        self._session_memory = SessionMemory(
            session_id=state.session_id,
            cwd=state.cwd,
        )

    def interrupt(self) -> None:
        """Interrupt the current query."""
        self._abort = True

    async def _auto_compact_if_needed(self) -> None:
        """Check token usage and auto-compact if approaching context limit."""
        from .services.compact import should_compact, compact_with_llm

        if self._compact_failures >= 3:
            return  # Circuit breaker: stop trying after 3 failures

        if not should_compact(
            self.state.messages,
            self.state.total_input_tokens,
            self.state.total_output_tokens,
        ):
            return

        logger.info("Auto-compacting conversation (%d messages, ~%d input tokens)",
                     len(self.state.messages), self.state.total_input_tokens)

        try:
            compacted = await compact_with_llm(self.state.messages, self.api_client)
            self.state.messages = compacted
            logger.info("Auto-compact complete: %d messages remaining", len(compacted))
        except Exception as e:
            self._compact_failures += 1
            logger.error("Auto-compact failed (%d/3): %s", self._compact_failures, e)

    async def _prompt_permission(self, tool_use: ToolUseBlock, message: str) -> bool:
        """Prompt the user to approve or deny a tool call.

        Returns True if approved, False if denied.
        """
        import sys

        # Build a short summary of what the tool wants to do
        summary = tool_use.name
        cmd = tool_use.input.get("command", "")
        path = tool_use.input.get("file_path", "") or tool_use.input.get("path", "")
        if cmd:
            summary += f": {cmd[:80]}"
        elif path:
            summary += f": {path}"

        prompt_text = f"\n⚠ {message}\n  {summary}\n  Allow? [y/N] "

        loop = asyncio.get_event_loop()
        try:
            sys.stdout.write(prompt_text)
            sys.stdout.flush()
            answer = await loop.run_in_executor(None, sys.stdin.readline)
            return answer.strip().lower() in ("y", "yes")
        except (EOFError, KeyboardInterrupt):
            return False

    async def submit_message(
        self,
        user_message: str,
        on_text: Any | None = None,
        on_tool_start: Any | None = None,
        on_tool_end: Any | None = None,
        on_thinking: Any | None = None,
        on_error: Any | None = None,
    ) -> Message | None:
        """Submit a user message and process the full response including tool calls.

        Returns the final assistant message, or None if interrupted.
        """
        self._abort = False
        self._current_turn += 1
        self.state.turn_count += 1

        # Add user message
        user_msg = Message(role="user", content=user_message, timestamp=time.time())
        self.state.add_message(user_msg)

        # Run the query loop (may have multiple turns for tool use)
        return await self._query_loop(
            on_text=on_text,
            on_tool_start=on_tool_start,
            on_tool_end=on_tool_end,
            on_thinking=on_thinking,
            on_error=on_error,
        )

    async def _query_loop(
        self,
        on_text: Any | None = None,
        on_tool_start: Any | None = None,
        on_tool_end: Any | None = None,
        on_thinking: Any | None = None,
        on_error: Any | None = None,
        max_iterations: int = 50,
    ) -> Message | None:
        """Core query loop - sends messages, processes tool calls, iterates."""
        iteration = 0

        while iteration < max_iterations:
            if self._abort:
                return None

            iteration += 1

            # Auto-compact if approaching context limit
            await self._auto_compact_if_needed()

            # Build system prompt (includes session notes if available)
            session_notes = self._session_memory.get_context_for_prompt()
            system_prompt = await build_system_prompt(
                cwd=self.state.cwd,
                custom_system_prompt=self.state.custom_system_prompt,
                append_system_prompt=(self.state.append_system_prompt or "") + session_notes,
                skills_description=getattr(self.state, '_skills_description', ''),
            )

            # Prepare messages for API
            api_messages = self._prepare_messages()

            # Get tool schemas
            tools = self.tool_registry.get_api_schemas()

            # Stream the response
            assistant_text = ""
            thinking_text = ""
            tool_uses: list[ToolUseBlock] = []
            stop_reason = None
            current_tool: dict[str, Any] | None = None

            async for event in self.api_client.stream_message(
                messages=api_messages,
                system=system_prompt,
                tools=tools if tools else None,
            ):
                if self._abort:
                    return None

                if event.type == "text":
                    assistant_text += event.data
                    if on_text:
                        on_text(event.data)

                elif event.type == "thinking":
                    thinking_text += event.data
                    if on_thinking:
                        on_thinking(event.data)

                elif event.type == "tool_use_start":
                    current_tool = event.data
                    # Don't call on_tool_start here — no input yet.
                    # It's called from _execute_single_tool with full input.

                elif event.type == "tool_use":
                    tool_use = ToolUseBlock(
                        id=event.data["id"],
                        name=event.data["name"],
                        input=event.data["input"],
                    )
                    tool_uses.append(tool_use)

                elif event.type == "message_delta":
                    stop_reason = event.data.get("stop_reason")

                elif event.type == "error":
                    error_msg = event.data.get("message", "Unknown error")
                    if on_error:
                        on_error(error_msg)

                    # Handle retryable errors
                    status = event.data.get("status", 0)
                    if status == 429:
                        logger.warning("Rate limited, waiting 10 seconds...")
                        await asyncio.sleep(10)
                        continue
                    elif status == 529:
                        logger.warning("API overloaded, waiting 30 seconds...")
                        await asyncio.sleep(30)
                        continue

                    # Non-retryable error
                    error_message = Message(
                        role="assistant",
                        content=[TextBlock(text=f"Error: {error_msg}")],
                        timestamp=time.time(),
                    )
                    self.state.add_message(error_message)
                    return error_message

            # Track usage
            if self.api_client.last_usage:
                usage = self.api_client.last_usage
                self.state.total_input_tokens += usage.input_tokens
                self.state.total_output_tokens += usage.output_tokens
                self.state.total_cost += estimate_cost(usage, self.api_client.model)
                # Enhanced cost tracker
                self.cost_tracker.add_turn(TurnUsage(
                    input_tokens=usage.input_tokens,
                    output_tokens=usage.output_tokens,
                    cache_read_tokens=usage.cache_read_input_tokens,
                    cache_creation_tokens=usage.cache_creation_input_tokens,
                    model=self.api_client.model,
                ))

            # Build assistant message
            content_blocks: list[ContentBlock] = []
            if thinking_text:
                content_blocks.append(ThinkingBlock(thinking=thinking_text))
            if assistant_text:
                content_blocks.append(TextBlock(text=assistant_text))
            for tu in tool_uses:
                content_blocks.append(tu)

            assistant_msg = Message(
                role="assistant",
                content=content_blocks,
                timestamp=time.time(),
                model=self.api_client.model,
            )
            self.state.add_message(assistant_msg)

            # Check if we need to execute tools
            if stop_reason == "tool_use" and tool_uses:
                # Execute tools and add results
                tool_results = await self._execute_tools(
                    tool_uses,
                    on_tool_start=on_tool_start,
                    on_tool_end=on_tool_end,
                )

                # Track tool calls for session memory
                for _ in tool_uses:
                    self._session_memory.record_tool_call()

                # Add tool results as a user message
                result_blocks: list[ContentBlock] = []
                for tool_use, result in zip(tool_uses, tool_results):
                    content = result.output
                    # Truncate large results
                    if len(content) > MAX_TOOL_RESULT_CHARS:
                        half = MAX_TOOL_RESULT_CHARS // 2
                        content = (
                            content[:half]
                            + f"\n\n... ({len(content) - MAX_TOOL_RESULT_CHARS} chars truncated) ...\n\n"
                            + content[-half:]
                        )
                    result_blocks.append(ToolResultBlock(
                        tool_use_id=tool_use.id,
                        content=content,
                        is_error=result.is_error,
                    ))

                tool_result_msg = Message(
                    role="user",
                    content=result_blocks,
                    timestamp=time.time(),
                )
                self.state.add_message(tool_result_msg)

                # Check budget
                if self.state.max_budget_usd > 0 and self.state.total_cost >= self.state.max_budget_usd:
                    logger.warning("Budget limit reached ($%.2f)", self.state.total_cost)
                    budget_msg = Message(
                        role="assistant",
                        content=[TextBlock(text=f"Budget limit reached (${self.state.total_cost:.2f}). Stopping.")],
                        timestamp=time.time(),
                    )
                    self.state.add_message(budget_msg)
                    return budget_msg

                # Check max turns
                if self.state.max_turns > 0 and iteration >= self.state.max_turns:
                    logger.warning("Max turns reached (%d)", self.state.max_turns)
                    return assistant_msg

                # Continue the loop for the next turn
                continue

            # No tool use - we're done
            # Post-turn: update session memory in background
            await self._post_turn_hooks()
            return assistant_msg

        logger.warning("Max iterations reached (%d)", max_iterations)
        return None

    async def _execute_tools(
        self,
        tool_uses: list[ToolUseBlock],
        on_tool_start: Any | None = None,
        on_tool_end: Any | None = None,
    ) -> list[ToolResult]:
        """Execute tool calls, handling concurrency."""
        results: list[ToolResult] = []

        # Partition into concurrent (read-only) and sequential batches
        concurrent_batch: list[tuple[int, ToolUseBlock]] = []
        sequential_batch: list[tuple[int, ToolUseBlock]] = []

        for i, tu in enumerate(tool_uses):
            tool = self.tool_registry.find_by_name(tu.name)
            if tool and tool.is_concurrency_safe(tu.input):
                concurrent_batch.append((i, tu))
            else:
                sequential_batch.append((i, tu))

        # Pre-allocate results
        results = [ToolResult(output="Tool not found", is_error=True)] * len(tool_uses)

        # Execute concurrent batch in parallel
        if concurrent_batch:
            tasks = []
            for idx, tu in concurrent_batch:
                tasks.append(self._execute_single_tool(tu, on_tool_start, on_tool_end))
            concurrent_results = await asyncio.gather(*tasks, return_exceptions=True)
            for (idx, _), result in zip(concurrent_batch, concurrent_results):
                if isinstance(result, Exception):
                    results[idx] = ToolResult(output=f"Error: {result}", is_error=True)
                else:
                    results[idx] = result

        # Execute sequential batch serially
        for idx, tu in sequential_batch:
            if self._abort:
                results[idx] = ToolResult(output="Interrupted", is_error=True)
                break
            result = await self._execute_single_tool(tu, on_tool_start, on_tool_end)
            results[idx] = result

        return results

    async def _execute_single_tool(
        self,
        tool_use: ToolUseBlock,
        on_tool_start: Any | None = None,
        on_tool_end: Any | None = None,
    ) -> ToolResult:
        """Execute a single tool call."""
        tool = self.tool_registry.find_by_name(tool_use.name)
        if not tool:
            return ToolResult(
                output=f"Error: Unknown tool '{tool_use.name}'",
                is_error=True,
            )

        # Permission check
        from .services.permissions import check_permission
        from .types import PermissionBehavior
        perm = check_permission(tool, tool_use.input, self.state)

        if perm.behavior == PermissionBehavior.DENY:
            denied_msg = f"Permission denied: {perm.message}"
            logger.info("Tool %s denied: %s", tool_use.name, perm.message)
            return ToolResult(output=denied_msg, is_error=True)

        if perm.behavior == PermissionBehavior.ASK:
            # Prompt user for confirmation
            approved = await self._prompt_permission(tool_use, perm.message)
            if not approved:
                return ToolResult(
                    output=f"Tool '{tool_use.name}' was denied by user.",
                    is_error=True,
                )

        # Notify start WITH input details
        if on_tool_start:
            on_tool_start(tool_use.name, tool_use.id, tool_use.input)

        try:
            result = await tool.call(
                tool_input=tool_use.input,
                cwd=self.state.cwd,
            )
            if on_tool_end:
                on_tool_end(tool_use.name, tool_use.id, tool_use.input, result)

            # After shell commands, check for newly installed skills
            if tool_use.name in ("bash", "powershell") and not result.is_error:
                self._check_for_new_skills(result)

            # After file_write of a SKILL.md, reload skills
            if tool_use.name == "file_write" and not result.is_error:
                path = tool_use.input.get("file_path", "")
                if "SKILL.md" in path or "skills" in path.replace("\\", "/"):
                    self._reload_skills()

            return result
        except Exception as e:
            logger.error("Tool %s failed: %s", tool_use.name, e, exc_info=True)
            err_result = ToolResult(output=f"Error executing {tool_use.name}: {e}", is_error=True)
            if on_tool_end:
                on_tool_end(tool_use.name, tool_use.id, tool_use.input, err_result)
            return err_result

    def _check_for_new_skills(self, result: ToolResult) -> None:
        """Check if a shell command installed new skills and auto-import them."""
        from .services.skills import auto_import_from_agents_dir, discover_skills, get_skills_description
        from .commands import register_skill_commands

        imported = auto_import_from_agents_dir()
        if not imported:
            return

        # Reload skills and update state
        skills = discover_skills(self.state.cwd)
        self.state._skills = skills
        self.state._skills_description = get_skills_description(skills)

        # Register new skill commands on the REPL (if accessible)
        # Append import info to the tool result so the model knows
        names = ", ".join(imported)
        result.output += f"\n\n[Noah: Auto-imported {len(imported)} new skill(s): {names}. Available now via /skills.]"
        logger.info("Auto-imported skills: %s", names)

    def _reload_skills(self) -> None:
        """Reload all skills (after a SKILL.md was written)."""
        from .services.skills import discover_skills, get_skills_description

        skills = discover_skills(self.state.cwd)
        self.state._skills = skills
        self.state._skills_description = get_skills_description(skills)
        logger.info("Reloaded skills: %d total", len(skills))

    async def _post_turn_hooks(self) -> None:
        """Run after each complete turn (no more tool calls).

        - Update session memory if threshold met
        """
        try:
            if self._session_memory.should_update(self.state.total_input_tokens):
                await self._session_memory.update(
                    api_client=self.api_client,
                    tool_registry=self.tool_registry,
                    messages=self.state.messages,
                    current_input_tokens=self.state.total_input_tokens,
                )
        except Exception as e:
            logger.debug("Post-turn hooks error: %s", e)

    def _prepare_messages(self) -> list[dict[str, Any]]:
        """Prepare messages for the API call."""
        api_messages: list[dict[str, Any]] = []

        for msg in self.state.messages:
            api_msg = msg.to_api_format()
            # Filter out non-API message types
            if api_msg["role"] in ("user", "assistant"):
                api_messages.append(api_msg)

        return api_messages

    def get_conversation_stats(self) -> dict[str, Any]:
        """Get conversation statistics."""
        return {
            "turns": self.state.turn_count,
            "total_input_tokens": self.state.total_input_tokens,
            "total_output_tokens": self.state.total_output_tokens,
            "total_cost": self.state.total_cost,
            "message_count": len(self.state.messages),
            "session_duration": self.cost_tracker.session_duration,
            "cost_summary": self.cost_tracker.format_summary(),
        }

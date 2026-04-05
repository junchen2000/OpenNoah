"""Session memory — LLM-maintained structured notes for the current session.

A subagent periodically updates a session-notes markdown file with a structured
summary of what's happening. This survives auto-compaction (re-injected into
the system prompt) and provides continuity for long conversations.

Trigger: every ~5K new tokens AND 3+ tool calls since last update.
"""
from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any, TYPE_CHECKING

from ..config import get_config_dir

if TYPE_CHECKING:
    from ..services.claude_api import NoahAPIClient
    from ..tool import ToolRegistry
    from ..state import AppState

logger = logging.getLogger(__name__)

# Trigger thresholds
MIN_TOKENS_BETWEEN_UPDATES = 5_000
MIN_TOOL_CALLS_BETWEEN_UPDATES = 3

# Template for session notes
SESSION_MEMORY_TEMPLATE = """# Session Notes

## Current Task
_What is actively being worked on right now?_

## Task Specification
_What did the user ask to build/do?_

## Key Files
_Important files read or modified_

## Errors & Fixes
_Errors encountered and how they were fixed_

## Decisions Made
_Important decisions and user preferences_

## Worklog
_Step by step, what was attempted_
"""

# Prompt sent to the session memory subagent
UPDATE_PROMPT = """Based on the conversation above, update the session notes file.

Rules:
- Keep each section concise (max 10 bullet points per section)
- Focus on WHAT happened, not HOW (the code speaks for itself)
- Update existing sections rather than appending duplicates
- The "Current Task" section should reflect the LATEST work, not old tasks
- The "Worklog" should be a chronological list of actions taken

The session notes file is at: {notes_path}

Read the current file, then use file_edit to update the relevant sections.
If the file doesn't exist, create it with file_write.

CRITICAL: Respond with TEXT ONLY after your tool calls. Do NOT call any tools other than file_read and file_edit/file_write."""


class SessionMemory:
    """Manages session-scoped memory notes."""

    def __init__(self, session_id: str, cwd: str) -> None:
        self.session_id = session_id
        self.cwd = cwd
        self._notes_path = self._get_notes_path()
        self._last_update_tokens = 0
        self._last_update_tool_calls = 0
        self._tool_calls_since_update = 0
        self._enabled = True

    def _get_notes_path(self) -> Path:
        """Get path to the session notes file."""
        session_dir = get_config_dir() / "session-memory"
        session_dir.mkdir(parents=True, exist_ok=True)
        return session_dir / f"{self.session_id}.md"

    def record_tool_call(self) -> None:
        """Record that a tool call happened (for trigger counting)."""
        self._tool_calls_since_update += 1

    def should_update(self, current_input_tokens: int) -> bool:
        """Check if session memory should be updated."""
        if not self._enabled:
            return False

        token_delta = current_input_tokens - self._last_update_tokens
        has_enough_tokens = token_delta >= MIN_TOKENS_BETWEEN_UPDATES
        has_enough_tool_calls = self._tool_calls_since_update >= MIN_TOOL_CALLS_BETWEEN_UPDATES

        return has_enough_tokens and has_enough_tool_calls

    async def update(
        self,
        api_client: "NoahAPIClient",
        tool_registry: "ToolRegistry",
        messages: list[Any],
        current_input_tokens: int,
    ) -> None:
        """Update session notes using a subagent."""
        from .subagent import run_subagent, SubagentConfig

        # Initialize file if needed
        if not self._notes_path.exists():
            self._notes_path.write_text(SESSION_MEMORY_TEMPLATE, encoding="utf-8")

        # Build context: recent conversation summary (last ~20 messages)
        context_messages = self._build_context(messages)

        prompt = UPDATE_PROMPT.format(notes_path=str(self._notes_path))

        config = SubagentConfig(
            system_prompt=(
                "You are a session note-taking assistant. Your job is to maintain "
                "structured notes about the current coding session. Read the existing "
                "notes file, then update it based on the conversation context."
            ),
            max_iterations=3,
            max_tokens=2048,
            temperature=0.0,
            allowed_tools=["file_read", "file_edit", "file_write"],
        )

        try:
            logger.info("Updating session memory (tokens: %d, tool_calls: %d)",
                        current_input_tokens, self._tool_calls_since_update)

            result = await run_subagent(
                api_client=api_client,
                tool_registry=tool_registry,
                prompt=prompt,
                config=config,
                cwd=self.cwd,
                context_messages=context_messages,
            )

            if result.error:
                logger.warning("Session memory update failed: %s", result.error)
            else:
                logger.info("Session memory updated (%d iterations, %d tool calls)",
                            result.iterations, result.tool_calls)

        except Exception as e:
            logger.error("Session memory update error: %s", e)

        # Reset counters regardless of success
        self._last_update_tokens = current_input_tokens
        self._tool_calls_since_update = 0

    def _build_context(self, messages: list[Any]) -> list[dict[str, Any]]:
        """Build context messages for the subagent (recent conversation)."""
        # Take last ~20 messages, convert to API format
        recent = messages[-20:] if len(messages) > 20 else messages
        context = []

        for msg in recent:
            try:
                api_format = msg.to_api_format()
                if api_format["role"] in ("user", "assistant"):
                    # Truncate long content
                    content = api_format.get("content", "")
                    if isinstance(content, str) and len(content) > 2000:
                        content = content[:2000] + "\n... [truncated]"
                        api_format["content"] = content
                    context.append(api_format)
            except Exception:
                continue

        return context

    def get_notes(self) -> str:
        """Get the current session notes content."""
        if self._notes_path.exists():
            try:
                return self._notes_path.read_text(encoding="utf-8")
            except OSError:
                pass
        return ""

    def get_context_for_prompt(self) -> str:
        """Get session notes formatted for system prompt injection."""
        notes = self.get_notes()
        if not notes or notes == SESSION_MEMORY_TEMPLATE:
            return ""
        return f"\n# Session Notes\n\n{notes}\n"

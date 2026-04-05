"""Message compaction service."""
from __future__ import annotations

import logging
from typing import Any

from ..types import Message, TextBlock

logger = logging.getLogger(__name__)


def should_compact(messages: list[Message], token_estimate: int, threshold: int) -> bool:
    """Check if conversation should be compacted based on estimated tokens."""
    return token_estimate > threshold


def compact_messages(
    messages: list[Message],
    keep_last_n: int = 4,
) -> list[Message]:
    """Compact conversation history by summarizing older messages.

    Keeps the most recent messages and creates a summary of older ones.
    """
    if len(messages) <= keep_last_n:
        return messages

    # Split into old and recent
    old_messages = messages[:-keep_last_n]
    recent_messages = messages[-keep_last_n:]

    # Create a summary of old messages
    summary_parts = []
    tool_uses = set()
    files_mentioned = set()

    for msg in old_messages:
        if isinstance(msg.content, str):
            if msg.role == "user":
                summary_parts.append(f"User asked: {msg.content[:100]}")
        elif isinstance(msg.content, list):
            for block in msg.content:
                if isinstance(block, TextBlock) and block.text:
                    prefix = "User" if msg.role == "user" else "Assistant"
                    summary_parts.append(f"{prefix}: {block.text[:100]}")

    summary_text = (
        "[Conversation compacted]\n"
        f"Removed {len(old_messages)} older messages.\n"
        "Summary of previous context:\n"
        + "\n".join(f"- {s}" for s in summary_parts[:20])
    )

    summary_msg = Message(
        role="user",
        content=summary_text,
    )

    return [summary_msg] + recent_messages


def estimate_tokens(messages: list[Message]) -> int:
    """Rough estimate of token count for messages."""
    total_chars = 0
    for msg in messages:
        if isinstance(msg.content, str):
            total_chars += len(msg.content)
        elif isinstance(msg.content, list):
            for block in msg.content:
                if hasattr(block, "text"):
                    total_chars += len(getattr(block, "text", ""))
                elif hasattr(block, "content"):
                    content = getattr(block, "content", "")
                    if isinstance(content, str):
                        total_chars += len(content)
                elif hasattr(block, "thinking"):
                    total_chars += len(getattr(block, "thinking", ""))
    # Rough estimate: ~4 chars per token
    return total_chars // 4

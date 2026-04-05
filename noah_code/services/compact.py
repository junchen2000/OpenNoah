"""Message compaction service — auto-compact and LLM-powered summarization.

When the conversation approaches the context window limit, this service:
1. Estimates token count (hybrid: API usage + rough char/4)
2. Triggers compaction when tokens > threshold
3. Sends old messages to the LLM for a structured summary
4. Replaces old messages with the summary + keeps recent messages
"""
from __future__ import annotations

import logging
import time
from typing import Any, TYPE_CHECKING

from ..types import Message, TextBlock

if TYPE_CHECKING:
    from ..services.claude_api import NoahAPIClient

logger = logging.getLogger(__name__)

# Buffer tokens below context window to trigger compaction
AUTOCOMPACT_BUFFER_TOKENS = 13_000
# Reserved for the summary generation response
RESERVED_FOR_SUMMARY = 8_000
# Minimum recent tokens to keep after compaction
MIN_KEEP_TOKENS = 8_000
# Minimum messages to always keep
MIN_KEEP_MESSAGES = 4

# Structured summary prompt for the LLM
COMPACT_SUMMARY_PROMPT = """Your task is to create a detailed summary of the conversation so far. This summary will replace the older messages to free up context space.

Create a summary with the following sections. Be thorough — this summary is the ONLY record of what happened before.

## Summary Format

### 1. Primary Request and Intent
What did the user originally ask for? What is the overall goal?

### 2. Key Decisions and Context
Important decisions made, constraints discovered, user preferences stated.

### 3. Files Modified or Read
List files that were read or modified, with brief notes on what was done.

### 4. Errors and Fixes
Any errors encountered and how they were resolved.

### 5. Current State
What was most recently being worked on? What is the current status?

### 6. Pending Tasks
What still needs to be done?

CRITICAL: Respond with TEXT ONLY. Do NOT call any tools. Just provide the summary text."""


def estimate_tokens(messages: list[Message]) -> int:
    """Estimate token count for messages.

    Uses a hybrid approach:
    - If we have API usage stats from the last assistant turn, use that as base
    - Estimate remaining messages at ~4 chars per token
    """
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
                elif hasattr(block, "input"):
                    # Tool use blocks
                    import json
                    try:
                        total_chars += len(json.dumps(getattr(block, "input", {})))
                    except (TypeError, ValueError):
                        total_chars += 100
    # ~4 chars per token
    return total_chars // 4


def should_compact(
    messages: list[Message],
    total_input_tokens: int,
    total_output_tokens: int,
    context_window: int = 128_000,
) -> bool:
    """Check if conversation should be compacted.

    Uses API-reported token usage if available, falls back to estimation.
    """
    if len(messages) <= MIN_KEEP_MESSAGES:
        return False

    # Use API-reported usage if we have it (more accurate)
    if total_input_tokens > 0:
        token_count = total_input_tokens  # Last turn's input = conversation size
    else:
        token_count = estimate_tokens(messages)

    threshold = context_window - AUTOCOMPACT_BUFFER_TOKENS - RESERVED_FOR_SUMMARY
    return token_count > threshold


def _find_keep_index(messages: list[Message]) -> int:
    """Find the index from which to keep messages.

    Keeps at least MIN_KEEP_MESSAGES and at least MIN_KEEP_TOKENS worth.
    """
    if len(messages) <= MIN_KEEP_MESSAGES:
        return 0

    # Start from the end, count backward
    keep_tokens = 0
    keep_count = 0
    idx = len(messages)

    for i in range(len(messages) - 1, -1, -1):
        msg = messages[i]
        if isinstance(msg.content, str):
            keep_tokens += len(msg.content) // 4
        elif isinstance(msg.content, list):
            for block in msg.content:
                if hasattr(block, "text"):
                    keep_tokens += len(getattr(block, "text", "")) // 4
        keep_count += 1
        idx = i

        if keep_count >= MIN_KEEP_MESSAGES and keep_tokens >= MIN_KEEP_TOKENS:
            break

    return idx


def _build_conversation_for_summary(messages: list[Message], keep_idx: int) -> str:
    """Build a text representation of messages to be summarized."""
    parts = []
    for msg in messages[:keep_idx]:
        role = msg.role.upper()
        if isinstance(msg.content, str):
            parts.append(f"[{role}]: {msg.content}")
        elif isinstance(msg.content, list):
            for block in msg.content:
                if hasattr(block, "text") and block.text:
                    parts.append(f"[{role}]: {block.text}")
                elif hasattr(block, "name"):
                    # Tool use
                    parts.append(f"[{role} used tool {block.name}]")
                elif hasattr(block, "output"):
                    # Tool result
                    output = block.output[:500] if block.output else ""
                    parts.append(f"[TOOL RESULT]: {output}")
    return "\n\n".join(parts)


async def compact_with_llm(
    messages: list[Message],
    api_client: "NoahAPIClient",
) -> list[Message]:
    """Compact conversation using LLM to generate a structured summary.

    1. Determines which messages to keep (recent) vs summarize (old)
    2. Sends old messages to LLM for summary
    3. Returns: [summary_message] + kept_messages
    """
    keep_idx = _find_keep_index(messages)

    if keep_idx <= 1:
        logger.info("Not enough messages to compact (keep_idx=%d)", keep_idx)
        return messages

    old_count = keep_idx
    kept_messages = messages[keep_idx:]

    # Build text for summarization
    conversation_text = _build_conversation_for_summary(messages, keep_idx)

    # Truncate if too long (keep last 50K chars for summarization)
    if len(conversation_text) > 50_000:
        conversation_text = "... [earlier content truncated] ...\n\n" + conversation_text[-50_000:]

    # Ask LLM to summarize
    summary_prompt = (
        f"Here is a conversation that needs to be summarized:\n\n"
        f"<conversation>\n{conversation_text}\n</conversation>\n\n"
        f"{COMPACT_SUMMARY_PROMPT}"
    )

    try:
        logger.info("Compacting %d messages via LLM summary...", old_count)
        summary_response = await api_client.create_message(
            messages=[{"role": "user", "content": summary_prompt}],
            system="You are a conversation summarizer. Create a structured summary.",
            max_tokens=4096,
            temperature=0.0,
        )

        # Extract summary text
        summary_text = ""
        if summary_response.content:
            for block in summary_response.content:
                if hasattr(block, "text"):
                    summary_text += block.text

        if not summary_text:
            logger.warning("LLM returned empty summary, falling back to simple compact")
            return _simple_compact(messages, keep_idx)

    except Exception as e:
        logger.error("LLM compaction failed: %s, falling back to simple compact", e)
        return _simple_compact(messages, keep_idx)

    # Build the compacted message list
    boundary_text = (
        f"[Conversation compacted — {old_count} older messages summarized]\n\n"
        f"{summary_text}\n\n"
        f"---\n"
        f"Continue the conversation from where we left off. "
        f"Do not acknowledge or repeat this summary."
    )

    summary_msg = Message(
        role="user",
        content=boundary_text,
        timestamp=time.time(),
    )

    logger.info(
        "Compacted: %d messages → summary (%d chars) + %d recent messages",
        old_count, len(summary_text), len(kept_messages),
    )

    return [summary_msg] + kept_messages


def _simple_compact(messages: list[Message], keep_idx: int) -> list[Message]:
    """Fallback: simple compaction without LLM (truncates old messages)."""
    old_messages = messages[:keep_idx]
    kept_messages = messages[keep_idx:]

    summary_parts = []
    for msg in old_messages:
        if isinstance(msg.content, str):
            prefix = "User" if msg.role == "user" else "Assistant"
            summary_parts.append(f"{prefix}: {msg.content[:100]}")
        elif isinstance(msg.content, list):
            for block in msg.content:
                if isinstance(block, TextBlock) and block.text:
                    prefix = "User" if msg.role == "user" else "Assistant"
                    summary_parts.append(f"{prefix}: {block.text[:100]}")

    summary_text = (
        f"[Conversation compacted — {len(old_messages)} older messages removed]\n"
        "Summary of previous context:\n"
        + "\n".join(f"- {s}" for s in summary_parts[:20])
    )

    summary_msg = Message(
        role="user",
        content=summary_text,
        timestamp=time.time(),
    )

    return [summary_msg] + kept_messages
"""Message compaction service."""

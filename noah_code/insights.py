"""Insights and satisfaction tracking system.

Analyzes conversation sessions to extract:
- User satisfaction signals (frustrated → delighted)
- Friction points (misunderstood, wrong approach, buggy code, etc.)
- Goal achievement (fully/mostly/partially/not achieved)
- Tool usage statistics
- Session summaries and recommendations
"""
from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .config import get_config_dir
from .types import Message, TextBlock, ToolUseBlock, ToolResultBlock


# ── Satisfaction Levels ──────────────────────────────────────

SATISFACTION_LEVELS = [
    "frustrated", "dissatisfied", "neutral", "likely_satisfied",
    "satisfied", "happy", "delighted",
]

SATISFACTION_LABELS = {
    "frustrated": "😤 Frustrated",
    "dissatisfied": "😕 Dissatisfied",
    "neutral": "😐 Neutral",
    "likely_satisfied": "🙂 Likely Satisfied",
    "satisfied": "😊 Satisfied",
    "happy": "😄 Happy",
    "delighted": "🤩 Delighted",
}

# ── Friction Types ───────────────────────────────────────────

FRICTION_TYPES = {
    "misunderstood_request": "Misunderstood Request",
    "wrong_approach": "Wrong Approach",
    "buggy_code": "Buggy Code",
    "tool_failed": "Tool Failed",
    "user_rejected_action": "User Rejected Action",
    "excessive_changes": "Excessive Changes",
    "user_unclear": "User Unclear",
    "external_issue": "External Issue",
}

# ── Outcome Types ────────────────────────────────────────────

OUTCOME_LABELS = {
    "fully_achieved": "✅ Fully Achieved",
    "mostly_achieved": "🟢 Mostly Achieved",
    "partially_achieved": "🟡 Partially Achieved",
    "not_achieved": "🔴 Not Achieved",
    "unclear_from_transcript": "❓ Unclear",
}

# ── Signal Detection Patterns ────────────────────────────────

# Positive signals
HAPPY_PATTERNS = [
    r"(?i)\byay\b", r"(?i)\bgreat\b!", r"(?i)\bperfect\b!",
    r"(?i)\bamazing\b", r"(?i)\bawesome\b", r"(?i)\bexcellent\b",
    r"(?i)\blove it\b", r"(?i)\bbeautiful\b",
]
SATISFIED_PATTERNS = [
    r"(?i)\bthanks\b", r"(?i)\bthank you\b", r"(?i)\blooks good\b",
    r"(?i)\bthat works\b", r"(?i)\bnice\b", r"(?i)\bgood job\b",
    r"(?i)\b(lgtm|lg)\b",
]

# Negative signals
FRUSTRATED_PATTERNS = [
    r"(?i)\bthis is broken\b", r"(?i)\bi give up\b", r"(?i)\bstop\b!",
    r"(?i)\bwhat the\b", r"(?i)\bcompletely wrong\b",
    r"(?i)\bthis doesn't work at all\b", r"(?i)\byou keep\b",
    r"(?i)\bagain\?\b",
]
DISSATISFIED_PATTERNS = [
    r"(?i)\bthat's not right\b", r"(?i)\btry again\b",
    r"(?i)\bnot what i (asked|wanted|meant)\b", r"(?i)\bwrong\b",
    r"(?i)\bno,?\s+(i |that|this)\b", r"(?i)\bundo\b",
    r"(?i)\brevert\b", r"(?i)\bdon't\b.*\bplease\b",
]

# Continuation (neutral-positive)
CONTINUE_PATTERNS = [
    r"(?i)\bok,?\s+(now|next|let's|also|and)\b",
    r"(?i)\bnow (do|let's|can you)\b",
    r"(?i)\bnext,?\s+\b",
]


@dataclass
class SessionInsight:
    """Analysis result for a single session."""
    session_id: str = ""
    satisfaction: str = "neutral"
    friction_counts: dict[str, int] = field(default_factory=dict)
    outcome: str = "unclear_from_transcript"
    tool_counts: dict[str, int] = field(default_factory=dict)
    tool_errors: int = 0
    user_turns: int = 0
    assistant_turns: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    summary: str = ""


@dataclass
class AggregatedInsights:
    """Aggregated insights across multiple sessions."""
    total_sessions: int = 0
    satisfaction_counts: dict[str, int] = field(default_factory=dict)
    friction_counts: dict[str, int] = field(default_factory=dict)
    outcome_counts: dict[str, int] = field(default_factory=dict)
    tool_counts: dict[str, int] = field(default_factory=dict)
    total_tool_errors: int = 0
    total_user_turns: int = 0
    total_assistant_turns: int = 0
    session_summaries: list[dict[str, str]] = field(default_factory=list)


# ── Signal Detection (rule-based, no LLM needed) ────────────

def detect_satisfaction(messages: list[Message]) -> str:
    """Detect user satisfaction from message signals.

    Uses the same heuristics as the original Noah Code insights system:
    - "Yay!", "great!", "perfect!" → happy
    - "thanks", "looks good", "that works" → satisfied
    - "ok, now let's..." → likely_satisfied
    - "that's not right", "try again" → dissatisfied
    - "this is broken", "I give up" → frustrated
    """
    scores = {level: 0 for level in SATISFACTION_LEVELS}

    for msg in messages:
        if msg.role != "user":
            continue
        text = msg.text if hasattr(msg, "text") else ""
        if isinstance(msg.content, str):
            text = msg.content

        if not text:
            continue

        # Check patterns
        for pattern in HAPPY_PATTERNS:
            if re.search(pattern, text):
                scores["happy"] += 2
                scores["delighted"] += 1

        for pattern in SATISFIED_PATTERNS:
            if re.search(pattern, text):
                scores["satisfied"] += 2
                scores["likely_satisfied"] += 1

        for pattern in FRUSTRATED_PATTERNS:
            if re.search(pattern, text):
                scores["frustrated"] += 3

        for pattern in DISSATISFIED_PATTERNS:
            if re.search(pattern, text):
                scores["dissatisfied"] += 2

        for pattern in CONTINUE_PATTERNS:
            if re.search(pattern, text):
                scores["likely_satisfied"] += 1

    # Pick the highest scoring level
    if max(scores.values()) == 0:
        return "neutral"

    return max(scores, key=lambda k: scores[k])


def detect_friction(messages: list[Message]) -> dict[str, int]:
    """Detect friction points from conversation patterns."""
    friction: dict[str, int] = {}

    for i, msg in enumerate(messages):
        # Check for tool errors
        if isinstance(msg.content, list):
            for block in msg.content:
                if isinstance(block, ToolResultBlock) and block.is_error:
                    friction["tool_failed"] = friction.get("tool_failed", 0) + 1

        # Check user messages for rejection/correction signals
        if msg.role == "user":
            text = msg.text if hasattr(msg, "text") else str(msg.content)

            if re.search(r"(?i)\b(no|stop|don't|undo|revert|wrong)\b", text):
                friction["user_rejected_action"] = friction.get("user_rejected_action", 0) + 1

            if re.search(r"(?i)\bthat's not what i (meant|asked|wanted)\b", text):
                friction["misunderstood_request"] = friction.get("misunderstood_request", 0) + 1

            if re.search(r"(?i)\b(too much|over.?engineer|excessive|unnecessary)\b", text):
                friction["excessive_changes"] = friction.get("excessive_changes", 0) + 1

            if re.search(r"(?i)\b(bug|broken|doesn't work|error|crash|fail)\b", text):
                friction["buggy_code"] = friction.get("buggy_code", 0) + 1

    return friction


def count_tool_usage(messages: list[Message]) -> dict[str, int]:
    """Count tool usage from messages."""
    counts: dict[str, int] = {}
    for msg in messages:
        if isinstance(msg.content, list):
            for block in msg.content:
                if isinstance(block, ToolUseBlock):
                    counts[block.name] = counts.get(block.name, 0) + 1
    return counts


def count_tool_errors(messages: list[Message]) -> int:
    """Count tool errors from messages."""
    errors = 0
    for msg in messages:
        if isinstance(msg.content, list):
            for block in msg.content:
                if isinstance(block, ToolResultBlock) and block.is_error:
                    errors += 1
    return errors


# ── Session Analysis ─────────────────────────────────────────

def analyze_session(session_id: str, messages: list[Message]) -> SessionInsight:
    """Analyze a single session for insights."""
    user_msgs = [m for m in messages if m.role == "user"]
    asst_msgs = [m for m in messages if m.role == "assistant"]

    satisfaction = detect_satisfaction(messages)
    friction = detect_friction(messages)
    tool_counts = count_tool_usage(messages)
    tool_errors = count_tool_errors(messages)

    # Generate brief summary from first user message
    summary = ""
    for msg in user_msgs:
        text = msg.text if hasattr(msg, "text") else str(msg.content)
        if text and len(text) > 5:
            summary = text[:120].replace("\n", " ")
            break

    return SessionInsight(
        session_id=session_id,
        satisfaction=satisfaction,
        friction_counts=friction,
        tool_counts=tool_counts,
        tool_errors=tool_errors,
        user_turns=len(user_msgs),
        assistant_turns=len(asst_msgs),
        summary=summary,
    )


def aggregate_insights(sessions: list[SessionInsight]) -> AggregatedInsights:
    """Aggregate insights across multiple sessions."""
    result = AggregatedInsights(total_sessions=len(sessions))

    for s in sessions:
        # Satisfaction
        result.satisfaction_counts[s.satisfaction] = \
            result.satisfaction_counts.get(s.satisfaction, 0) + 1

        # Friction
        for k, v in s.friction_counts.items():
            result.friction_counts[k] = result.friction_counts.get(k, 0) + v

        # Tools
        for k, v in s.tool_counts.items():
            result.tool_counts[k] = result.tool_counts.get(k, 0) + v

        result.total_tool_errors += s.tool_errors
        result.total_user_turns += s.user_turns
        result.total_assistant_turns += s.assistant_turns

        if s.summary:
            result.session_summaries.append({
                "id": s.session_id[:8],
                "satisfaction": s.satisfaction,
                "summary": s.summary[:80],
            })

    return result


# ── Formatting ───────────────────────────────────────────────

def format_insights_report(data: AggregatedInsights) -> str:
    """Format insights as a readable report."""
    lines = []
    lines.append("╔══════════════════════════════════════════════╗")
    lines.append("║            Noah Code Insights                ║")
    lines.append("╚══════════════════════════════════════════════╝")
    lines.append("")
    lines.append(f"Sessions analyzed: {data.total_sessions}")
    lines.append(f"Total turns: {data.total_user_turns} user, {data.total_assistant_turns} assistant")
    lines.append("")

    # Satisfaction distribution
    lines.append("── Satisfaction ─────────────────────────────")
    total = sum(data.satisfaction_counts.values()) or 1
    for level in SATISFACTION_LEVELS:
        count = data.satisfaction_counts.get(level, 0)
        pct = count / total * 100
        bar = "█" * int(pct / 5) + "░" * (20 - int(pct / 5))
        label = SATISFACTION_LABELS.get(level, level)
        lines.append(f"  {label:<22} {bar} {count:>3} ({pct:.0f}%)")

    # Friction
    if data.friction_counts:
        lines.append("")
        lines.append("── Friction Points ──────────────────────────")
        for k, v in sorted(data.friction_counts.items(), key=lambda x: -x[1]):
            label = FRICTION_TYPES.get(k, k)
            lines.append(f"  {label:<25} {v:>3}")

    # Top tools
    if data.tool_counts:
        lines.append("")
        lines.append("── Top Tools ────────────────────────────────")
        top = sorted(data.tool_counts.items(), key=lambda x: -x[1])[:10]
        for name, count in top:
            lines.append(f"  {name:<20} {count:>5}")
        if data.total_tool_errors:
            lines.append(f"  (tool errors: {data.total_tool_errors})")

    # Recent sessions
    if data.session_summaries:
        lines.append("")
        lines.append("── Recent Sessions ──────────────────────────")
        for s in data.session_summaries[-10:]:
            emoji = SATISFACTION_LABELS.get(s["satisfaction"], "")[:2]
            lines.append(f"  {emoji} {s['id']}  {s['summary']}")

    return "\n".join(lines)


# ── Persistence ──────────────────────────────────────────────

def _insights_file() -> Path:
    return get_config_dir() / "insights.json"


def save_session_insight(insight: SessionInsight) -> None:
    """Append a session insight to the insights store."""
    path = _insights_file()
    path.parent.mkdir(parents=True, exist_ok=True)

    existing: list[dict] = []
    if path.exists():
        try:
            existing = json.loads(path.read_text("utf-8"))
        except (json.JSONDecodeError, OSError):
            existing = []

    # Remove duplicate by session_id
    existing = [e for e in existing if e.get("session_id") != insight.session_id]

    existing.append({
        "session_id": insight.session_id,
        "satisfaction": insight.satisfaction,
        "friction_counts": insight.friction_counts,
        "tool_counts": insight.tool_counts,
        "tool_errors": insight.tool_errors,
        "user_turns": insight.user_turns,
        "assistant_turns": insight.assistant_turns,
        "summary": insight.summary,
        "timestamp": time.time(),
    })

    # Keep last 200
    existing = existing[-200:]
    path.write_text(json.dumps(existing, indent=2), encoding="utf-8")


def load_all_insights() -> list[SessionInsight]:
    """Load all stored session insights."""
    path = _insights_file()
    if not path.exists():
        return []

    try:
        data = json.loads(path.read_text("utf-8"))
    except (json.JSONDecodeError, OSError):
        return []

    insights = []
    for d in data:
        insights.append(SessionInsight(
            session_id=d.get("session_id", ""),
            satisfaction=d.get("satisfaction", "neutral"),
            friction_counts=d.get("friction_counts", {}),
            tool_counts=d.get("tool_counts", {}),
            tool_errors=d.get("tool_errors", 0),
            user_turns=d.get("user_turns", 0),
            assistant_turns=d.get("assistant_turns", 0),
            summary=d.get("summary", ""),
        ))
    return insights


# ── LLM-based Facet Extraction Prompt ────────────────────────

FACET_EXTRACTION_PROMPT = """Analyze this Noah Code session and extract structured facets.

CRITICAL GUIDELINES:

1. **goal_categories**: Count ONLY what the USER explicitly asked for.
   - DO NOT count Noah's autonomous codebase exploration
   - ONLY count when user says "can you...", "please...", "I need...", "let's..."

2. **user_satisfaction_counts**: Base ONLY on explicit user signals.
   - "Yay!", "great!", "perfect!" → happy
   - "thanks", "looks good", "that works" → satisfied
   - "ok, now let's..." (continuing without complaint) → likely_satisfied
   - "that's not right", "try again" → dissatisfied
   - "this is broken", "I give up" → frustrated

3. **friction_counts**: Be specific about what went wrong.
   - misunderstood_request: Noah interpreted incorrectly
   - wrong_approach: Right goal, wrong solution method
   - buggy_code: Code didn't work correctly
   - user_rejected_action: User said no/stop to a tool call
   - excessive_changes: Over-engineered or changed too much

4. **outcome**: Overall - fully_achieved, mostly_achieved, partially_achieved, not_achieved

Respond in JSON format:
{
    "satisfaction": "one of: frustrated/dissatisfied/neutral/likely_satisfied/satisfied/happy/delighted",
    "friction_counts": {"type": count, ...},
    "outcome": "one of the outcome types",
    "brief_summary": "1-2 sentence summary of what happened"
}

SESSION:
"""

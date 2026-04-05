"""Tips service - contextual tips and suggestions for users."""
from __future__ import annotations

import random
import time
from dataclasses import dataclass
from typing import Any

TIPS = [
    {"id": "slash_commands", "text": "Use /help to see all available slash commands.", "shown_max": 2},
    {"id": "buddy", "text": "Try /buddy hatch to get your own companion pet!", "shown_max": 1},
    {"id": "session_save", "text": "Sessions are auto-saved on exit. Use /session list to see them.", "shown_max": 2},
    {"id": "memory", "text": "Use /memory to view/edit NOAH.md project instructions.", "shown_max": 2},
    {"id": "insights", "text": "Use /insights to see your usage patterns and satisfaction analytics.", "shown_max": 1},
    {"id": "brief_mode", "text": "Too verbose? Use /brief to toggle concise responses.", "shown_max": 2},
    {"id": "model_switch", "text": "Use /model <name> to switch models mid-conversation.", "shown_max": 2},
    {"id": "cost_tracking", "text": "Use /cost to see token usage and estimated cost.", "shown_max": 2},
    {"id": "compact", "text": "Long conversation? Use /compact to trim older messages.", "shown_max": 2},
    {"id": "doctor", "text": "Something wrong? Use /doctor to run diagnostics.", "shown_max": 1},
    {"id": "init", "text": "New project? Use /init to create a NOAH.md template.", "shown_max": 1},
    {"id": "pipe_input", "text": "You can pipe input: echo 'question' | noah -p", "shown_max": 1},
    {"id": "multiline", "text": "For multi-line input, paste directly into the prompt.", "shown_max": 1},
    {"id": "keyboard", "text": "Press Ctrl+C to interrupt, Ctrl+D to exit.", "shown_max": 2},
    {"id": "repl_tool", "text": "Noah can run Python/Node code directly with the REPL tool.", "shown_max": 1},
    {"id": "tool_search", "text": "Not sure which tool? Noah can search tools by keyword.", "shown_max": 1},
]


@dataclass
class TipState:
    """Track which tips have been shown."""
    shown_counts: dict[str, int]
    last_shown_at: float = 0
    min_interval: float = 300  # 5 minutes between tips

    def __init__(self):
        self.shown_counts = {}
        self.last_shown_at = 0


_state = TipState()


def get_tip() -> str | None:
    """Get a contextual tip if appropriate."""
    now = time.time()
    if now - _state.last_shown_at < _state.min_interval:
        return None

    # Filter to tips that haven't exceeded their max
    eligible = []
    for tip in TIPS:
        shown = _state.shown_counts.get(tip["id"], 0)
        if shown < tip["shown_max"]:
            eligible.append(tip)

    if not eligible:
        return None

    chosen = random.choice(eligible)
    _state.shown_counts[chosen["id"]] = _state.shown_counts.get(chosen["id"], 0) + 1
    _state.last_shown_at = now

    return f"💡 Tip: {chosen['text']}"

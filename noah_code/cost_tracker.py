"""Enhanced cost tracker with per-model pricing and cache metrics."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


# Pricing per million tokens (approximate as of 2026)
MODEL_PRICING: dict[str, dict[str, float]] = {
    # OpenAI
    "gpt-5.4": {"input": 5.0, "output": 20.0},
    "gpt-5.4-mini": {"input": 0.40, "output": 1.60},
    "gpt-5.4-nano": {"input": 0.10, "output": 0.40},
    "gpt-5.4-pro": {"input": 10.0, "output": 40.0},
    "gpt-5.3-codex": {"input": 3.0, "output": 12.0},
    "gpt-5.3-chat": {"input": 2.5, "output": 10.0},
    "gpt-5.2": {"input": 2.5, "output": 10.0},
    "gpt-5.1": {"input": 2.0, "output": 8.0},
    "gpt-5.1-codex": {"input": 2.0, "output": 8.0},
    "gpt-4o": {"input": 2.5, "output": 10.0},
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "gpt-4.1": {"input": 2.0, "output": 8.0},
    "gpt-4.1-mini": {"input": 0.40, "output": 1.60},
    "o3": {"input": 10.0, "output": 40.0},
    "o3-mini": {"input": 1.10, "output": 4.40},
    "o4-mini": {"input": 1.10, "output": 4.40},
    # Anthropic
    "claude-sonnet-4-20250514": {"input": 3.0, "output": 15.0},
    "claude-sonnet-4": {"input": 3.0, "output": 15.0},
    "claude-opus-4-20250514": {"input": 15.0, "output": 75.0},
    "claude-opus-4": {"input": 15.0, "output": 75.0},
    # Google
    "gemini-2.0-flash-001": {"input": 0.10, "output": 0.40},
    "gemini-2.5-pro": {"input": 2.50, "output": 10.0},
}

# Default for unknown models
DEFAULT_PRICING = {"input": 3.0, "output": 15.0}


@dataclass
class TurnUsage:
    """Usage stats for a single API turn."""
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0
    model: str = ""
    duration_ms: float = 0
    timestamp: float = field(default_factory=time.time)


@dataclass
class CostTracker:
    """Tracks cumulative cost across a session."""
    turns: list[TurnUsage] = field(default_factory=list)
    _session_start: float = field(default_factory=time.time)

    def add_turn(self, usage: TurnUsage) -> None:
        self.turns.append(usage)

    @property
    def total_input_tokens(self) -> int:
        return sum(t.input_tokens for t in self.turns)

    @property
    def total_output_tokens(self) -> int:
        return sum(t.output_tokens for t in self.turns)

    @property
    def total_cache_read_tokens(self) -> int:
        return sum(t.cache_read_tokens for t in self.turns)

    @property
    def total_cache_creation_tokens(self) -> int:
        return sum(t.cache_creation_tokens for t in self.turns)

    @property
    def total_cost(self) -> float:
        total = 0.0
        for t in self.turns:
            total += estimate_turn_cost(t)
        return total

    @property
    def turn_count(self) -> int:
        return len(self.turns)

    @property
    def session_duration(self) -> float:
        return time.time() - self._session_start

    def format_summary(self) -> str:
        """Format a detailed cost summary."""
        lines = []
        lines.append("Cost Summary")
        lines.append("─" * 40)
        lines.append(f"  Turns:          {self.turn_count}")
        lines.append(f"  Duration:       {self._format_duration(self.session_duration)}")
        lines.append(f"  Input tokens:   {self.total_input_tokens:,}")
        lines.append(f"  Output tokens:  {self.total_output_tokens:,}")
        if self.total_cache_read_tokens:
            lines.append(f"  Cache read:     {self.total_cache_read_tokens:,}")
        if self.total_cache_creation_tokens:
            lines.append(f"  Cache created:  {self.total_cache_creation_tokens:,}")
        lines.append(f"  Total cost:     ${self.total_cost:.4f}")
        return "\n".join(lines)

    @staticmethod
    def _format_duration(seconds: float) -> str:
        if seconds < 60:
            return f"{seconds:.0f}s"
        mins = int(seconds // 60)
        secs = int(seconds % 60)
        if mins < 60:
            return f"{mins}m {secs}s"
        hours = mins // 60
        mins = mins % 60
        return f"{hours}h {mins}m"


def estimate_turn_cost(turn: TurnUsage) -> float:
    """Estimate cost for a single turn."""
    rates = MODEL_PRICING.get(turn.model, DEFAULT_PRICING)

    input_cost = (turn.input_tokens / 1_000_000) * rates["input"]
    output_cost = (turn.output_tokens / 1_000_000) * rates["output"]
    cache_read_cost = (turn.cache_read_tokens / 1_000_000) * rates["input"] * 0.1
    cache_write_cost = (turn.cache_creation_tokens / 1_000_000) * rates["input"] * 1.25

    return input_cost + output_cost + cache_read_cost + cache_write_cost


def get_model_pricing(model: str) -> dict[str, float]:
    """Get pricing for a model."""
    return MODEL_PRICING.get(model, DEFAULT_PRICING)

"""Extract Memories service - extract and persist learnings from sessions."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from ..config import get_config_dir


def get_memory_dir() -> Path:
    """Get the auto-memory directory."""
    return get_config_dir() / "memory"


def save_memory(content: str, category: str = "general", source_session: str = "") -> Path:
    """Save a memory note."""
    mem_dir = get_memory_dir() / category
    mem_dir.mkdir(parents=True, exist_ok=True)

    timestamp = int(time.time())
    filename = f"{timestamp}.md"
    path = mem_dir / filename

    header = f"<!-- session: {source_session} -->\n" if source_session else ""
    path.write_text(f"{header}{content}\n", encoding="utf-8")
    return path


def load_memories(category: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    """Load memory notes."""
    mem_dir = get_memory_dir()
    if not mem_dir.exists():
        return []

    memories = []
    dirs = [mem_dir / category] if category else [d for d in mem_dir.iterdir() if d.is_dir()]

    for d in dirs:
        if not d.exists():
            continue
        for f in sorted(d.glob("*.md"), reverse=True)[:limit]:
            try:
                content = f.read_text("utf-8")
                memories.append({
                    "category": d.name,
                    "file": f.name,
                    "content": content[:500],
                    "path": str(f),
                })
            except OSError:
                continue

    return memories[:limit]


def get_memory_context() -> str:
    """Get memory context for system prompt injection."""
    memories = load_memories(limit=20)
    if not memories:
        return ""

    lines = ["# Auto-Memories", ""]
    for m in memories[:10]:
        content = m["content"].strip().split("\n")[0][:200]
        if content.startswith("<!--"):
            continue
        lines.append(f"- {content}")

    return "\n".join(lines) if len(lines) > 2 else ""

"""Utility functions for Noah Code."""
from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path
from typing import Any


def truncate_string(s: str, max_length: int = 1000, suffix: str = "...") -> str:
    """Truncate a string to max_length."""
    if len(s) <= max_length:
        return s
    return s[: max_length - len(suffix)] + suffix


def format_tokens(count: int) -> str:
    """Format token count for display."""
    if count < 1000:
        return str(count)
    elif count < 1_000_000:
        return f"{count / 1000:.1f}k"
    else:
        return f"{count / 1_000_000:.2f}M"


def format_cost(cost: float) -> str:
    """Format cost for display."""
    if cost < 0.01:
        return f"${cost:.4f}"
    return f"${cost:.2f}"


def is_binary_file(path: str | Path) -> bool:
    """Check if a file is binary."""
    try:
        with open(path, "rb") as f:
            chunk = f.read(8192)
        return b"\x00" in chunk
    except OSError:
        return False


def safe_relative_path(path: str | Path, base: str | Path) -> str:
    """Get a safe relative path, or return absolute if not under base."""
    try:
        return str(Path(path).relative_to(base))
    except ValueError:
        return str(path)


def hash_string(s: str) -> str:
    """Hash a string with SHA256."""
    return hashlib.sha256(s.encode()).hexdigest()


def sanitize_filename(name: str) -> str:
    """Sanitize a filename by removing unsafe characters."""
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', name)


def ensure_dir(path: str | Path) -> Path:
    """Ensure a directory exists."""
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p

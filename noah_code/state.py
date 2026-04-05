"""Application state management for Noah Code."""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from .types import Message, PermissionMode, TaskState


@dataclass
class AppState:
    """Central application state."""
    messages: list[Message] = field(default_factory=list)
    cwd: str = field(default_factory=os.getcwd)
    session_id: str = ""
    model: str = "claude-sonnet-4-20250514"
    permission_mode: PermissionMode = PermissionMode.DEFAULT
    allowed_tools: list[str] = field(default_factory=list)  # pre-approved tool patterns
    tasks: list[TaskState] = field(default_factory=list)
    total_cost: float = 0.0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    is_busy: bool = False
    verbose: bool = False
    debug: bool = False
    max_turns: int = 0  # 0 = unlimited
    max_budget_usd: float = 0.0  # 0 = unlimited
    custom_system_prompt: str | None = None
    append_system_prompt: str | None = None
    api_key: str = ""
    base_url: str | None = None

    # conversation continuity
    conversation_id: str = ""
    turn_count: int = 0
    start_time: float = field(default_factory=time.time)

    def add_message(self, msg: Message) -> None:
        self.messages.append(msg)

    def get_messages(self) -> list[Message]:
        return list(self.messages)

    def clear_messages(self) -> None:
        self.messages.clear()


_global_state: AppState | None = None


def get_state() -> AppState:
    global _global_state
    if _global_state is None:
        _global_state = AppState()
    return _global_state


def set_state(state: AppState) -> None:
    global _global_state
    _global_state = state


def reset_state() -> None:
    global _global_state
    _global_state = None


def register_session(state: AppState) -> None:
    """Register this session's PID file for concurrent tracking."""
    import json
    from .config import get_config_dir

    sessions_dir = get_config_dir() / "sessions"
    sessions_dir.mkdir(parents=True, exist_ok=True)

    pid_file = sessions_dir / f"{os.getpid()}.json"
    pid_file.write_text(json.dumps({
        "pid": os.getpid(),
        "session_id": state.session_id,
        "cwd": state.cwd,
        "model": state.model,
        "started_at": state.start_time,
    }), encoding="utf-8")


def unregister_session() -> None:
    """Remove this session's PID file."""
    from .config import get_config_dir

    pid_file = get_config_dir() / "sessions" / f"{os.getpid()}.json"
    try:
        pid_file.unlink(missing_ok=True)
    except OSError:
        pass

"""Conversation history persistence - save/resume sessions."""
from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .config import get_session_dir
from .types import Message, TextBlock, ToolUseBlock, ToolResultBlock, ThinkingBlock, ContentBlock


MAX_HISTORY_ITEMS = 100


@dataclass
class SessionMeta:
    """Metadata for a saved session."""
    session_id: str
    title: str  # first user message (truncated)
    model: str
    message_count: int
    total_cost: float
    created_at: float
    updated_at: float
    cwd: str


def _session_file(session_id: str) -> Path:
    return get_session_dir() / f"{session_id}.json"


def _serialize_message(msg: Message) -> dict[str, Any]:
    """Serialize a Message for JSON storage."""
    data: dict[str, Any] = {
        "role": msg.role,
        "id": msg.id,
        "timestamp": msg.timestamp,
        "model": msg.model,
    }
    if isinstance(msg.content, str):
        data["content"] = msg.content
    else:
        blocks = []
        for b in msg.content:
            if isinstance(b, TextBlock):
                blocks.append({"type": "text", "text": b.text})
            elif isinstance(b, ToolUseBlock):
                blocks.append({"type": "tool_use", "id": b.id, "name": b.name, "input": b.input})
            elif isinstance(b, ToolResultBlock):
                blocks.append({
                    "type": "tool_result",
                    "tool_use_id": b.tool_use_id,
                    "content": b.content,
                    "is_error": b.is_error,
                })
            elif isinstance(b, ThinkingBlock):
                blocks.append({"type": "thinking", "thinking": b.thinking})
        data["content"] = blocks
    return data


def _deserialize_message(data: dict[str, Any]) -> Message:
    """Deserialize a Message from JSON."""
    content = data.get("content", "")
    if isinstance(content, str):
        return Message(
            role=data["role"], content=content,
            id=data.get("id", ""), timestamp=data.get("timestamp", 0),
            model=data.get("model", ""),
        )
    blocks: list[ContentBlock] = []
    for b in content:
        btype = b.get("type", "")
        if btype == "text":
            blocks.append(TextBlock(text=b.get("text", "")))
        elif btype == "tool_use":
            blocks.append(ToolUseBlock(id=b.get("id", ""), name=b.get("name", ""), input=b.get("input", {})))
        elif btype == "tool_result":
            blocks.append(ToolResultBlock(
                tool_use_id=b.get("tool_use_id", ""),
                content=b.get("content", ""),
                is_error=b.get("is_error", False),
            ))
        elif btype == "thinking":
            blocks.append(ThinkingBlock(thinking=b.get("thinking", "")))
    return Message(
        role=data["role"], content=blocks,
        id=data.get("id", ""), timestamp=data.get("timestamp", 0),
        model=data.get("model", ""),
    )


def save_session(
    session_id: str,
    messages: list[Message],
    model: str = "",
    total_cost: float = 0.0,
    cwd: str = "",
) -> None:
    """Save a conversation session to disk."""
    session_dir = get_session_dir()
    session_dir.mkdir(parents=True, exist_ok=True)

    # Generate title from first user message
    title = ""
    for msg in messages:
        if msg.role == "user":
            text = msg.text if hasattr(msg, "text") else str(msg.content)
            title = text[:80].replace("\n", " ")
            break
    title = title or "Untitled session"

    now = time.time()
    meta = SessionMeta(
        session_id=session_id,
        title=title,
        model=model,
        message_count=len(messages),
        total_cost=total_cost,
        created_at=messages[0].timestamp if messages else now,
        updated_at=now,
        cwd=cwd,
    )

    data = {
        "meta": {
            "session_id": meta.session_id,
            "title": meta.title,
            "model": meta.model,
            "message_count": meta.message_count,
            "total_cost": meta.total_cost,
            "created_at": meta.created_at,
            "updated_at": meta.updated_at,
            "cwd": meta.cwd,
        },
        "messages": [_serialize_message(m) for m in messages],
    }

    path = _session_file(session_id)
    path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")


def load_session(session_id: str) -> tuple[SessionMeta | None, list[Message]]:
    """Load a session from disk."""
    path = _session_file(session_id)
    if not path.exists():
        return None, []

    try:
        data = json.loads(path.read_text("utf-8"))
    except (json.JSONDecodeError, OSError):
        return None, []

    meta_data = data.get("meta", {})
    meta = SessionMeta(**meta_data)
    messages = [_deserialize_message(m) for m in data.get("messages", [])]
    return meta, messages


def list_sessions() -> list[SessionMeta]:
    """List all saved sessions, newest first."""
    session_dir = get_session_dir()
    if not session_dir.exists():
        return []

    sessions = []
    for path in session_dir.glob("*.json"):
        try:
            data = json.loads(path.read_text("utf-8"))
            meta_data = data.get("meta", {})
            sessions.append(SessionMeta(**meta_data))
        except (json.JSONDecodeError, OSError, TypeError):
            continue

    sessions.sort(key=lambda s: s.updated_at, reverse=True)
    return sessions[:MAX_HISTORY_ITEMS]


def delete_session(session_id: str) -> bool:
    """Delete a saved session."""
    path = _session_file(session_id)
    if path.exists():
        path.unlink()
        return True
    return False

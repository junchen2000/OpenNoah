"""Core type definitions for Noah Code."""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class MessageRole(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class ContentBlockType(str, Enum):
    TEXT = "text"
    TOOL_USE = "tool_use"
    TOOL_RESULT = "tool_result"
    THINKING = "thinking"
    IMAGE = "image"


@dataclass
class TextBlock:
    type: str = "text"
    text: str = ""


@dataclass
class ToolUseBlock:
    type: str = "tool_use"
    id: str = ""
    name: str = ""
    input: dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolResultBlock:
    type: str = "tool_result"
    tool_use_id: str = ""
    content: str | list[dict[str, Any]] = ""
    is_error: bool = False


@dataclass
class ThinkingBlock:
    type: str = "thinking"
    thinking: str = ""


ContentBlock = TextBlock | ToolUseBlock | ToolResultBlock | ThinkingBlock


@dataclass
class Message:
    role: str
    content: list[ContentBlock] | str
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: float = 0.0
    model: str = ""

    @property
    def text(self) -> str:
        if isinstance(self.content, str):
            return self.content
        texts = []
        for block in self.content:
            if isinstance(block, TextBlock):
                texts.append(block.text)
        return "\n".join(texts)

    @property
    def tool_uses(self) -> list[ToolUseBlock]:
        if isinstance(self.content, str):
            return []
        return [b for b in self.content if isinstance(b, ToolUseBlock)]

    def to_api_format(self) -> dict[str, Any]:
        if isinstance(self.content, str):
            return {"role": self.role, "content": self.content}
        blocks = []
        for block in self.content:
            if isinstance(block, TextBlock):
                blocks.append({"type": "text", "text": block.text})
            elif isinstance(block, ToolUseBlock):
                blocks.append({
                    "type": "tool_use",
                    "id": block.id,
                    "name": block.name,
                    "input": block.input,
                })
            elif isinstance(block, ToolResultBlock):
                blocks.append({
                    "type": "tool_result",
                    "tool_use_id": block.tool_use_id,
                    "content": block.content if isinstance(block.content, str) else block.content,
                    "is_error": block.is_error,
                })
            elif isinstance(block, ThinkingBlock):
                blocks.append({"type": "thinking", "thinking": block.thinking})
        return {"role": self.role, "content": blocks}


class PermissionMode(str, Enum):
    DEFAULT = "default"
    PLAN = "plan"
    BYPASS = "bypassPermissions"
    ACCEPT_EDITS = "acceptEdits"
    DONT_ASK = "dontAsk"
    AUTO = "auto"


class PermissionBehavior(str, Enum):
    ALLOW = "allow"
    DENY = "deny"
    ASK = "ask"


@dataclass
class PermissionResult:
    behavior: PermissionBehavior
    message: str = ""


class TaskType(str, Enum):
    LOCAL_BASH = "local_bash"
    LOCAL_AGENT = "local_agent"


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    KILLED = "killed"


@dataclass
class TaskState:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    type: TaskType = TaskType.LOCAL_BASH
    status: TaskStatus = TaskStatus.PENDING
    description: str = ""
    output: str = ""


@dataclass
class ToolProgress:
    tool_use_id: str = ""
    data: dict[str, Any] = field(default_factory=dict)

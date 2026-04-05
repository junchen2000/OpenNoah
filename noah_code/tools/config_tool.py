"""Config tool - view/manage configuration."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from ..config import get_config_dir
from ..tool import Tool, ToolResult


class ConfigTool(Tool):
    """View or update Noah Code configuration."""

    name = "config"
    description_text = (
        "View or modify Noah Code configuration settings. "
        "Can read/write settings from the config directory."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["get", "set", "list"],
                "description": "Action: get a value, set a value, or list all.",
            },
            "key": {"type": "string", "description": "Config key (for get/set)."},
            "value": {"type": "string", "description": "Value to set (for set)."},
        },
        "required": ["action"],
    }

    def is_read_only(self, tool_input: dict[str, Any]) -> bool:
        return tool_input.get("action") in ("get", "list")

    def is_concurrency_safe(self, tool_input: dict[str, Any]) -> bool:
        return self.is_read_only(tool_input)

    async def call(
        self, tool_input: dict[str, Any], cwd: str,
        on_progress: Callable[[dict[str, Any]], None] | None = None,
    ) -> ToolResult:
        action = tool_input.get("action", "list")
        config_path = get_config_dir() / "config.json"

        config: dict[str, Any] = {}
        if config_path.exists():
            try:
                config = json.loads(config_path.read_text("utf-8"))
            except (json.JSONDecodeError, OSError):
                config = {}

        if action == "list":
            if not config:
                return ToolResult(output="No configuration set.")
            lines = [f"  {k}: {json.dumps(v)}" for k, v in sorted(config.items())]
            return ToolResult(output="Configuration:\n" + "\n".join(lines))

        elif action == "get":
            key = tool_input.get("key", "")
            if not key:
                return ToolResult(output="Error: key required", is_error=True)
            val = config.get(key)
            if val is None:
                return ToolResult(output=f"{key}: (not set)")
            return ToolResult(output=f"{key}: {json.dumps(val)}")

        elif action == "set":
            key = tool_input.get("key", "")
            value = tool_input.get("value", "")
            if not key:
                return ToolResult(output="Error: key required", is_error=True)
            try:
                config[key] = json.loads(value)
            except json.JSONDecodeError:
                config[key] = value
            config_path.parent.mkdir(parents=True, exist_ok=True)
            config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")
            return ToolResult(output=f"Set {key} = {json.dumps(config[key])}")

        return ToolResult(output=f"Unknown action: {action}", is_error=True)

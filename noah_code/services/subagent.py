"""Subagent runner — fork isolated LLM conversations for background tasks.

A subagent gets:
- Its own system prompt and message history
- Optionally restricted tools (e.g., read-only for memory extraction)
- A mini query loop with limited iterations
- Results returned to the caller

Used for:
- Session memory maintenance (structured notes updated periodically)
- Background memory extraction (durable learnings after each turn)
- Skill execution in fork mode (future)
"""
from __future__ import annotations

import asyncio
import json
import logging
import sys
import time
from dataclasses import dataclass, field
from typing import Any, TYPE_CHECKING

from ..types import Message, TextBlock, ToolUseBlock, ToolResultBlock

if TYPE_CHECKING:
    from ..services.claude_api import NoahAPIClient
    from ..tool import Tool, ToolRegistry

logger = logging.getLogger(__name__)


@dataclass
class SubagentConfig:
    """Configuration for a subagent."""
    system_prompt: str = ""
    max_iterations: int = 5
    max_tokens: int = 4096
    temperature: float = 0.0
    # Tool restrictions: if set, only these tool names are allowed
    allowed_tools: list[str] | None = None
    # If True, only read-only tools are allowed
    read_only: bool = False
    # Overall timeout in seconds (0 = no timeout)
    timeout: float = 120.0


@dataclass
class SubagentResult:
    """Result from a subagent execution."""
    text: str = ""
    tool_calls: int = 0
    iterations: int = 0
    error: str = ""


async def run_subagent(
    api_client: "NoahAPIClient",
    tool_registry: "ToolRegistry",
    prompt: str,
    config: SubagentConfig | None = None,
    cwd: str = "",
    context_messages: list[dict[str, Any]] | None = None,
) -> SubagentResult:
    """Run a subagent with isolated context.

    Args:
        api_client: The API client to use
        tool_registry: Available tools
        prompt: The task/prompt for the subagent
        config: Subagent configuration
        cwd: Working directory for tool execution
        context_messages: Optional prior messages to include for context
    """
    cfg = config or SubagentConfig()
    result = SubagentResult()

    # Build tool schemas (filtered by config)
    tools = _get_filtered_tools(tool_registry, cfg)
    tool_schemas = [t.to_api_schema() for t in tools] if tools else None

    # Build messages
    messages: list[dict[str, Any]] = []
    if context_messages:
        messages.extend(context_messages)
    messages.append({"role": "user", "content": prompt})

    system = cfg.system_prompt or "You are a helpful assistant. Complete the task and respond concisely."

    for iteration in range(cfg.max_iterations):
        result.iterations = iteration + 1

        try:
            response = await api_client.create_message(
                messages=messages,
                system=system,
                tools=tool_schemas,
                max_tokens=cfg.max_tokens,
                temperature=cfg.temperature,
            )
        except Exception as e:
            result.error = str(e)
            logger.error("Subagent API call failed: %s", e)
            break

        # Extract text and tool calls
        assistant_text = ""
        tool_uses = []

        for block in response.content:
            if isinstance(block, TextBlock):
                assistant_text += block.text
            elif isinstance(block, ToolUseBlock):
                tool_uses.append(block)

        # Add assistant message to history
        messages.append({"role": "assistant", "content": _serialize_content(response.content)})

        if not tool_uses:
            # No tool calls — subagent is done
            result.text = assistant_text
            logger.info("Subagent finished (iter %d): %s", iteration + 1, assistant_text[:200])
            break

        # Execute tool calls
        tool_results = []
        for tu in tool_uses:
            result.tool_calls += 1
            _input_summary = json.dumps(tu.input, ensure_ascii=False)[:200]
            logger.info("Subagent tool call [%d/%d]: %s(%s)",
                        iteration + 1, cfg.max_iterations, tu.name, _input_summary)
            # Print to stderr so the user can see subagent activity
            print(f"    ⚡ {tu.name}  {_input_summary}", file=sys.stderr, flush=True)
            tool_result = await _execute_tool(tu, tools, cwd)
            logger.info("Subagent tool result [%s]: %s", tu.name, tool_result[:300])
            _result_preview = tool_result[:120].replace("\n", " ")
            print(f"      → {_result_preview}", file=sys.stderr, flush=True)
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": tu.id,
                "content": tool_result,
            })

        # Add tool results as user message
        messages.append({"role": "user", "content": tool_results})

    if not result.text and not result.error:
        result.text = "(subagent completed without text output)"

    return result


def _get_filtered_tools(
    registry: "ToolRegistry",
    config: SubagentConfig,
) -> list["Tool"]:
    """Get tools filtered by subagent config."""
    all_tools = registry.get_all()

    if config.allowed_tools is not None:
        allowed = set(config.allowed_tools)
        return [t for t in all_tools if t.name in allowed]

    if config.read_only:
        # Only tools that are always read-only
        read_only_names = {
            "file_read", "glob", "grep", "list_dir",
            "web_fetch", "web_search", "tool_search",
        }
        return [t for t in all_tools if t.name in read_only_names]

    return all_tools


async def _execute_tool(
    tool_use: ToolUseBlock,
    tools: list["Tool"],
    cwd: str,
) -> str:
    """Execute a single tool call for the subagent."""
    tool = None
    for t in tools:
        if t.name == tool_use.name:
            tool = t
            break

    if not tool:
        return f"Error: tool '{tool_use.name}' not available in this subagent"

    try:
        result = await tool.call(tool_input=tool_use.input, cwd=cwd)
        return result.output
    except Exception as e:
        return f"Error: {e}"


def _serialize_content(content: list) -> list[dict[str, Any]]:
    """Serialize content blocks for API message format."""
    serialized = []
    for block in content:
        if isinstance(block, TextBlock):
            serialized.append({"type": "text", "text": block.text})
        elif isinstance(block, ToolUseBlock):
            serialized.append({
                "type": "tool_use",
                "id": block.id,
                "name": block.name,
                "input": block.input,
            })
    return serialized

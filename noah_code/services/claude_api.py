"""API client - OpenAI-compatible chat completions interface."""
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator, Optional

import aiohttp

from ..config import (
    DEFAULT_MODEL,
    DEFAULT_BASE_URL,
    MAX_OUTPUT_TOKENS,
)
from ..types import (
    ContentBlock,
    Message,
    TextBlock,
    ThinkingBlock,
    ToolUseBlock,
)

logger = logging.getLogger(__name__)


@dataclass
class UsageStats:
    """Token usage statistics."""
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass
class StreamEvent:
    """Event from the streaming API."""
    type: str  # "text", "tool_use", "thinking", "message_start", "message_stop", "error"
    data: Any = None


class NoahAPIClient:
    """Client for any OpenAI-compatible chat completions API."""

    def __init__(
        self,
        api_key: str = "",
        model: str = DEFAULT_MODEL,
        base_url: str | None = None,
        max_tokens: int = MAX_OUTPUT_TOKENS,
    ) -> None:
        self.base_url = (base_url or DEFAULT_BASE_URL).rstrip("/")
        self.api_key = api_key
        self.model = model
        self.max_tokens = max_tokens
        self.last_usage: UsageStats | None = None
        # Detect Azure OpenAI by URL pattern
        self.is_azure = "openai.azure.com" in self.base_url
        # Azure AD credential (lazy init, pinned to startup tenant)
        self._azure_credential = None
        self._azure_token: str = ""
        self._azure_token_expires: float = 0
        self._azure_tenant_id: str | None = None  # Pinned at first auth

    async def _get_azure_ad_token(self) -> str:
        """Get an Azure AD bearer token for Cognitive Services.

        IMPORTANT: This pins to the tenant active at first auth. Skills that
        run 'az login --tenant X' for other resources won't affect LLM calls.

        Uses (in order):
        - Environment variables (AZURE_CLIENT_ID/SECRET/TENANT_ID)
        - Azure CLI credential pinned to the initial tenant
        - VS Code credential
        """
        import time as _time
        # Return cached token if still valid (5 min buffer)
        if self._azure_token and _time.time() < self._azure_token_expires - 300:
            return self._azure_token

        if self._azure_credential is None:
            self._azure_credential = self._create_pinned_credential()

        # Run the sync get_token in a thread to avoid blocking
        import asyncio
        token_obj = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: self._azure_credential.get_token("https://cognitiveservices.azure.com/.default"),
        )
        self._azure_token = token_obj.token
        self._azure_token_expires = token_obj.expires_on
        return self._azure_token

    def _create_pinned_credential(self):
        """Create an Azure credential pinned to the current tenant.

        Captures the tenant ID from the current az CLI session at first call,
        then uses it for all subsequent token requests — immune to az login changes.
        """
        from azure.identity import ChainedTokenCredential, AzureCLICredential, VisualStudioCodeCredential

        # Check for explicit tenant from env
        import os
        tenant = os.environ.get("AZURE_TENANT_ID")

        if not tenant:
            # Discover current tenant from az CLI
            tenant = self._get_current_az_tenant()

        if tenant:
            self._azure_tenant_id = tenant
            logger.info("Azure auth pinned to tenant: %s", tenant)
            return ChainedTokenCredential(
                AzureCLICredential(tenant_id=tenant),
                VisualStudioCodeCredential(tenant_id=tenant),
            )
        else:
            # Fallback to default chain
            from azure.identity import DefaultAzureCredential
            return DefaultAzureCredential()

    @staticmethod
    def _get_current_az_tenant() -> str | None:
        """Get the current Azure CLI tenant ID (synchronous, one-time)."""
        import subprocess
        try:
            result = subprocess.run(
                ["az", "account", "show", "--query", "tenantId", "-o", "tsv"],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip()
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
        return None

    def _build_url(self) -> str:
        """Build the chat completions endpoint URL."""
        if self.is_azure:
            base = self.base_url.rstrip("/")
            if "/deployments/" in base:
                return f"{base}/chat/completions?api-version=2024-12-01-preview"
            return f"{base}/openai/deployments/{self.model}/chat/completions?api-version=2024-12-01-preview"
        base = self.base_url.rstrip("/")
        if base.endswith("/v1"):
            return f"{base}/chat/completions"
        return f"{base}/v1/chat/completions"

    async def _build_headers(self, stream: bool = False) -> dict[str, str]:
        """Build request headers. Azure uses AD bearer token or api-key."""
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if stream:
            headers["Accept"] = "text/event-stream"
        if self.is_azure:
            if self.api_key:
                # API key auth (if enabled on the resource)
                headers["api-key"] = self.api_key
            else:
                # Azure AD token auth
                token = await self._get_azure_ad_token()
                headers["Authorization"] = f"Bearer {token}"
        elif self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    # ── Message format conversion helpers ────────────────────────────

    @staticmethod
    def _anthropic_tools_to_openai(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Convert Anthropic tool schemas to OpenAI function-calling format."""
        openai_tools = []
        for t in tools:
            openai_tools.append({
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t.get("description", ""),
                    "parameters": t.get("input_schema", {"type": "object", "properties": {}}),
                },
            })
        return openai_tools

    @staticmethod
    def _anthropic_messages_to_openai(
        messages: list[dict[str, Any]],
        system: str = "",
    ) -> list[dict[str, Any]]:
        """Convert Anthropic-format messages to OpenAI chat format.

        Anthropic has structured content blocks; OpenAI uses content strings
        and separate tool_calls / tool role messages.
        """
        oai_messages: list[dict[str, Any]] = []

        # Prepend system message
        if system:
            oai_messages.append({"role": "system", "content": system})

        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content")

            if isinstance(content, str):
                oai_messages.append({"role": role, "content": content})
                continue

            if not isinstance(content, list):
                oai_messages.append({"role": role, "content": str(content) if content else ""})
                continue

            # Structured content blocks — need to split into OpenAI format
            if role == "assistant":
                # Collect text and tool_calls from this assistant message
                text_parts: list[str] = []
                tool_calls: list[dict[str, Any]] = []
                for block in content:
                    btype = block.get("type", "")
                    if btype == "text":
                        text_parts.append(block.get("text", ""))
                    elif btype == "thinking":
                        # Include thinking as text prefix (OpenAI has no thinking block)
                        pass
                    elif btype == "tool_use":
                        tool_calls.append({
                            "id": block.get("id", f"call_{uuid.uuid4().hex[:8]}"),
                            "type": "function",
                            "function": {
                                "name": block.get("name", ""),
                                "arguments": json.dumps(block.get("input", {})),
                            },
                        })

                assistant_msg: dict[str, Any] = {"role": "assistant"}
                combined_text = "\n".join(text_parts)
                if combined_text:
                    assistant_msg["content"] = combined_text
                else:
                    assistant_msg["content"] = None
                if tool_calls:
                    assistant_msg["tool_calls"] = tool_calls
                oai_messages.append(assistant_msg)

            elif role == "user":
                # User messages may contain tool_result blocks
                text_parts_u: list[str] = []
                tool_results: list[dict[str, Any]] = []
                for block in content:
                    btype = block.get("type", "")
                    if btype == "text":
                        text_parts_u.append(block.get("text", ""))
                    elif btype == "tool_result":
                        tool_results.append(block)
                    else:
                        # Unknown block, stringify
                        text_parts_u.append(str(block))

                # Emit tool result messages first (OpenAI "tool" role)
                for tr in tool_results:
                    tr_content = tr.get("content", "")
                    if isinstance(tr_content, list):
                        tr_content = "\n".join(
                            b.get("text", str(b)) for b in tr_content
                        )
                    oai_messages.append({
                        "role": "tool",
                        "tool_call_id": tr.get("tool_use_id", ""),
                        "content": str(tr_content),
                    })

                # If there's also plain text from the user, add that
                combined_u = "\n".join(text_parts_u)
                if combined_u:
                    oai_messages.append({"role": "user", "content": combined_u})
            else:
                oai_messages.append({"role": role, "content": str(content)})

        return oai_messages

    # ── API calls ────────────────────────────────────────────────────

    async def stream_message(
        self,
        messages: list[dict[str, Any]],
        system: str = "",
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
        stop_sequences: list[str] | None = None,
    ) -> AsyncGenerator[StreamEvent, None]:
        """Stream a message response via OpenAI-compatible SSE format."""
        oai_messages = self._anthropic_messages_to_openai(messages, system)

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": oai_messages,
            "stream": True,
            "stream_options": {"include_usage": True},
        }

        if max_tokens or self.max_tokens:
            payload["max_completion_tokens"] = max_tokens or self.max_tokens

        if temperature is not None:
            payload["temperature"] = temperature

        if stop_sequences:
            payload["stop"] = stop_sequences

        if tools:
            payload["tools"] = self._anthropic_tools_to_openai(tools)
            payload["tool_choice"] = "auto"

        url = self._build_url()
        headers = await self._build_headers(stream=True)

        accumulated_usage = UsageStats()

        # Track tool calls being assembled across SSE chunks
        pending_tool_calls: dict[int, dict[str, Any]] = {}
        current_content = ""

        try:
            timeout = aiohttp.ClientTimeout(total=300)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(url, headers=headers, json=payload) as resp:
                    if resp.status != 200:
                        error_body = await resp.text()
                        logger.error("Copilot Proxy error: %s %s", resp.status, error_body)
                        yield StreamEvent(type="error", data={
                            "status": resp.status,
                            "message": error_body,
                            "error_type": "APIError",
                        })
                        return

                    yield StreamEvent(type="message_start", data=None)

                    # Parse SSE stream
                    async for raw_line in resp.content:
                        line = raw_line.decode("utf-8", errors="replace").strip()

                        if not line or not line.startswith("data: "):
                            continue

                        data_str = line[6:]  # strip "data: "
                        if data_str == "[DONE]":
                            break

                        try:
                            chunk = json.loads(data_str)
                        except json.JSONDecodeError:
                            continue

                        # Extract usage if present
                        usage = chunk.get("usage")
                        if usage:
                            accumulated_usage.input_tokens = usage.get("prompt_tokens", 0)
                            accumulated_usage.output_tokens = usage.get("completion_tokens", 0)

                        choices = chunk.get("choices", [])
                        if not choices:
                            continue

                        delta = choices[0].get("delta", {})
                        finish_reason = choices[0].get("finish_reason")

                        # Text content
                        if delta.get("content"):
                            yield StreamEvent(type="text", data=delta["content"])
                            current_content += delta["content"]

                        # Tool calls (streamed incrementally)
                        if delta.get("tool_calls"):
                            for tc_delta in delta["tool_calls"]:
                                idx = tc_delta.get("index", 0)
                                if idx not in pending_tool_calls:
                                    # New tool call starting
                                    tc_id = tc_delta.get("id", f"call_{uuid.uuid4().hex[:8]}")
                                    tc_name = tc_delta.get("function", {}).get("name", "")
                                    pending_tool_calls[idx] = {
                                        "id": tc_id,
                                        "name": tc_name,
                                        "arguments": "",
                                    }
                                    if tc_name:
                                        yield StreamEvent(type="tool_use_start", data={
                                            "id": tc_id,
                                            "name": tc_name,
                                        })

                                # Accumulate arguments
                                arg_chunk = tc_delta.get("function", {}).get("arguments", "")
                                if arg_chunk:
                                    pending_tool_calls[idx]["arguments"] += arg_chunk
                                    yield StreamEvent(type="tool_use_delta", data=arg_chunk)

                                # Also update name if it arrives later
                                incoming_name = tc_delta.get("function", {}).get("name")
                                if incoming_name and not pending_tool_calls[idx]["name"]:
                                    pending_tool_calls[idx]["name"] = incoming_name
                                    yield StreamEvent(type="tool_use_start", data={
                                        "id": pending_tool_calls[idx]["id"],
                                        "name": incoming_name,
                                    })

                        # Finish reason
                        if finish_reason:
                            # Emit completed tool calls
                            for idx in sorted(pending_tool_calls):
                                tc = pending_tool_calls[idx]
                                try:
                                    args = json.loads(tc["arguments"]) if tc["arguments"] else {}
                                except json.JSONDecodeError:
                                    args = {}
                                yield StreamEvent(type="tool_use", data={
                                    "id": tc["id"],
                                    "name": tc["name"],
                                    "input": args,
                                })

                            # Map OpenAI finish_reason to Anthropic stop_reason
                            stop_map = {
                                "stop": "end_turn",
                                "tool_calls": "tool_use",
                                "length": "max_tokens",
                                "content_filter": "end_turn",
                            }
                            yield StreamEvent(type="message_delta", data={
                                "stop_reason": stop_map.get(finish_reason, finish_reason),
                            })

                    yield StreamEvent(type="message_stop")

        except aiohttp.ClientError as e:
            yield StreamEvent(type="error", data={
                "message": f"Connection error: {e}",
                "error_type": "ConnectionError",
            })
        except asyncio.TimeoutError:
            yield StreamEvent(type="error", data={
                "message": "Request timed out",
                "error_type": "TimeoutError",
            })

        self.last_usage = accumulated_usage

    async def create_message(
        self,
        messages: list[dict[str, Any]],
        system: str = "",
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
        stop_sequences: list[str] | None = None,
    ) -> Message:
        """Create a message (non-streaming)."""
        oai_messages = self._anthropic_messages_to_openai(messages, system)

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": oai_messages,
            "stream": False,
        }
        if max_tokens or self.max_tokens:
            payload["max_completion_tokens"] = max_tokens or self.max_tokens
        if temperature is not None:
            payload["temperature"] = temperature
        if stop_sequences:
            payload["stop"] = stop_sequences
        if tools:
            payload["tools"] = self._anthropic_tools_to_openai(tools)
            payload["tool_choice"] = "auto"

        url = self._build_url()
        headers = await self._build_headers()

        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=payload) as resp:
                if resp.status != 200:
                    error_body = await resp.text()
                    raise RuntimeError(f"API error {resp.status}: {error_body}")
                data = await resp.json()

        return self._openai_response_to_message(data)

    @staticmethod
    def _openai_response_to_message(data: dict[str, Any]) -> Message:
        """Convert OpenAI chat completion response to internal Message."""
        content_blocks: list[ContentBlock] = []
        choice = data.get("choices", [{}])[0]
        msg = choice.get("message", {})

        # Text content
        if msg.get("content"):
            content_blocks.append(TextBlock(text=msg["content"]))

        # Tool calls
        for tc in msg.get("tool_calls", []):
            func = tc.get("function", {})
            try:
                args = json.loads(func.get("arguments", "{}"))
            except json.JSONDecodeError:
                args = {}
            content_blocks.append(ToolUseBlock(
                id=tc.get("id", f"call_{uuid.uuid4().hex[:8]}"),
                name=func.get("name", ""),
                input=args,
            ))

        usage = data.get("usage", {})

        return Message(
            role="assistant",
            content=content_blocks if content_blocks else [TextBlock(text="")],
            model=data.get("model", ""),
        )


def estimate_cost(usage: UsageStats, model: str = DEFAULT_MODEL) -> float:
    """Estimate the cost of an API call based on usage."""
    # Pricing per million tokens (approximate)
    pricing = {
        "claude-sonnet-4-20250514": {"input": 3.0, "output": 15.0},
        "claude-opus-4-20250514": {"input": 15.0, "output": 75.0},
        "gpt-4o": {"input": 2.5, "output": 10.0},
        "gpt-4o-mini": {"input": 0.15, "output": 0.60},
        "gpt-4.1": {"input": 2.0, "output": 8.0},
        "gpt-4.1-mini": {"input": 0.40, "output": 1.60},
    }
    rates = pricing.get(model, {"input": 3.0, "output": 15.0})
    input_cost = (usage.input_tokens / 1_000_000) * rates["input"]
    output_cost = (usage.output_tokens / 1_000_000) * rates["output"]
    return input_cost + output_cost

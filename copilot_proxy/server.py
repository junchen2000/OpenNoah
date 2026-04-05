"""Main proxy server - OpenAI-compatible API backed by GitHub Copilot.

Endpoints:
  GET  /v1/models              - List available models
  POST /v1/chat/completions    - Chat completions (streaming & non-streaming)
  GET  /health                 - Health check
"""

import json
import logging
import uuid
from typing import Any

import aiohttp
from aiohttp import web

from .auth import CopilotAuth
from .config import COPILOT_API_BASE, DEFAULT_HOST, DEFAULT_PORT, KNOWN_MODELS

logger = logging.getLogger(__name__)


class CopilotProxy:
    """OpenAI-compatible API proxy for GitHub Copilot."""

    def __init__(self, auth: CopilotAuth, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT):
        self.auth = auth
        self.host = host
        self.port = port
        self.app = web.Application()
        self._setup_routes()

    def _setup_routes(self):
        self.app.router.add_get("/v1/models", self.handle_list_models)
        self.app.router.add_post("/v1/chat/completions", self.handle_chat_completions)
        self.app.router.add_get("/health", self.handle_health)
        # Also handle without /v1 prefix for compatibility
        self.app.router.add_get("/models", self.handle_list_models)
        self.app.router.add_post("/chat/completions", self.handle_chat_completions)

    async def _get_headers(self) -> dict[str, str]:
        """Build request headers with a valid Copilot token."""
        copilot_token = await self.auth.get_copilot_token()
        return {
            "Authorization": f"Bearer {copilot_token.token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Editor-Version": "vscode/1.100.0",
            "Editor-Plugin-Version": "copilot-chat/0.24.0",
            "Copilot-Integration-Id": "vscode-chat",
            "Openai-Intent": "conversation-panel",
            "Openai-Organization": "github-copilot",
            "User-Agent": "GitHubCopilotChat/0.24.0",
            "X-Request-Id": str(uuid.uuid4()),
        }

    # ── GET /v1/models ──────────────────────────────────────────────

    async def handle_list_models(self, request: web.Request) -> web.Response:
        """List available models in OpenAI format."""
        models = []
        for model_id, info in KNOWN_MODELS.items():
            models.append({
                "id": model_id,
                "object": "model",
                "created": 1700000000,
                "owned_by": info["provider"],
                "permission": [],
                "root": model_id,
                "parent": None,
            })

        return web.json_response({
            "object": "list",
            "data": models,
        })

    # ── POST /v1/chat/completions ───────────────────────────────────

    async def handle_chat_completions(self, request: web.Request) -> web.Response:
        """Forward chat completion requests to GitHub Copilot API."""
        try:
            body = await request.json()
        except json.JSONDecodeError:
            return web.json_response(
                {"error": {"message": "Invalid JSON body", "type": "invalid_request_error"}},
                status=400,
            )

        stream = body.get("stream", False)
        model = body.get("model", "gpt-4o")

        logger.info("Chat completion request: model=%s stream=%s", model, stream)

        # Build the request payload for Copilot API
        payload = self._build_copilot_payload(body)

        try:
            headers = await self._get_headers()
        except RuntimeError as e:
            return web.json_response(
                {"error": {"message": str(e), "type": "authentication_error"}},
                status=401,
            )

        url = f"{COPILOT_API_BASE}/chat/completions"

        if stream:
            return await self._handle_stream(request, url, headers, payload)
        else:
            return await self._handle_non_stream(url, headers, payload)

    def _build_copilot_payload(self, body: dict[str, Any]) -> dict[str, Any]:
        """Transform incoming OpenAI request to Copilot-compatible format."""
        payload: dict[str, Any] = {
            "messages": body.get("messages", []),
            "model": body.get("model", "gpt-4o"),
            "stream": body.get("stream", False),
        }

        # Forward optional parameters
        for key in (
            "temperature", "top_p", "max_tokens", "stop",
            "presence_penalty", "frequency_penalty", "n",
            "tools", "tool_choice", "response_format",
        ):
            if key in body:
                payload[key] = body[key]

        return payload

    async def _handle_non_stream(
        self, url: str, headers: dict, payload: dict
    ) -> web.Response:
        """Handle non-streaming chat completion."""
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=payload) as resp:
                if resp.status != 200:
                    error_body = await resp.text()
                    logger.error("Copilot API error: %s %s", resp.status, error_body)
                    return web.Response(
                        text=error_body,
                        status=resp.status,
                        content_type="application/json",
                    )
                data = await resp.json()
                return web.json_response(data)

    async def _handle_stream(
        self, request: web.Request, url: str, headers: dict, payload: dict
    ) -> web.StreamResponse:
        """Handle streaming chat completion with SSE passthrough."""
        payload["stream"] = True

        response = web.StreamResponse(
            status=200,
            reason="OK",
            headers={
                "Content-Type": "text/event-stream",
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

        await response.prepare(request)

        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=payload) as resp:
                if resp.status != 200:
                    error_body = await resp.text()
                    logger.error("Copilot API stream error: %s %s", resp.status, error_body)
                    error_event = {
                        "error": {
                            "message": f"Copilot API error: {resp.status}",
                            "type": "api_error",
                            "details": error_body,
                        }
                    }
                    await response.write(
                        f"data: {json.dumps(error_event)}\n\n".encode()
                    )
                    await response.write(b"data: [DONE]\n\n")
                    return response

                # Pass through SSE events from Copilot
                async for line in resp.content:
                    decoded = line.decode("utf-8", errors="replace")
                    if decoded.strip():
                        await response.write(line)
                    else:
                        await response.write(b"\n")

        return response

    # ── GET /health ─────────────────────────────────────────────────

    async def handle_health(self, request: web.Request) -> web.Response:
        """Health check endpoint."""
        try:
            token = await self.auth.get_copilot_token()
            return web.json_response({
                "status": "ok",
                "token_expires_at": token.expires_at,
            })
        except Exception as e:
            return web.json_response(
                {"status": "error", "message": str(e)},
                status=503,
            )

    def run(self):
        """Start the proxy server."""
        print(f"""
╔══════════════════════════════════════════════════════════════╗
║            GitHub Copilot LLM Proxy                         ║
╠══════════════════════════════════════════════════════════════╣
║  OpenAI-compatible API for GitHub Copilot models            ║
║                                                             ║
║  Base URL:  http://{self.host}:{self.port}/v1                       ║
║  Models:    GET  /v1/models                                 ║
║  Chat:      POST /v1/chat/completions                       ║
║  Health:    GET  /health                                    ║
║                                                             ║
║  Usage with Claude Code:                                    ║
║    export ANTHROPIC_BASE_URL=http://{self.host}:{self.port}/v1      ║
║                                                             ║
║  Usage with OpenAI SDK:                                     ║
║    client = OpenAI(                                         ║
║        base_url="http://{self.host}:{self.port}/v1",                ║
║        api_key="copilot-proxy"                              ║
║    )                                                        ║
╚══════════════════════════════════════════════════════════════╝
""")
        web.run_app(self.app, host=self.host, port=self.port, print=None)

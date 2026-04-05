"""MCP (Model Context Protocol) client service.

Manages connections to MCP servers, discovers tools/resources,
and proxies tool calls.

Config format (~/.noah/mcp.json or .noah/mcp.json):
{
    "mcpServers": {
        "microsoft-learn": {
            "type": "http",
            "url": "https://learn.microsoft.com/api/mcp"
        },
        "server-name": {
            "type": "stdio",
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-filesystem", "/path"],
            "env": {}
        },
        "another-server": {
            "type": "sse",
            "url": "http://localhost:3000/sse"
        }
    }
}
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from ..config import get_config_dir

logger = logging.getLogger(__name__)


@dataclass
class MCPServerConfig:
    """Configuration for a single MCP server."""
    name: str
    type: str  # "stdio", "sse", "http"
    command: str = ""
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    url: str = ""


@dataclass
class MCPToolInfo:
    """Discovered tool from an MCP server."""
    server_name: str
    tool_name: str
    description: str
    input_schema: dict[str, Any]


@dataclass
class MCPConnection:
    """An active connection to an MCP server."""
    config: MCPServerConfig
    session: ClientSession | None = None
    tools: list[MCPToolInfo] = field(default_factory=list)
    connected: bool = False
    error: str = ""


class MCPManager:
    """Manages MCP server connections and tool discovery."""

    def __init__(self) -> None:
        self._connections: dict[str, MCPConnection] = {}
        self._stdio_contexts: dict[str, Any] = {}  # hold context managers alive

    def load_config(self, cwd: str = "", extra_config: str | None = None) -> list[MCPServerConfig]:
        """Load MCP server configs from config files.

        Priority (later overrides): project < personal < extra_config (session).
        """
        configs: list[MCPServerConfig] = []
        seen_names: set[str] = set()

        def _add(new_configs: list[MCPServerConfig]) -> None:
            for c in new_configs:
                seen_names.add(c.name)
                configs.append(c)

        # Check project-level config (lowest priority)
        if cwd:
            project_config = Path(cwd) / ".noah" / "mcp.json"
            if project_config.exists():
                _add(self._parse_config(project_config))

        # Check user-level config
        user_config = get_config_dir() / "mcp.json"
        if user_config.exists():
            _add(self._parse_config(user_config))

        # Session-level extra config (highest priority, --mcp-config)
        if extra_config:
            extra_path = Path(extra_config)
            if extra_path.exists():
                _add(self._parse_config(extra_path))

        return configs

    @staticmethod
    def _parse_config(path: Path) -> list[MCPServerConfig]:
        """Parse an MCP config file."""
        try:
            data = json.loads(path.read_text("utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            logger.error("Failed to parse MCP config %s: %s", path, e)
            return []

        servers = data.get("mcpServers", {})
        configs = []
        for name, cfg in servers.items():
            server_type = cfg.get("type", "stdio")
            configs.append(MCPServerConfig(
                name=name,
                type=server_type,
                command=cfg.get("command", ""),
                args=cfg.get("args", []),
                env=cfg.get("env", {}),
                url=cfg.get("url", ""),
            ))
        return configs

    async def connect_all(self, cwd: str = "", extra_config: str | None = None) -> list[MCPConnection]:
        """Load configs and connect to all MCP servers."""
        configs = self.load_config(cwd, extra_config=extra_config)
        if not configs:
            return []

        tasks = [self._connect_server(cfg) for cfg in configs]
        connections = await asyncio.gather(*tasks, return_exceptions=True)

        for result in connections:
            if isinstance(result, MCPConnection):
                self._connections[result.config.name] = result
            elif isinstance(result, Exception):
                logger.error("MCP connection failed: %s", result)

        return list(self._connections.values())

    async def _connect_server(self, config: MCPServerConfig) -> MCPConnection:
        """Connect to a single MCP server and discover tools."""
        conn = MCPConnection(config=config)

        try:
            if config.type == "stdio":
                conn = await self._connect_stdio(config)
            elif config.type in ("sse", "http"):
                conn = await self._connect_http(config)
            else:
                conn.error = f"Unsupported transport: {config.type}"
                logger.warning("Skipping MCP server %s: %s", config.name, conn.error)
        except Exception as e:
            conn.error = str(e)
            logger.error("Failed to connect to MCP server %s: %s", config.name, e)

        return conn

    async def _connect_stdio(self, config: MCPServerConfig) -> MCPConnection:
        """Connect to a stdio MCP server."""
        conn = MCPConnection(config=config)

        server_params = StdioServerParameters(
            command=config.command,
            args=config.args,
            env={**os.environ, **config.env} if config.env else None,
        )

        # Create the stdio client context
        stdio_ctx = stdio_client(server_params)
        read_stream, write_stream = await stdio_ctx.__aenter__()
        self._stdio_contexts[config.name] = stdio_ctx

        # Create session
        session = ClientSession(read_stream, write_stream)
        await session.__aenter__()
        await session.initialize()

        conn.session = session
        conn.connected = True

        # Discover tools
        conn.tools = await self._discover_tools(config.name, session)
        logger.info("MCP server %s: connected, %d tools", config.name, len(conn.tools))

        return conn

    async def _connect_http(self, config: MCPServerConfig) -> MCPConnection:
        """Connect to an SSE/HTTP MCP server."""
        conn = MCPConnection(config=config)

        try:
            if config.type == "http":
                from mcp.client.streamable_http import streamablehttp_client
                ctx = streamablehttp_client(config.url)
            else:
                from mcp.client.sse import sse_client
                ctx = sse_client(config.url)

            result = await ctx.__aenter__()
            self._stdio_contexts[config.name] = ctx

            # streamablehttp_client returns 3 values, sse_client returns 2
            if len(result) == 3:
                read_stream, write_stream, _ = result
            else:
                read_stream, write_stream = result

            session = ClientSession(read_stream, write_stream)
            await session.__aenter__()
            await session.initialize()

            conn.session = session
            conn.connected = True
            conn.tools = await self._discover_tools(config.name, session)
            logger.info("MCP server %s (%s): connected, %d tools", config.name, config.type, len(conn.tools))
        except ImportError:
            conn.error = "SSE transport not available"
        except Exception as e:
            conn.error = str(e)

        return conn

    async def _discover_tools(self, server_name: str, session: ClientSession) -> list[MCPToolInfo]:
        """Discover tools from an MCP server."""
        try:
            result = await session.list_tools()
            tools = []
            for tool in result.tools:
                tools.append(MCPToolInfo(
                    server_name=server_name,
                    tool_name=tool.name,
                    description=tool.description or "",
                    input_schema=tool.inputSchema if hasattr(tool, 'inputSchema') else {},
                ))
            return tools
        except Exception as e:
            logger.error("Failed to list tools from %s: %s", server_name, e)
            return []

    async def call_tool(self, server_name: str, tool_name: str, arguments: dict[str, Any]) -> str:
        """Call a tool on an MCP server."""
        conn = self._connections.get(server_name)
        if not conn or not conn.session:
            raise RuntimeError(f"MCP server '{server_name}' not connected")

        try:
            result = await conn.session.call_tool(tool_name, arguments)
            # Extract text from result content
            texts = []
            for block in result.content:
                if hasattr(block, 'text'):
                    texts.append(block.text)
                elif hasattr(block, 'data'):
                    texts.append(f"[binary data: {len(block.data)} bytes]")
                else:
                    texts.append(str(block))
            return "\n".join(texts) if texts else "(no output)"
        except Exception as e:
            raise RuntimeError(f"MCP tool call failed: {e}") from e

    def get_all_tools(self) -> list[MCPToolInfo]:
        """Get all discovered tools across all connected servers."""
        tools = []
        for conn in self._connections.values():
            tools.extend(conn.tools)
        return tools

    def get_connections(self) -> list[MCPConnection]:
        """Get all connections."""
        return list(self._connections.values())

    async def disconnect_all(self) -> None:
        """Disconnect from all MCP servers."""
        # Close sessions first, then transport contexts
        for conn in self._connections.values():
            if conn.session:
                try:
                    await conn.session.__aexit__(None, None, None)
                except Exception:
                    pass
                conn.session = None
        self._connections.clear()

        for name, ctx in list(self._stdio_contexts.items()):
            try:
                await ctx.__aexit__(None, None, None)
            except Exception:
                pass
        self._stdio_contexts.clear()

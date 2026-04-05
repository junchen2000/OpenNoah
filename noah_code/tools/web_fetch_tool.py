"""Web Fetch tool - Fetch content from URLs."""
from __future__ import annotations

import asyncio
import html
import re
from typing import Any, Callable
from urllib.parse import urlparse

from ..tool import Tool, ToolResult


class WebFetchTool(Tool):
    """Fetch and extract content from a URL."""

    name = "web_fetch"
    description_text = (
        "Fetch content from a URL and extract the main text. "
        "Useful for reading documentation, API references, or web pages."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "The URL to fetch.",
            },
        },
        "required": ["url"],
    }

    def is_read_only(self, tool_input: dict[str, Any]) -> bool:
        return True

    def is_concurrency_safe(self, tool_input: dict[str, Any]) -> bool:
        return True

    def get_tool_use_summary(self, tool_input: dict[str, Any]) -> str | None:
        url = tool_input.get("url", "")
        return f"Fetch {url}"

    async def call(
        self,
        tool_input: dict[str, Any],
        cwd: str,
        on_progress: Callable[[dict[str, Any]], None] | None = None,
    ) -> ToolResult:
        url = tool_input.get("url", "")

        if not url:
            return ToolResult(output="Error: url is required", is_error=True)

        # Validate URL
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return ToolResult(output="Error: Only http and https URLs are supported", is_error=True)

        try:
            import aiohttp

            timeout = aiohttp.ClientTimeout(total=30)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(
                    url,
                    headers={"User-Agent": "Noah-Code/2.1.88"},
                    allow_redirects=True,
                    max_redirects=5,
                ) as response:
                    if response.status != 200:
                        return ToolResult(
                            output=f"Error: HTTP {response.status} {response.reason}",
                            is_error=True,
                        )

                    content_type = response.headers.get("content-type", "")
                    raw = await response.text()

                    # Extract text from HTML
                    if "text/html" in content_type:
                        text = self._extract_text_from_html(raw)
                    else:
                        text = raw

                    # Truncate
                    if len(text) > 50000:
                        text = text[:50000] + "\n\n... (truncated)"

                    return ToolResult(output=text)

        except ImportError:
            # Fallback to urllib
            import urllib.request
            import urllib.error

            try:
                req = urllib.request.Request(
                    url, headers={"User-Agent": "Noah-Code/2.1.88"}
                )
                with urllib.request.urlopen(req, timeout=30) as response:
                    raw = response.read().decode("utf-8", errors="replace")
                    content_type = response.headers.get("content-type", "")

                    if "text/html" in content_type:
                        text = self._extract_text_from_html(raw)
                    else:
                        text = raw

                    if len(text) > 50000:
                        text = text[:50000] + "\n\n... (truncated)"

                    return ToolResult(output=text)
            except urllib.error.URLError as e:
                return ToolResult(output=f"Error fetching URL: {e}", is_error=True)

        except Exception as e:
            return ToolResult(output=f"Error fetching URL: {e}", is_error=True)

    @staticmethod
    def _extract_text_from_html(html_content: str) -> str:
        """Simple HTML to text extraction."""
        # Remove script and style tags
        text = re.sub(r"<script[^>]*>.*?</script>", "", html_content, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL | re.IGNORECASE)
        # Remove HTML tags
        text = re.sub(r"<[^>]+>", " ", text)
        # Decode HTML entities
        text = html.unescape(text)
        # Clean up whitespace
        text = re.sub(r"\s+", " ", text)
        text = re.sub(r"\n\s*\n+", "\n\n", text)
        return text.strip()

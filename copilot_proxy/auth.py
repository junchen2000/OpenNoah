"""GitHub Copilot token management.

Auth flow:
1. Get GitHub token from `gh auth token`, VS Code config, or environment variable
2. Exchange for a short-lived Copilot JWT token via GitHub's internal API
3. Cache the JWT and auto-refresh before expiry
"""

import asyncio
import json
import logging
import os
import subprocess
import time
from dataclasses import dataclass, field

import aiohttp

logger = logging.getLogger(__name__)

GITHUB_COPILOT_TOKEN_URL = "https://api.github.com/copilot_internal/v2/token"
TOKEN_REFRESH_BUFFER = 300  # Refresh 5 minutes before expiry


@dataclass
class CopilotToken:
    """A cached Copilot API token."""
    token: str
    expires_at: int  # Unix timestamp
    endpoints: dict = field(default_factory=dict)

    @property
    def is_expired(self) -> bool:
        return time.time() >= (self.expires_at - TOKEN_REFRESH_BUFFER)


class CopilotAuth:
    """Manages GitHub Copilot authentication tokens."""

    def __init__(self, github_token: str | None = None):
        self._github_token = github_token
        self._copilot_token: CopilotToken | None = None
        self._lock = asyncio.Lock()

    def _resolve_github_token(self) -> str:
        """Resolve GitHub token from multiple sources."""
        # 1. Explicit token
        if self._github_token:
            return self._github_token

        # 2. Environment variables
        for env_var in ("GITHUB_TOKEN", "GH_TOKEN"):
            token = os.environ.get(env_var)
            if token:
                logger.info("Using GitHub token from %s", env_var)
                return token

        # 3. VS Code Copilot token file (common locations)
        vscode_token_paths = [
            os.path.expanduser("~/.config/github-copilot/hosts.json"),
            os.path.expanduser("~/.config/github-copilot/apps.json"),
            os.path.join(os.environ.get("LOCALAPPDATA", ""), "github-copilot", "hosts.json"),
            os.path.join(os.environ.get("APPDATA", ""), "github-copilot", "hosts.json"),
        ]
        for path in vscode_token_paths:
            if os.path.exists(path):
                try:
                    with open(path, "r") as f:
                        data = json.load(f)
                    for key, val in data.items():
                        if "github.com" in key:
                            token = val.get("oauth_token") or val.get("token")
                            if token:
                                logger.info("Using GitHub token from %s", path)
                                return token
                except Exception as e:
                    logger.debug("Failed reading %s: %s", path, e)

        # 4. GitHub CLI
        try:
            result = subprocess.run(
                ["gh", "auth", "token"],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0 and result.stdout.strip():
                logger.info("Using GitHub token from `gh auth token`")
                return result.stdout.strip()
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

        raise RuntimeError(
            "No GitHub token found. Set GITHUB_TOKEN env var, "
            "or install GitHub CLI (`gh`) and run `gh auth login`."
        )

    async def get_copilot_token(self) -> CopilotToken:
        """Get a valid Copilot token, refreshing if needed."""
        async with self._lock:
            if self._copilot_token and not self._copilot_token.is_expired:
                return self._copilot_token

            github_token = self._resolve_github_token()
            self._copilot_token = await self._fetch_copilot_token(github_token)
            logger.info(
                "Copilot token refreshed, expires at %s",
                time.strftime("%H:%M:%S", time.localtime(self._copilot_token.expires_at))
            )
            return self._copilot_token

    async def _fetch_copilot_token(self, github_token: str) -> CopilotToken:
        """Exchange a GitHub token for a Copilot API token."""
        headers = {
            "Authorization": f"token {github_token}",
            "Accept": "application/json",
            "Editor-Version": "vscode/1.100.0",
            "Editor-Plugin-Version": "copilot-chat/0.24.0",
            "User-Agent": "GitHubCopilotChat/0.24.0",
        }

        async with aiohttp.ClientSession() as session:
            async with session.get(GITHUB_COPILOT_TOKEN_URL, headers=headers) as resp:
                if resp.status == 401:
                    raise RuntimeError(
                        "GitHub token is invalid or does not have Copilot access. "
                        "Ensure you have an active GitHub Copilot subscription."
                    )
                if resp.status != 200:
                    body = await resp.text()
                    raise RuntimeError(
                        f"Failed to get Copilot token: HTTP {resp.status} - {body}"
                    )
                data = await resp.json()

        return CopilotToken(
            token=data["token"],
            expires_at=data["expires_at"],
            endpoints=data.get("endpoints", {}),
        )

"""Configuration and constants for Noah Code."""
from __future__ import annotations

import os
from pathlib import Path

# Version
VERSION = "0.1.0"

# Default models
DEFAULT_MODEL = os.environ.get("NOAH_CODE_MODEL", "gpt-5.4-mini")
OPUS_MODEL = "gpt-5.4"
HAIKU_MODEL = "gpt-5.4-nano"

# API settings (OpenAI-compatible endpoint)
# Set OPENAI_BASE_URL to override. Azure OpenAI endpoints auto-detected.
DEFAULT_BASE_URL = os.environ.get("OPENAI_BASE_URL", "https://juncheaoai.openai.azure.com")

# Token limits
MAX_OUTPUT_TOKENS = 16384
MAX_THINKING_TOKENS = 10000
AUTOCOMPACT_BUFFER_TOKENS = 13000
WARNING_TOKEN_THRESHOLD = 20000

# Tool limits
MAX_GREP_RESULTS = 250
MAX_GLOB_RESULTS = 100
MAX_FILE_SIZE_BYTES = 1_073_741_824  # 1 GB
MAX_TOOL_RESULT_CHARS = 100_000

# Paths
def get_config_dir() -> Path:
    """Get the Noah configuration directory."""
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", Path.home()))
    else:
        base = Path.home()
    return base / ".noah"


def get_cache_dir() -> Path:
    """Get the Noah cache directory."""
    return get_config_dir() / "cache"


def get_session_dir() -> Path:
    """Get the session storage directory."""
    return get_config_dir() / "sessions"


def get_noah_md_path(cwd: str | None = None) -> Path:
    """Get the path to NOAH.md in the current project."""
    if cwd:
        return Path(cwd) / "NOAH.md"
    return Path.cwd() / "NOAH.md"


# System prompt components
SYSTEM_PROMPT_PREFIX = """You are Noah Code, an autonomous agentic coding tool. You solve tasks end-to-end using your tools without stopping to ask the user for confirmation or next steps.

CRITICAL RULES:
- Be AGGRESSIVE and AUTONOMOUS. When you encounter an error, fix it yourself and continue. Do NOT stop to ask the user what to do.
- When a tool or command fails, diagnose the problem, try an alternative approach, and keep going.
- When you have a recommended action, EXECUTE IT. Do not say "If you want, I can..." — just do it.
- Only ask the user when you genuinely need information you cannot find yourself (e.g., credentials, preferences with no reasonable default).
- Minimize output tokens. No preamble, no postamble. Do the work, report results briefly.
- When a dependency is missing, install it. When a path doesn't exist, create it. When a command fails, try another way.
- Persist through errors. Try at least 3 different approaches before giving up.

"""

TOOL_USE_INSTRUCTIONS = """When using tools:
1. Always provide the required parameters
2. When a tool fails, diagnose and retry with a different approach — do NOT ask the user
3. Use the most appropriate tool for each task
4. Chain multiple tools together to complete tasks autonomously
5. If a command is not found, install the dependency or find an alternative
"""

# Feature flags (simplified from GrowthBook)
FEATURES: dict[str, bool] = {
    "THINKING": True,
    "MULTI_AGENT": False,
    "MCP": False,
}


def feature(name: str) -> bool:
    """Check if a feature flag is enabled."""
    return FEATURES.get(name, False)

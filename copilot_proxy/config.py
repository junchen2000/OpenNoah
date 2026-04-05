"""Copilot Proxy configuration and known models."""

# GitHub Copilot API base URL
COPILOT_API_BASE = "https://api.githubcopilot.com"

# Known models available through GitHub Copilot
# The actual availability depends on your subscription level
KNOWN_MODELS = {
    # OpenAI models
    "gpt-4o": {"name": "gpt-4o", "provider": "openai", "context": 128000},
    "gpt-4o-mini": {"name": "gpt-4o-mini", "provider": "openai", "context": 128000},
    "gpt-4.1": {"name": "gpt-4.1", "provider": "openai", "context": 1047576},
    "gpt-4.1-mini": {"name": "gpt-4.1-mini", "provider": "openai", "context": 1047576},
    "gpt-4.1-nano": {"name": "gpt-4.1-nano", "provider": "openai", "context": 1047576},
    "o1": {"name": "o1", "provider": "openai", "context": 200000},
    "o1-mini": {"name": "o1-mini", "provider": "openai", "context": 128000},
    "o1-preview": {"name": "o1-preview", "provider": "openai", "context": 128000},
    "o3": {"name": "o3", "provider": "openai", "context": 200000},
    "o3-mini": {"name": "o3-mini", "provider": "openai", "context": 200000},
    "o4-mini": {"name": "o4-mini", "provider": "openai", "context": 200000},
    # Anthropic models
    "claude-3.5-sonnet": {"name": "claude-3.5-sonnet", "provider": "anthropic", "context": 200000},
    "claude-3.7-sonnet": {"name": "claude-3.7-sonnet", "provider": "anthropic", "context": 200000},
    "claude-3.7-sonnet-thought": {"name": "claude-3.7-sonnet-thought", "provider": "anthropic", "context": 200000},
    "claude-sonnet-4": {"name": "claude-sonnet-4", "provider": "anthropic", "context": 200000},
    "claude-opus-4": {"name": "claude-opus-4", "provider": "anthropic", "context": 200000},
    # Google models
    "gemini-2.0-flash-001": {"name": "gemini-2.0-flash-001", "provider": "google", "context": 1048576},
    "gemini-2.5-pro": {"name": "gemini-2.5-pro", "provider": "google", "context": 1048576},
    # xAI
    "grok-3": {"name": "grok-3", "provider": "xai", "context": 131072},
}

DEFAULT_MODEL = "gpt-4o"
DEFAULT_PORT = 8787
DEFAULT_HOST = "127.0.0.1"

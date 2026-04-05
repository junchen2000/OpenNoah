"""Entry point: python -m copilot_proxy"""

import argparse
import logging
import sys

from .auth import CopilotAuth
from .config import DEFAULT_HOST, DEFAULT_PORT
from .server import CopilotProxy


def main():
    parser = argparse.ArgumentParser(
        description="GitHub Copilot LLM Proxy - OpenAI-compatible API"
    )
    parser.add_argument(
        "--host", default=DEFAULT_HOST,
        help=f"Bind address (default: {DEFAULT_HOST})"
    )
    parser.add_argument(
        "--port", "-p", type=int, default=DEFAULT_PORT,
        help=f"Port number (default: {DEFAULT_PORT})"
    )
    parser.add_argument(
        "--token", default=None,
        help="GitHub token (default: auto-detect from gh CLI / env / VS Code)"
    )
    parser.add_argument(
        "--debug", action="store_true",
        help="Enable debug logging"
    )

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    auth = CopilotAuth(github_token=args.token)
    proxy = CopilotProxy(auth=auth, host=args.host, port=args.port)

    try:
        proxy.run()
    except KeyboardInterrupt:
        print("\nShutting down.")
        sys.exit(0)


if __name__ == "__main__":
    main()

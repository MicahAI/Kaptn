"""Claude Code hook client — forwards PreToolUse events to the Kaptn bridge.

Registered in Claude Code settings as a PreToolUse hook command. Reads the
hook event from stdin, POSTs it to the local Kaptn hook server, and prints
the decision JSON to stdout.

Fails open: if the bridge is not running, times out, or errors, this exits
0 with no output — Claude Code's normal permission flow stays in charge.
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

DEFAULT_HOOK_PORT = 3002
DEFAULT_TIMEOUT_SECONDS = 5.0


def main(argv: list[str] | None = None) -> int:
    """Read a hook event from stdin, relay it, print the decision.

    Args:
        argv: CLI arguments (defaults to sys.argv).

    Returns:
        Process exit code — always 0 so a bridge outage never blocks
        Claude Code.
    """
    parser = argparse.ArgumentParser(description="Kaptn Claude Code hook client")
    parser.add_argument("--host", default=os.environ.get("KAPTN_HOOK_HOST", "127.0.0.1"))
    parser.add_argument(
        "--port", type=int,
        default=int(os.environ.get("KAPTN_HOOK_PORT", DEFAULT_HOOK_PORT)),
    )
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    args = parser.parse_args(argv)

    try:
        event = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        return 0

    request = urllib.request.Request(
        f"http://{args.host}:{args.port}/hook",
        data=json.dumps(event).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=args.timeout) as response:
            body = response.read()
    except (urllib.error.URLError, OSError, TimeoutError):
        return 0  # fail open — normal permission flow takes over

    try:
        result = json.loads(body or b"{}")
    except json.JSONDecodeError:
        return 0

    if result:
        print(json.dumps(result))
    return 0


def entry() -> None:
    """Console-script entry point."""
    sys.exit(main())


if __name__ == "__main__":
    sys.exit(main())

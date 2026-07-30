"""Claude Code hook client — forwards PreToolUse events to the Kaptn bridge.

Registered in Claude Code settings as a PreToolUse hook command. Reads the
hook event from stdin, POSTs it to the local Kaptn hook server, and prints
the decision JSON to stdout.

Fails open: if the bridge is not running, times out, or errors, this exits
0 with no output — Claude Code's normal permission flow stays in charge.

The `--timeout` is this client's **answer budget**: the longest it can take
to produce a verdict. It is baked into the registered command by
bridge.claude.claude_setup so it and the registered hook `timeout` are
derived from the same number and cannot drift apart — the hook must never
be killed mid-answer, because a killed PreToolUse hook abstains and
abstaining fails open (ADR-0012, and see bridge.claude.hook_guard).

`--timeout none` means an unbounded hold: wait however long the captain
takes. Under that regime the local fail-open behavior below still applies
to a *dead* bridge, but never to a slow one.
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

from bridge.claude.hook_guard import DEFAULT_ANSWER_BUDGET_SECONDS

DEFAULT_HOOK_PORT = 3002
DEFAULT_TIMEOUT_SECONDS = DEFAULT_ANSWER_BUDGET_SECONDS

#: Values that select an unbounded hold rather than a deadline.
UNBOUNDED_TOKENS = ("none", "unbounded", "hold", "0")


def parse_answer_budget(value: str | float | None) -> float | None:
    """Parse an answer budget from the command line or environment.

    Args:
        value: Seconds, or one of UNBOUNDED_TOKENS for an unbounded hold.

    Returns:
        Seconds, or None for an unbounded hold (no deadline).

    Raises:
        argparse.ArgumentTypeError: If the value is not a number or token.
    """
    if value is None:
        return None
    if isinstance(value, str):
        if value.strip().lower() in UNBOUNDED_TOKENS:
            return None
        try:
            value = float(value)
        except ValueError as e:
            raise argparse.ArgumentTypeError(
                f"answer budget must be seconds or one of {UNBOUNDED_TOKENS}: {value!r}"
            ) from e
    return None if value <= 0 else float(value)


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
    parser.add_argument(
        "--timeout", type=parse_answer_budget,
        default=parse_answer_budget(
            os.environ.get("KAPTN_ANSWER_BUDGET", DEFAULT_TIMEOUT_SECONDS)
        ),
        help="Answer budget in seconds, or 'none' for an unbounded hold.",
    )
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

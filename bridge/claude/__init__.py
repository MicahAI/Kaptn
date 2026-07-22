"""Claude Code adapter — hook-based approval source for the Kaptn bridge.

Unlike the CDP drivers (which poll an IDE's DOM and click buttons), this
adapter is push-based: Claude Code's PreToolUse hook sends each tool call
to the Kaptn hook server, which evaluates it through the shared AutoPilot
engine and returns an allow/deny/ask decision.
"""

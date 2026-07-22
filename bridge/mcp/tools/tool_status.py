"""MCP tool: kaptn_status — get current bridge and AutoPilot state."""

import time

from bridge.mcp import _state
from bridge.mcp._progress import is_bridge_running, read_progress


@_state.mcp.tool()
def kaptn_status(window: str | None = None) -> dict:
    """Get current bridge and AutoPilot state — connection, windows, temp rules.

    Shows whether the bridge subprocess is running, which IDE windows are
    connected, any CDP errors, and active temporary rules.

    Args:
        window: Filter to a specific window.
    """
    progress = read_progress()
    running = is_bridge_running()

    if not running and not progress:
        return {
            "bridge": "not_running",
            "message": "Bridge not started. Call kaptn_connect to start.",
        }

    result = {
        "bridge": "running" if running else "stopped",
        "pid": progress.get("pid"),
        "cdp_port": progress.get("cdp_port"),
    }

    # CDP/connection error
    error = progress.get("error")
    if error:
        result["error"] = error
        retry_at = progress.get("retry_at")
        if retry_at:
            remaining = max(0, retry_at - time.time())
            result["retry_in_seconds"] = round(remaining, 1)

    # Connected windows
    windows = progress.get("windows", [])
    if window:
        windows = [w for w in windows if w == window]
    result["windows"] = windows
    result["window_count"] = len(windows)

    # Temp rules from bridge progress
    temp_rules = progress.get("temp_rules", [])
    if window:
        temp_rules = [r for r in temp_rules if r.get("window") == window or not r.get("window")]
    result["temp_rules"] = temp_rules
    result["temp_rule_count"] = len(temp_rules)

    # Staleness check
    ts = progress.get("timestamp")
    if ts:
        age = time.time() - ts
        if age > 10:
            result["warning"] = f"Bridge status is {age:.0f}s old — may be unresponsive"

    return result

"""MCP tool: kaptn_watch — start monitoring a window with time-boxed auto-approval."""

from bridge.mcp import _state
from bridge.mcp._progress import is_bridge_running, read_commands, write_commands

# Default if not set in config and not provided by caller
_FALLBACK_WATCH_MINUTES = 20


@_state.mcp.tool()
def kaptn_watch(
    window: str,
    minutes: int | None = None,
    categories: list[str] | None = None,
    alert_on_stuck: bool = True,
) -> dict:
    """Start monitoring a window — auto-approve requests for a duration.

    Creates temporary approval rules for the specified window with a
    time-to-live. When the TTL expires, rules are removed and static
    config takes over again.

    Args:
        window: Window name to monitor (e.g. "Kaptn", "TelemetryMCPV2").
        minutes: Duration in minutes (max 480 = 8 hours).
            Defaults to autopilot.default_watch_minutes from config.
        categories: Categories to approve. Default: all except file_delete.
            Values: file_read, file_write, command_safe, command_unsafe, search, tool_call.
        alert_on_stuck: Alert user if loop detected or AutoPilot pauses.
    """
    if not is_bridge_running():
        return {"error": "Bridge not running. Call kaptn_connect first."}

    # Resolve minutes from config default if not provided
    if minutes is None:
        cfg_default = _FALLBACK_WATCH_MINUTES
        if _state._config_manager:
            cfg = _state._config_manager.load()
            cfg_default = cfg.get("autopilot", {}).get("default_watch_minutes", _FALLBACK_WATCH_MINUTES)
        minutes = cfg_default

    if minutes < 1 or minutes > 480:
        return {"error": "minutes must be between 1 and 480"}

    # Queue command for bridge subprocess
    cmds = read_commands()
    rules = cmds.get("temp_rules", [])
    rules.append({
        "action": "create_watch",
        "window": window,
        "minutes": minutes,
        "categories": categories,
    })
    # Also resume the window if it was paused
    rules.append({"action": "resume_window", "window": window})
    cmds["temp_rules"] = rules
    write_commands(cmds)

    return {
        "status": "watching",
        "window": window,
        "minutes": minutes,
        "categories": categories or ["all except file_delete"],
        "alert_on_stuck": alert_on_stuck,
        "message": "Watch rules sent to bridge. Use kaptn_status to verify.",
    }

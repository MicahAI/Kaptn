"""MCP tool: kaptn_defaults — view current AutoPilot configuration."""

from bridge.mcp import _state


@_state.mcp.tool()
def kaptn_defaults() -> dict:
    """View current AutoPilot defaults — rules, poll intervals, and settings.

    Shows the full autopilot configuration including all static rules,
    poll intervals, loop detection settings, and the reset-on-manual flag.
    """
    if _state._config_manager is None:
        return {"error": "Config manager not initialized"}

    cfg = _state._config_manager.load()
    autopilot = cfg.get("autopilot", {})
    poll = cfg.get("poll_intervals", {})

    rules_summary = []
    for rule in autopilot.get("rules", []):
        rules_summary.append({
            "id": rule.get("id", ""),
            "category": rule.get("category", ""),
            "action": rule.get("action", ""),
            "limits": rule.get("limits"),
            "conditions": rule.get("conditions"),
        })

    return {
        "poll_intervals": {
            "approvals_seconds": poll.get("approvals", 1.0),
            "messages_seconds": poll.get("messages", 2.0),
            "status_seconds": poll.get("status", 5.0),
        },
        "autopilot_enabled": autopilot.get("enabled", True),
        "default_watch_minutes": autopilot.get("default_watch_minutes", 20),
        "reset_on_manual_approve": autopilot.get("reset_on_manual_approve", True),
        "rules": rules_summary,
        "loop_detection": autopilot.get("loop_detection", {}),
        "config_file": str(_state._config_manager.config_path),
    }

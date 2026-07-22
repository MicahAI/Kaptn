"""MCP tool: kaptn_approve_category — blanket approve a category for a duration."""

from bridge.mcp import _state
from bridge.mcp._progress import is_bridge_running, read_commands, write_commands

VALID_CATEGORIES = {
    "file_read", "file_write", "file_delete",
    "command_safe", "command_unsafe",
    "search", "tool_call", "unknown",
}


@_state.mcp.tool()
def kaptn_approve_category(
    category: str,
    minutes: int,
    window: str | None = None,
    max_count: int | None = None,
) -> dict:
    """Blanket approve a specific category for a duration.

    Args:
        category: Category to approve (e.g. "command_unsafe", "file_write").
        minutes: Duration in minutes.
        window: Limit to a specific window (default: all windows).
        max_count: Max approvals before auto-expiring (default: unlimited).
    """
    if not is_bridge_running():
        return {"error": "Bridge not running. Call kaptn_connect first."}

    if category not in VALID_CATEGORIES:
        return {"error": f"Invalid category '{category}'. Must be one of: {', '.join(sorted(VALID_CATEGORIES))}"}

    if minutes < 1 or minutes > 480:
        return {"error": "minutes must be between 1 and 480"}

    # Queue command for bridge subprocess
    cmds = read_commands()
    rules = cmds.get("temp_rules", [])
    rules.append({
        "action": "create_rule",
        "category": category,
        "minutes": minutes,
        "window": window,
        "max_count": max_count,
    })
    cmds["temp_rules"] = rules
    write_commands(cmds)

    result = {
        "status": "active",
        "category": category,
        "minutes": minutes,
        "message": "Temp rule sent to bridge. Use kaptn_status to verify.",
    }
    if window:
        result["window"] = window
    if max_count:
        result["max_count"] = max_count
    return result

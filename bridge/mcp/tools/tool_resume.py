"""MCP tool: kaptn_resume — resume AutoPilot after pause from loop detection."""

from bridge.mcp import _state
from bridge.mcp._progress import is_bridge_running, read_commands, write_commands


@_state.mcp.tool()
def kaptn_resume(
    window: str | None = None,
    all: bool = False,
) -> dict:
    """Resume AutoPilot after it paused due to loop detection or escalation.

    Args:
        window: Resume a specific window.
        all: Resume all paused windows.
    """
    if not is_bridge_running():
        return {"error": "Bridge not running. Call kaptn_connect first."}

    if not any([window, all]):
        return {"error": "Provide window or all=true"}

    # Queue resume command for bridge subprocess
    cmds = read_commands()
    rules = cmds.get("temp_rules", [])

    if all:
        rules.append({"action": "resume_all"})
    elif window:
        rules.append({"action": "resume_window", "window": window})

    cmds["temp_rules"] = rules
    write_commands(cmds)

    return {
        "status": "resuming",
        "window": window,
        "all": all,
        "message": "Resume command sent to bridge.",
    }

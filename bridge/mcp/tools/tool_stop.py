"""MCP tool: kaptn_stop — cancel temporary rules or kill the bridge subprocess."""

import logging
import os
import signal

from bridge.mcp import _state
from bridge.mcp._progress import (
    clear_progress,
    is_bridge_running,
    read_commands,
    read_progress,
    write_commands,
)

logger = logging.getLogger(__name__)


@_state.mcp.tool()
def kaptn_stop(
    window: str | None = None,
    rule_id: str | None = None,
    all: bool = False,
    disconnect: bool = False,
) -> dict:
    """Stop auto-approving — cancel a window, a specific rule, or everything.

    Args:
        window: Window to stop watching.
        rule_id: Specific temporary rule ID to cancel.
        all: Stop all temporary rules.
        disconnect: Kill the bridge subprocess entirely (stops all monitoring).
    """
    if disconnect:
        return _kill_bridge()

    if not is_bridge_running():
        return {"error": "Bridge not running. Call kaptn_connect first."}

    if not any([window, rule_id, all]):
        return {"error": "Provide window, rule_id, all=true, or disconnect=true"}

    # Queue stop command for bridge subprocess
    cmds = read_commands()
    rules = cmds.get("temp_rules", [])

    if all:
        rules.append({"action": "stop_all"})
    elif rule_id:
        rules.append({"action": "stop_rule", "rule_id": rule_id})
    elif window:
        rules.append({"action": "stop_window", "window": window})

    cmds["temp_rules"] = rules
    write_commands(cmds)

    return {
        "status": "stopping",
        "window": window,
        "rule_id": rule_id,
        "all": all,
        "message": "Stop command sent to bridge. Use kaptn_status to verify.",
    }


def _kill_bridge() -> dict:
    """Kill the bridge subprocess."""
    progress = read_progress()
    pid = progress.get("pid")

    if not pid or not is_bridge_running():
        clear_progress()
        return {"status": "not_running", "message": "Bridge was not running."}

    try:
        os.kill(pid, signal.SIGTERM)
        logger.info("Sent SIGTERM to bridge worker PID %d", pid)
        clear_progress()
        return {"status": "disconnected", "pid": pid, "message": "Bridge subprocess terminated."}
    except ProcessLookupError:
        clear_progress()
        return {"status": "not_running", "message": "Bridge process already gone."}
    except OSError as e:
        return {"error": f"Failed to kill bridge PID {pid}: {e}"}

"""Kaptn MCP Server — orchestration index.

Each tool has its own module in bridge/mcp/tools/. Shared state lives in
bridge/mcp/_state.py. This file wires everything together and re-exports
symbols so existing callers (tests, CLI) keep working.

Modules:
    _state.py                        — mcp instance + shared state
    _progress.py                     — atomic JSON file helpers (bridge ↔ MCP)
    _bridge_worker.py                — standalone bridge subprocess
    tools/tool_connect.py            — kaptn_connect (spawn bridge)
    tools/tool_watch.py              — kaptn_watch
    tools/tool_approve_category.py   — kaptn_approve_category
    tools/tool_stop.py               — kaptn_stop
    tools/tool_status.py             — kaptn_status
    tools/tool_audit.py              — kaptn_audit
    tools/tool_resume.py             — kaptn_resume
    tools/tool_defaults.py           — kaptn_defaults
    tools/tool_defaults_set.py       — kaptn_defaults_set
"""

import logging

from bridge.autopilot.temp_rule_manager import TempRuleManager
from bridge.config.config_manager import ConfigManager
from bridge.mcp import _state

# Import tool modules — this registers them with the FastMCP instance
from bridge.mcp.tools.tool_connect import kaptn_connect  # noqa: F401
from bridge.mcp.tools.tool_watch import kaptn_watch  # noqa: F401
from bridge.mcp.tools.tool_approve_category import kaptn_approve_category  # noqa: F401
from bridge.mcp.tools.tool_stop import kaptn_stop  # noqa: F401
from bridge.mcp.tools.tool_status import kaptn_status  # noqa: F401
from bridge.mcp.tools.tool_audit import kaptn_audit  # noqa: F401
from bridge.mcp.tools.tool_resume import kaptn_resume  # noqa: F401
from bridge.mcp.tools.tool_defaults import kaptn_defaults  # noqa: F401
from bridge.mcp.tools.tool_defaults_set import kaptn_defaults_set  # noqa: F401

logger = logging.getLogger(__name__)

# Re-export shared state so tests can do `mcp_mod._bridge = ...`
mcp = _state.mcp
_temp_rules = _state._temp_rules
_bridge = _state._bridge
_config_manager = _state._config_manager


def create_kaptn_mcp_server(
    config_path: str = "kaptn.config.json",
    config_manager: ConfigManager | None = None,
    auto_connect: bool = True,
):
    """Initialize the MCP server and optionally spawn the bridge subprocess.

    The bridge runs as a separate OS process that connects to the IDE via CDP.
    Communication happens via atomic JSON files in /tmp/kaptn/.

    Args:
        config_path: Path to kaptn.config.json (passed to bridge worker).
        config_manager: ConfigManager for reading/writing config.
        auto_connect: If True, automatically spawn bridge worker on startup.

    Returns:
        The configured FastMCP ready to run.
    """
    _state._temp_rules = TempRuleManager()
    _state._config_manager = config_manager
    _state._config_path = config_path

    if auto_connect:
        # Spawn bridge subprocess immediately
        result = kaptn_connect(config=config_path)
        logger.info("Auto-connect: %s", result.get("status", "unknown"))

    logger.info("Kaptn MCP server initialized (config=%s)", config_path)
    return _state.mcp

"""Shared MCP server state — mcp instance, bridge ref, temp rules, config manager.

All tool modules import from here to access shared state. The factory
function in mcp_server.py initializes these before the server starts.
"""

import logging
from typing import Any

from mcp.server.fastmcp import FastMCP

from bridge.autopilot.temp_rule_manager import TempRuleManager
from bridge.config.config_manager import ConfigManager

logger = logging.getLogger(__name__)

mcp = FastMCP("kaptn")

# Set by create_kaptn_mcp_server() before the server starts
_temp_rules: TempRuleManager | None = None
_bridge: Any = None  # KaptnBridge reference (avoids circular import)
_config_manager: ConfigManager | None = None
_config_path: str | None = None  # Set by create_kaptn_mcp_server() for subprocess spawning

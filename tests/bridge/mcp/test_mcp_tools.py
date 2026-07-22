"""MCP tool handler tests — orchestration index.

Each tool has its own test file. Shared fixtures live in conftest.py.
This file re-exports all test classes so `pytest test_mcp_tools.py`
still runs the full suite.

Architecture: Tools communicate with the bridge subprocess via JSON files:
    progress.json — bridge → MCP (status, windows, errors)
    commands.json — MCP → bridge (temp rules, config changes)

Test files:
    conftest.py              — shared fixtures (fake progress files, temp config)
    test_progress.py         — _progress.py atomic JSON helpers
    test_tool_connect.py     — kaptn_connect (subprocess spawning)
    test_tool_watch.py       — kaptn_watch
    test_tool_approve_category.py — kaptn_approve_category
    test_tool_stop.py        — kaptn_stop
    test_tool_status.py      — kaptn_status
    test_tool_audit.py       — kaptn_audit
    test_tool_resume.py      — kaptn_resume
    test_tool_defaults.py    — kaptn_defaults
    test_tool_defaults_set.py — kaptn_defaults_set
    test_tool_integration.py — temp rules → RuleEvaluator integration
"""

from tests.bridge.mcp.test_progress import TestProgress  # noqa: F401
from tests.bridge.mcp.test_tool_connect import TestKaptnConnect  # noqa: F401
from tests.bridge.mcp.test_tool_watch import TestKaptnWatch  # noqa: F401
from tests.bridge.mcp.test_tool_approve_category import TestKaptnApproveCategory  # noqa: F401
from tests.bridge.mcp.test_tool_stop import TestKaptnStop  # noqa: F401
from tests.bridge.mcp.test_tool_status import TestKaptnStatus  # noqa: F401
from tests.bridge.mcp.test_tool_audit import TestKaptnAudit  # noqa: F401
from tests.bridge.mcp.test_tool_resume import TestKaptnResume  # noqa: F401
from tests.bridge.mcp.test_tool_defaults import TestKaptnDefaults  # noqa: F401
from tests.bridge.mcp.test_tool_defaults_set import TestKaptnDefaultsSet  # noqa: F401
from tests.bridge.mcp.test_tool_integration import TestTempRulesIntegration  # noqa: F401

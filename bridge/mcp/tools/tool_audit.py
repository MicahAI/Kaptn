"""MCP tool: kaptn_audit — view recent approval decisions from the audit log."""

import os
from pathlib import Path

from bridge.audit.audit_logger import AuditLogger
from bridge.mcp import _state

_KAPTN_HOME = os.path.join(Path.home(), ".kaptn")


@_state.mcp.tool()
def kaptn_audit(
    limit: int = 10,
    window: str | None = None,
    category: str | None = None,
    decision: str | None = None,
) -> dict:
    """View recent approval decisions from the audit log.

    Args:
        limit: Max records to return (default 10, max 50).
        window: Filter by window name.
        category: Filter by category (e.g. "command_unsafe").
        decision: Filter by decision: "approve", "deny", "escalate".
    """
    # Read audit DB path from config, resolve relative paths against ~/.kaptn/
    db_path = "kaptn_audit.db"
    if _state._config_manager:
        cfg = _state._config_manager.load()
        db_path = cfg.get("audit_db", db_path)
    if not os.path.isabs(db_path):
        db_path = os.path.join(_KAPTN_HOME, db_path)

    try:
        audit = AuditLogger(db_path=db_path)
    except Exception as e:
        return {"error": f"Cannot open audit DB: {e}"}

    limit = min(limit, 50)
    records = audit.get_recent_by_time(minutes=60 * 24)  # last 24h
    audit.close()

    # Apply filters
    filtered = []
    for rec in records:
        if window and rec.get("window_name") != window:
            continue
        if category and rec.get("category") != category:
            continue
        if decision and rec.get("decision") != decision:
            continue
        filtered.append({
            "timestamp": rec.get("timestamp", ""),
            "window": rec.get("window_name", ""),
            "tab_id": rec.get("tab_id", ""),
            "category": rec.get("category", ""),
            "action": rec.get("action_text", ""),
            "decision": rec.get("decision", ""),
            "rule_id": rec.get("rule_id", ""),
        })
        if len(filtered) >= limit:
            break

    return {
        "count": len(filtered),
        "records": filtered,
    }

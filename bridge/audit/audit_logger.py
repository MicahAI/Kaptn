"""Audit logger — persistent record of all approval decisions in SQLite."""

import json
import logging
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from bridge.models import ApprovalAction, ApprovalRequest, AuditRecord, DecisionSource

logger = logging.getLogger(__name__)

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS audit_log (
    id TEXT PRIMARY KEY,
    timestamp TEXT NOT NULL,
    window_name TEXT NOT NULL,
    tab_id TEXT NOT NULL DEFAULT '',
    mode TEXT NOT NULL,
    category TEXT NOT NULL,
    action_text TEXT NOT NULL,
    details TEXT NOT NULL,
    decision TEXT NOT NULL,
    source TEXT NOT NULL,
    rule_id TEXT,
    rule_action TEXT,
    limit_status TEXT NOT NULL,
    loop_detected INTEGER NOT NULL DEFAULT 0
)
"""

# Migration: add tab_id column if missing (existing DBs)
MIGRATE_TAB_ID_SQL = """
ALTER TABLE audit_log ADD COLUMN tab_id TEXT NOT NULL DEFAULT ''
"""

INSERT_SQL = """
INSERT INTO audit_log (id, timestamp, window_name, tab_id, mode, category, action_text,
                       details, decision, source, rule_id, rule_action, limit_status, loop_detected)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""


class AuditLogger:
    """Persists approval decisions to a SQLite database.

    Every AutoPilot decision, manual approval, or PWA-initiated action
    is recorded with full context for later review.
    """

    def __init__(self, db_path: str | Path = "kaptn_audit.db") -> None:
        """Initialize the audit logger.

        Args:
            db_path: Path to the SQLite database file. Use ':memory:' for tests.
        """
        self.db_path = str(db_path)
        self._conn: sqlite3.Connection | None = None
        # Writes may come from the async poll loop or hook-server threads
        self._lock = threading.Lock()
        self._init_db()

    def _init_db(self) -> None:
        """Create the database and audit_log table if they don't exist."""
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.execute(CREATE_TABLE_SQL)
        self._conn.commit()

        # Migrate existing DBs: add tab_id column if missing
        cursor = self._conn.execute("PRAGMA table_info(audit_log)")
        columns = {row[1] for row in cursor.fetchall()}
        if "tab_id" not in columns:
            self._conn.execute(MIGRATE_TAB_ID_SQL)
            self._conn.commit()
            logger.info("Migrated audit_log: added tab_id column")

        logger.info("Audit database initialized: %s", self.db_path)

    def log(self, record: AuditRecord) -> str:
        """Write an audit record to the database.

        Args:
            record: The AuditRecord to persist.

        Returns:
            The record ID.
        """
        if self._conn is None:
            raise RuntimeError("Audit database not initialized")

        with self._lock:
            self._conn.execute(INSERT_SQL, (
                record.id,
                record.timestamp.isoformat(),
                record.window_name,
                record.tab_id,
                record.mode,
                record.request.category.value,
                record.request.action,
                json.dumps(record.request.details),
                record.decision.value,
                record.source.value,
                record.rule_id,
                record.rule_action,
                json.dumps(record.limit_status),
                1 if record.loop_detected else 0,
            ))
            self._conn.commit()

        logger.info(
            "Audit: %s %s '%s' (rule=%s, source=%s)",
            record.decision.value.upper(),
            record.request.category.value,
            record.request.action[:50],
            record.rule_id or "none",
            record.source.value,
        )
        return record.id

    def create_record(
        self,
        request: ApprovalRequest,
        decision: ApprovalAction,
        source: DecisionSource,
        rule_id: str | None = None,
        rule_action: str | None = None,
        limit_status: dict | None = None,
        loop_detected: bool = False,
    ) -> AuditRecord:
        """Create and log an AuditRecord from components.

        Convenience method that builds the record and logs it in one step.

        Args:
            request: The approval request.
            decision: The decision made.
            source: Who made the decision.
            rule_id: The rule that matched, if any.
            rule_action: What the rule said to do.
            limit_status: Current limit counters.
            loop_detected: Whether a loop was detected.

        Returns:
            The created and logged AuditRecord.
        """
        tab_id = request.details.get("tab_id", "") if request.details else ""
        record = AuditRecord(
            id=str(uuid.uuid4()),
            timestamp=datetime.now(timezone.utc),
            window_name=request.window_name,
            tab_id=tab_id,
            mode=request.mode,
            request=request,
            decision=decision,
            source=source,
            rule_id=rule_id,
            rule_action=rule_action,
            limit_status=limit_status or {},
            loop_detected=loop_detected,
        )
        self.log(record)
        return record

    def get_recent(self, limit: int = 50, window_name: str | None = None) -> list[dict]:
        """Fetch recent audit records.

        Args:
            limit: Maximum number of records to return.
            window_name: Optional filter by window name.

        Returns:
            List of audit record dicts, newest first.
        """
        if self._conn is None:
            return []

        query = "SELECT * FROM audit_log"
        params: list = []

        if window_name:
            query += " WHERE window_name = ?"
            params.append(window_name)

        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)

        with self._lock:
            cursor = self._conn.execute(query, params)
            columns = [desc[0] for desc in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def get_loops(self, limit: int = 20) -> list[dict]:
        """Fetch records where loop detection triggered.

        Args:
            limit: Maximum number of records to return.

        Returns:
            List of loop-related audit record dicts.
        """
        if self._conn is None:
            return []

        with self._lock:
            cursor = self._conn.execute(
                "SELECT * FROM audit_log WHERE loop_detected = 1 ORDER BY timestamp DESC LIMIT ?",
                (limit,),
            )
            columns = [desc[0] for desc in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def get_recent_by_time(self, minutes: int = 30) -> list[dict]:
        """Fetch audit records from the last N minutes.

        Used on startup to seed the bridge's in-memory state so we don't
        re-process approvals that were already handled in a previous session.

        Args:
            minutes: How far back to look, in minutes.

        Returns:
            List of audit record dicts, newest first.
        """
        if self._conn is None:
            return []

        from datetime import timedelta
        cutoff = (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()

        with self._lock:
            cursor = self._conn.execute(
                "SELECT * FROM audit_log WHERE timestamp >= ? ORDER BY timestamp DESC",
                (cutoff,),
            )
            columns = [desc[0] for desc in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def get_count(self, window_name: str | None = None) -> int:
        """Get total number of audit records.

        Args:
            window_name: Optional filter by window name.

        Returns:
            Total count of matching records.
        """
        if self._conn is None:
            return 0

        with self._lock:
            if window_name:
                cursor = self._conn.execute(
                    "SELECT COUNT(*) FROM audit_log WHERE window_name = ?", (window_name,)
                )
            else:
                cursor = self._conn.execute("SELECT COUNT(*) FROM audit_log")
            return cursor.fetchone()[0]

    def close(self) -> None:
        """Close the database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None
            logger.debug("Audit database closed")

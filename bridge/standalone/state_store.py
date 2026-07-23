"""SQLite-backed AutoPilot state for daemonless (plugin) mode.

One small database holds limit counters, per-minute events, consecutive
runs, loop-detection history, and paused windows. WAL mode and short
transactions keep it safe across concurrent Claude sessions.
"""

import logging
import sqlite3
import time
from pathlib import Path

logger = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS counters (
    scope TEXT NOT NULL,
    rule_id TEXT NOT NULL,
    count INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (scope, rule_id)
);
CREATE TABLE IF NOT EXISTS minute_events (
    scope TEXT NOT NULL,
    rule_id TEXT NOT NULL,
    ts REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS consecutive (
    scope TEXT PRIMARY KEY,
    rule_id TEXT NOT NULL,
    count INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS history (
    scope TEXT NOT NULL,
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    key TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS paused (
    window TEXT PRIMARY KEY
);
"""


class StateStore:
    """Persistent counters and history for the standalone evaluator."""

    def __init__(self, db_path: str | Path) -> None:
        """Open (and initialize) the state database.

        Args:
            db_path: SQLite file path; parent directories are created.
        """
        path = Path(db_path)
        if str(db_path) != ":memory:":
            path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path))
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    # -- limit counters -------------------------------------------------

    def get_count(self, scope: str, rule_id: str) -> int:
        """Return the session counter for (scope, rule)."""
        row = self._conn.execute(
            "SELECT count FROM counters WHERE scope=? AND rule_id=?",
            (scope, rule_id),
        ).fetchone()
        return row[0] if row else 0

    def increment(self, scope: str, rule_id: str, now: float | None = None) -> None:
        """Increment session/minute/consecutive counters after an approval."""
        now = time.time() if now is None else now
        self._conn.execute(
            "INSERT INTO counters (scope, rule_id, count) VALUES (?, ?, 1) "
            "ON CONFLICT(scope, rule_id) DO UPDATE SET count = count + 1",
            (scope, rule_id),
        )
        self._conn.execute(
            "INSERT INTO minute_events (scope, rule_id, ts) VALUES (?, ?, ?)",
            (scope, rule_id, now),
        )
        row = self._conn.execute(
            "SELECT rule_id, count FROM consecutive WHERE scope=?", (scope,)
        ).fetchone()
        if row and row[0] == rule_id:
            self._conn.execute(
                "UPDATE consecutive SET count = count + 1 WHERE scope=?", (scope,)
            )
        else:
            self._conn.execute(
                "INSERT INTO consecutive (scope, rule_id, count) VALUES (?, ?, 1) "
                "ON CONFLICT(scope) DO UPDATE SET rule_id=excluded.rule_id, count=1",
                (scope, rule_id),
            )
        self._conn.commit()

    def minute_count(self, scope: str, rule_id: str, now: float | None = None,
                     window_seconds: float = 60.0) -> int:
        """Count (and prune) events in the rolling minute window."""
        now = time.time() if now is None else now
        self._conn.execute(
            "DELETE FROM minute_events WHERE ts < ?", (now - window_seconds,)
        )
        row = self._conn.execute(
            "SELECT COUNT(*) FROM minute_events WHERE scope=? AND rule_id=? AND ts >= ?",
            (scope, rule_id, now - window_seconds),
        ).fetchone()
        self._conn.commit()
        return row[0]

    def consecutive_for(self, scope: str, rule_id: str) -> int:
        """Return the consecutive count if rule_id was the last rule in scope."""
        row = self._conn.execute(
            "SELECT rule_id, count FROM consecutive WHERE scope=?", (scope,)
        ).fetchone()
        if row and row[0] == rule_id:
            return row[1]
        return 0

    def counters_snapshot(self) -> dict[tuple[str, str], int]:
        """All session counters, keyed by (scope, rule_id)."""
        rows = self._conn.execute(
            "SELECT scope, rule_id, count FROM counters WHERE count > 0"
        ).fetchall()
        return {(scope, rule_id): count for scope, rule_id, count in rows}

    def reset_all(self) -> None:
        """Clear all counters, history, and pauses."""
        for table in ("counters", "minute_events", "consecutive", "history", "paused"):
            self._conn.execute(f"DELETE FROM {table}")  # noqa: S608 — fixed names
        self._conn.commit()
        logger.info("Standalone state reset")

    def reset_rule(self, rule_id: str) -> None:
        """Clear counters for one rule across all scopes."""
        self._conn.execute("DELETE FROM counters WHERE rule_id=?", (rule_id,))
        self._conn.execute("DELETE FROM minute_events WHERE rule_id=?", (rule_id,))
        self._conn.execute("DELETE FROM consecutive WHERE rule_id=?", (rule_id,))
        self._conn.commit()

    # -- loop-detection history -----------------------------------------

    def get_history(self, scope: str, limit: int = 20) -> list[str]:
        """Return the most recent action keys for a scope, oldest first."""
        rows = self._conn.execute(
            "SELECT key FROM history WHERE scope=? ORDER BY seq DESC LIMIT ?",
            (scope, limit),
        ).fetchall()
        return [key for (key,) in reversed(rows)]

    def set_history(self, scope: str, keys: list[str], limit: int = 20) -> None:
        """Replace a scope's history with the given keys (kept to limit)."""
        self._conn.execute("DELETE FROM history WHERE scope=?", (scope,))
        self._conn.executemany(
            "INSERT INTO history (scope, key) VALUES (?, ?)",
            [(scope, key) for key in keys[-limit:]],
        )
        self._conn.commit()

    # -- paused windows --------------------------------------------------

    def get_paused(self) -> set[str]:
        """Windows currently paused (loop detected)."""
        rows = self._conn.execute("SELECT window FROM paused").fetchall()
        return {window for (window,) in rows}

    def add_paused(self, window: str) -> None:
        """Persist a paused window."""
        self._conn.execute(
            "INSERT OR IGNORE INTO paused (window) VALUES (?)", (window,)
        )
        self._conn.commit()

    def close(self) -> None:
        """Close the database connection."""
        self._conn.close()

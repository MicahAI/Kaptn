"""Daemonless evaluation — builds the AutoPilot stack per hook invocation.

Used by the plugin's PreToolUse hook script: no server, no venv, stdlib
only. Reuses the shared classifier/rules/adapter/audit; only limit and
loop state moves to the SQLite StateStore.
"""

import logging
import os
from pathlib import Path

from bridge.audit.audit_logger import AuditLogger
from bridge.autopilot.auto_pilot_engine import AutoPilotEngine
from bridge.autopilot.loop_detector import LoopDetector
from bridge.autopilot.rule_evaluator import RuleEvaluator
from bridge.claude.claude_adapter import ClaudeAdapter
from bridge.config.config_manager import ConfigManager
from bridge.standalone.state_store import StateStore

logger = logging.getLogger(__name__)

DEFAULT_STATE_DIR = Path.home() / ".kaptn"


class PersistentRuleEvaluator(RuleEvaluator):
    """RuleEvaluator whose limit counters live in a StateStore.

    Matching logic is inherited unchanged; only the counter reads/writes
    are overridden so limits survive across hook processes.
    """

    def __init__(self, rules: list[dict], store: StateStore) -> None:
        """Initialize with rules and a persistent store."""
        super().__init__(rules)
        self.store = store

    def _check_limits(self, rule: dict, scope: str) -> tuple[bool, str]:
        """Check limits against persisted counters."""
        limits = rule.get("limits")
        if not limits:
            return False, ""
        rule_id = rule.get("id", "unnamed")

        max_session = limits.get("max_per_session")
        if max_session is not None:
            current = self.store.get_count(scope, rule_id)
            if current >= max_session:
                return True, f"max_per_session ({current}/{max_session})"

        max_minute = limits.get("max_per_minute")
        if max_minute is not None:
            current = self.store.minute_count(scope, rule_id)
            if current >= max_minute:
                return True, f"max_per_minute ({current}/{max_minute})"

        max_consecutive = limits.get("max_consecutive")
        if max_consecutive is not None:
            current = self.store.consecutive_for(scope, rule_id)
            if current >= max_consecutive:
                return True, f"max_consecutive ({current}/{max_consecutive})"

        return False, ""

    def _increment_counters(self, rule_id: str, scope: str) -> None:
        """Persist counter increments."""
        self.store.increment(scope, rule_id)

    def reset_rule_limit(self, rule_id: str) -> None:
        """Reset one rule's counters across all scopes."""
        self.store.reset_rule(rule_id)

    def reset_limits(self) -> None:
        """Reset all persisted counters and state."""
        self.store.reset_all()

    def get_limit_status(self) -> dict[str, dict]:
        """Limit status built from persisted counters."""
        counters = self.store.counters_snapshot()
        status = {}
        for rule in self.rules:
            rule_id = rule.get("id", "unnamed")
            limits = rule.get("limits", {})
            if not limits:
                continue
            scopes = {
                scope: count for (scope, rid), count in counters.items()
                if rid == rule_id
            }
            status[rule_id] = {
                "session_count": sum(scopes.values()),
                "minute_count": 0,  # rolling window lives in the store
                "consecutive_count": 0,
                "limits": limits,
                "scopes": scopes,
            }
        return status


def config_path() -> Path:
    """Resolve the standalone config path (cwd-independent).

    $KAPTN_CONFIG wins; otherwise ~/.kaptn/kaptn.config.json, which
    ConfigManager creates with defaults on first load.
    """
    env = os.environ.get("KAPTN_CONFIG")
    if env:
        return Path(env)
    return DEFAULT_STATE_DIR / "kaptn.config.json"


def build_stack(state_dir: Path | None = None):
    """Construct the standalone stack.

    Args:
        state_dir: Override for the state directory (tests).

    Returns:
        Tuple of (adapter, engine, store, audit).
    """
    state_dir = state_dir or DEFAULT_STATE_DIR
    cfg = ConfigManager(str(config_path() if state_dir == DEFAULT_STATE_DIR
                             else state_dir / "kaptn.config.json")).load()

    autopilot_cfg = cfg.get("autopilot", {})
    loop_cfg = autopilot_cfg.get("loop_detection", {})

    store = StateStore(state_dir / "kaptn_state.db")
    evaluator = PersistentRuleEvaluator(autopilot_cfg.get("rules", []), store)
    detector = LoopDetector(
        same_action_threshold=loop_cfg.get("same_action_threshold", 3),
        oscillation_threshold=loop_cfg.get("oscillation_threshold", 3),
        history_size=loop_cfg.get("history_size", 20),
    )
    engine = AutoPilotEngine(
        rule_evaluator=evaluator,
        loop_detector=detector,
        enabled=autopilot_cfg.get("enabled", True),
    )

    audit_db = cfg.get("audit_db")
    if not audit_db or audit_db == "kaptn_audit.db":
        audit_db = str(state_dir / "kaptn_audit.db")
    audit = AuditLogger(db_path=audit_db)

    adapter = ClaudeAdapter(engine, audit)
    return adapter, engine, store, audit


def handle_event(event: dict, state_dir: Path | None = None) -> dict | None:
    """Evaluate one hook event with persistent state.

    Args:
        event: The PreToolUse hook event.
        state_dir: Override for the state directory (tests).

    Returns:
        The hook response dict, or None for non-PreToolUse events.
    """
    adapter, engine, store, audit = build_stack(state_dir)
    try:
        scope = str(event.get("session_id") or "global") if isinstance(event, dict) else "global"

        # Seed per-scope loop history and persisted pauses into the engine
        seeded = store.get_history(scope)
        engine.loop_detector._history.extend(seeded)
        prior_paused = store.get_paused()
        for window in prior_paused:
            engine.pause_window(window)

        result = adapter.handle_hook_event(event)

        store.set_history(scope, engine.loop_detector.history)
        for window in engine.paused_windows - prior_paused:
            store.add_paused(window)
        return result
    finally:
        audit.close()
        store.close()


def reset_state(state_dir: Path | None = None) -> dict:
    """Clear all standalone limits, history, and pauses."""
    state_dir = state_dir or DEFAULT_STATE_DIR
    store = StateStore(state_dir / "kaptn_state.db")
    try:
        store.reset_all()
    finally:
        store.close()
    return {"status": "reset"}

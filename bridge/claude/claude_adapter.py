"""Claude Code adapter — evaluates PreToolUse hook events through AutoPilot.

This is the push-based counterpart of the CDP IDE drivers: instead of
polling a DOM for approval dialogs, Claude Code sends each tool call here
and waits for the verdict.
"""

import logging
import threading
from pathlib import PurePath

from bridge.audit.audit_logger import AuditLogger
from bridge.autopilot.auto_pilot_engine import AutoPilotEngine
from bridge.autopilot.escalation_handler import EscalationHandler
from bridge.claude.tool_classifier import classify
from bridge.models import ApprovalAction, ApprovalRequest, DecisionSource

logger = logging.getLogger(__name__)

_DECISION_MAP = {
    ApprovalAction.APPROVE: "allow",
    ApprovalAction.DENY: "deny",
    ApprovalAction.ESCALATE: "ask",
}


class ClaudeAdapter:
    """Evaluates Claude Code hook events with the shared AutoPilot engine.

    Decisions map to Claude Code's PreToolUse hook contract:
    APPROVE → 'allow', DENY → 'deny', ESCALATE → 'ask' (falls back to
    Claude Code's normal permission prompt — fail-safe by design).
    """

    def __init__(
        self,
        autopilot: AutoPilotEngine,
        audit: AuditLogger,
        escalation: EscalationHandler | None = None,
    ) -> None:
        """Initialize the adapter.

        Args:
            autopilot: The shared AutoPilot engine (rules, limits, loops).
            audit: The shared audit logger.
            escalation: Optional escalation handler for 'ask' decisions.
        """
        self.autopilot = autopilot
        self.audit = audit
        self.escalation = escalation
        self._lock = threading.Lock()

    def handle_hook_event(self, event: dict) -> dict | None:
        """Process a Claude Code hook event and return the hook response.

        Args:
            event: The parsed hook event JSON from Claude Code's stdin
                (session_id, cwd, hook_event_name, tool_name, tool_input).

        Returns:
            A PreToolUse hook response dict, or None for events this
            adapter doesn't handle (non-PreToolUse).
        """
        if not isinstance(event, dict) or event.get("hook_event_name") != "PreToolUse":
            return None

        tool_name = str(event.get("tool_name", ""))
        tool_input = event.get("tool_input") or {}
        category, action_text, details = classify(tool_name, tool_input)

        session_id = str(event.get("session_id", ""))
        cwd = str(event.get("cwd", ""))
        window = f"claude:{PurePath(cwd).name}" if cwd else "claude"
        details.update({
            "tab_id": session_id,
            "session_id": session_id,
            "cwd": cwd,
            "type": "claude_hook",
        })

        request = ApprovalRequest(
            category=category,
            action=action_text,
            details=details,
            window_name=window,
            mode="claude",
        )

        with self._lock:
            action, rule_id, reason = self.autopilot.evaluate(request)
            limit_status = self.autopilot.rule_evaluator.get_limit_status()
            self.audit.create_record(
                request=request,
                decision=action,
                source=DecisionSource.AUTOPILOT,
                rule_id=rule_id,
                rule_action=action.value,
                limit_status=limit_status,
                loop_detected=(reason == "loop_detected"),
            )

        if action == ApprovalAction.ESCALATE and self.escalation:
            self.escalation.escalate(request, reason, rule_id)

        decision = _DECISION_MAP[action]
        logger.info(
            "[%s] Claude %s: %s '%s' (rule=%s, reason=%s)",
            window, decision.upper(), category.value, action_text[:60], rule_id, reason,
        )
        return {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": decision,
                "permissionDecisionReason": self._reason_text(action, rule_id, reason),
            }
        }

    def status(self) -> dict:
        """Snapshot of live AutoPilot state for the /status endpoint.

        Returns:
            Dict with autopilot enabled flag, paused windows, rule count,
            and per-rule limit counters (including per-scope breakdown).
        """
        with self._lock:
            return {
                "autopilot_enabled": self.autopilot.enabled,
                "paused_windows": sorted(self.autopilot.paused_windows),
                "rules_loaded": len(self.autopilot.rule_evaluator.rules),
                "limit_status": self.autopilot.rule_evaluator.get_limit_status(),
            }

    def reset(self) -> dict:
        """Reset AutoPilot state: rule limits, loop history, paused windows.

        Exposed via the hook server's /reset endpoint so `kaptn reset` can
        clear limit_exceeded escalations without restarting the server.

        Returns:
            Status dict for the HTTP response.
        """
        with self._lock:
            self.autopilot.rule_evaluator.reset_limits()
            self.autopilot.loop_detector.clear()
            self.autopilot.resume_all()
        logger.info("AutoPilot state reset (limits, loop history, pauses)")
        return {"status": "reset"}

    @staticmethod
    def _reason_text(action: ApprovalAction, rule_id: str | None, reason: str) -> str:
        """Build the human/model-facing explanation for a decision."""
        rule_part = f"rule={rule_id}" if rule_id else "no rule"
        if action == ApprovalAction.APPROVE:
            return f"Kaptn AutoPilot approved ({rule_part})"
        if action == ApprovalAction.DENY:
            return f"Kaptn AutoPilot denied ({rule_part}, {reason})"
        return f"Kaptn escalated to user ({reason})"

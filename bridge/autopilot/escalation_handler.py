"""Escalation handler — routes unhandled approvals to the user."""

import logging

from bridge.models import ApprovalRequest, EscalationEvent

logger = logging.getLogger(__name__)


class EscalationHandler:
    """Routes escalation events to connected clients or logs them.

    When AutoPilot can't make a decision (no rule, limit hit, loop),
    this handler creates an escalation event and notifies any listeners.
    """

    def __init__(self) -> None:
        """Initialize the escalation handler."""
        self._listeners: list[callable] = []
        self._pending: list[EscalationEvent] = []

    def escalate(self, request: ApprovalRequest, reason: str, rule_id: str | None = None,
                 limit_details: dict | None = None) -> EscalationEvent:
        """Create and dispatch an escalation event.

        Args:
            request: The approval request that couldn't be handled.
            reason: Why AutoPilot escalated (e.g., 'no_matching_rule').
            rule_id: The rule that triggered escalation, if any.
            limit_details: Current limit counters, if escalation was limit-related.

        Returns:
            The created EscalationEvent.
        """
        event = EscalationEvent(
            request=request,
            reason=reason,
            rule_id=rule_id,
            limit_details=limit_details or {},
        )

        self._pending.append(event)

        logger.info(
            "Escalation: reason=%s category=%s action='%s' window='%s'",
            reason, request.category.value, request.action, request.window_name,
        )

        for listener in self._listeners:
            try:
                listener(event)
            except Exception:
                logger.exception("Error in escalation listener")

        return event

    def add_listener(self, callback: callable) -> None:
        """Register a callback for escalation events.

        Args:
            callback: Function that accepts an EscalationEvent.
        """
        self._listeners.append(callback)

    def remove_listener(self, callback: callable) -> None:
        """Remove a previously registered callback.

        Args:
            callback: The callback to remove.
        """
        self._listeners = [cb for cb in self._listeners if cb is not callback]

    def get_pending(self) -> list[EscalationEvent]:
        """Return all pending escalation events.

        Returns:
            List of unresolved EscalationEvent objects.
        """
        return list(self._pending)

    def clear_pending(self) -> None:
        """Clear all pending escalation events."""
        count = len(self._pending)
        self._pending.clear()
        logger.debug("Cleared %d pending escalations", count)

"""Temporary rule manager — CRUD for time-boxed approval rules with TTL."""

import logging
import time
import uuid
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

MAX_TTL_MINUTES = 480  # 8 hours
MAX_CONCURRENT_RULES = 10
DEFAULT_EXCLUDED_CATEGORIES = frozenset({"file_delete"})


@dataclass
class TempRule:
    """A temporary approval rule with a time-to-live.

    Attributes:
        id: Unique rule identifier (auto-generated).
        category: ApprovalCategory value to match (e.g. "command_unsafe").
        action: "approve", "deny", or "escalate".
        window: Optional window name filter (None = all windows).
        created_at: Unix timestamp when the rule was created.
        expires_at: Unix timestamp when the rule expires.
        max_count: Max approvals before auto-expiring (None = unlimited).
        approved_count: Number of approvals made under this rule.
        source: Who created the rule (e.g. "mcp", "cli").
    """

    id: str = field(default_factory=lambda: f"tmp-{uuid.uuid4().hex[:8]}")
    category: str = ""
    action: str = "approve"
    window: str | None = None
    created_at: float = field(default_factory=time.time)
    expires_at: float = 0.0
    max_count: int | None = None
    approved_count: int = 0
    source: str = "mcp"

    @property
    def expired(self) -> bool:
        """Check if this rule has expired by time or count."""
        if time.time() >= self.expires_at:
            return True
        if self.max_count is not None and self.approved_count >= self.max_count:
            return True
        return False

    @property
    def minutes_remaining(self) -> float:
        """Minutes until this rule expires (0 if already expired)."""
        remaining = (self.expires_at - time.time()) / 60.0
        return max(0.0, remaining)

    def to_dict(self) -> dict:
        """Serialize to a dict for API responses."""
        return {
            "rule_id": self.id,
            "category": self.category,
            "action": self.action,
            "window": self.window,
            "expires_in_minutes": round(self.minutes_remaining, 1),
            "approved_count": self.approved_count,
            "max_count": self.max_count,
            "source": self.source,
        }


class TempRuleManager:
    """Manages temporary approval rules with TTL.

    Temporary rules layer on top of static rules from config. They are
    checked first (newest first) during rule evaluation. Expired rules
    are cleaned up lazily on each access.
    """

    def __init__(self) -> None:
        self._rules: dict[str, TempRule] = {}

    def create_rule(
        self,
        category: str,
        minutes: int,
        action: str = "approve",
        window: str | None = None,
        max_count: int | None = None,
        source: str = "mcp",
    ) -> TempRule:
        """Create a new temporary rule with TTL.

        Args:
            category: ApprovalCategory value to match.
            minutes: Duration in minutes (capped at MAX_TTL_MINUTES).
            action: "approve", "deny", or "escalate".
            window: Optional window name filter.
            max_count: Max approvals before auto-expiring.
            source: Who created this rule.

        Returns:
            The created TempRule.

        Raises:
            ValueError: If category is excluded or limits exceeded.
        """
        self._cleanup_expired()

        if category in DEFAULT_EXCLUDED_CATEGORIES:
            raise ValueError(
                f"Category '{category}' is excluded by default. "
                f"Excluded: {', '.join(DEFAULT_EXCLUDED_CATEGORIES)}"
            )

        if len(self._rules) >= MAX_CONCURRENT_RULES:
            raise ValueError(
                f"Max concurrent temporary rules reached ({MAX_CONCURRENT_RULES}). "
                f"Cancel existing rules first."
            )

        if minutes < 1:
            raise ValueError("Duration must be at least 1 minute")

        capped_minutes = min(minutes, MAX_TTL_MINUTES)
        if capped_minutes != minutes:
            logger.warning("TTL capped from %d to %d minutes", minutes, capped_minutes)

        rule = TempRule(
            category=category,
            action=action,
            window=window,
            expires_at=time.time() + (capped_minutes * 60),
            max_count=max_count,
            source=source,
        )

        self._rules[rule.id] = rule
        logger.info(
            "Created temp rule '%s': %s %s for %dm (window=%s, max_count=%s)",
            rule.id, action, category, capped_minutes, window or "all", max_count,
        )
        return rule

    def create_watch(
        self,
        window: str,
        minutes: int,
        categories: list[str] | None = None,
        source: str = "mcp",
    ) -> list[TempRule]:
        """Create a watch — one temp rule per category for a window.

        Args:
            window: Window name to watch.
            minutes: Duration in minutes.
            categories: Categories to approve (default: all except excluded).
            source: Who created this watch.

        Returns:
            List of created TempRules.
        """
        if categories is None:
            categories = [
                "file_read", "file_write", "command_safe",
                "command_unsafe", "search", "tool_call",
            ]

        rules = []
        for cat in categories:
            if cat in DEFAULT_EXCLUDED_CATEGORIES:
                logger.warning("Skipping excluded category '%s' in watch", cat)
                continue
            rule = self.create_rule(
                category=cat,
                minutes=minutes,
                action="approve",
                window=window,
                source=source,
            )
            rules.append(rule)

        logger.info(
            "Watch created: window='%s', %d rules, %dm TTL",
            window, len(rules), minutes,
        )
        return rules

    def cancel_rule(self, rule_id: str) -> TempRule | None:
        """Cancel a specific temporary rule.

        Args:
            rule_id: The rule ID to cancel.

        Returns:
            The cancelled rule, or None if not found.
        """
        rule = self._rules.pop(rule_id, None)
        if rule:
            logger.info("Cancelled temp rule '%s' (%s %s)", rule.id, rule.action, rule.category)
        return rule

    def cancel_window(self, window: str) -> list[TempRule]:
        """Cancel all temporary rules for a specific window.

        Args:
            window: Window name whose rules should be cancelled.

        Returns:
            List of cancelled rules.
        """
        cancelled = []
        for rule_id in list(self._rules):
            rule = self._rules[rule_id]
            if rule.window == window:
                self._rules.pop(rule_id)
                cancelled.append(rule)
        if cancelled:
            logger.info("Cancelled %d temp rules for window '%s'", len(cancelled), window)
        return cancelled

    def cancel_all(self) -> list[TempRule]:
        """Cancel all temporary rules.

        Returns:
            List of all cancelled rules.
        """
        cancelled = list(self._rules.values())
        self._rules.clear()
        if cancelled:
            logger.info("Cancelled all %d temp rules", len(cancelled))
        return cancelled

    def get_rule(self, rule_id: str) -> TempRule | None:
        """Get a specific temporary rule by ID.

        Args:
            rule_id: The rule ID to look up.

        Returns:
            The TempRule, or None if not found or expired.
        """
        rule = self._rules.get(rule_id)
        if rule and rule.expired:
            self._rules.pop(rule_id, None)
            return None
        return rule

    def get_active_rules(self, window: str | None = None) -> list[TempRule]:
        """Get all active (non-expired) temporary rules.

        Args:
            window: Optional filter by window name.

        Returns:
            List of active TempRules, newest first.
        """
        self._cleanup_expired()
        rules = list(self._rules.values())
        if window:
            rules = [r for r in rules if r.window is None or r.window == window]
        return sorted(rules, key=lambda r: r.created_at, reverse=True)

    def match(self, category: str, window: str | None = None) -> TempRule | None:
        """Find the first active temp rule matching a category and window.

        Args:
            category: The approval category to match.
            window: The window name to match.

        Returns:
            The matching TempRule (newest first), or None.
        """
        for rule in self.get_active_rules(window):
            if rule.category == category or rule.category == "*":
                return rule
        return None

    def record_approval(self, rule_id: str) -> None:
        """Increment the approval count for a rule.

        Args:
            rule_id: The rule ID that was used for an approval.
        """
        rule = self._rules.get(rule_id)
        if rule:
            rule.approved_count += 1
            if rule.expired:
                logger.info("Temp rule '%s' exhausted (count %d/%d)", rule.id, rule.approved_count, rule.max_count)
                self._rules.pop(rule_id, None)

    def _cleanup_expired(self) -> None:
        """Remove expired rules from the active set."""
        expired_ids = [rid for rid, rule in self._rules.items() if rule.expired]
        for rid in expired_ids:
            rule = self._rules.pop(rid)
            logger.info("Temp rule '%s' expired (%s %s)", rule.id, rule.action, rule.category)

    @property
    def count(self) -> int:
        """Number of active temporary rules."""
        self._cleanup_expired()
        return len(self._rules)

    def status(self) -> dict:
        """Get a summary of all active temporary rules.

        Returns:
            Dict with active rules grouped by window.
        """
        self._cleanup_expired()
        windows: dict[str, list[dict]] = {}
        for rule in self._rules.values():
            key = rule.window or "__all__"
            windows.setdefault(key, []).append(rule.to_dict())
        return {
            "active_rules": len(self._rules),
            "max_rules": MAX_CONCURRENT_RULES,
            "windows": windows,
        }

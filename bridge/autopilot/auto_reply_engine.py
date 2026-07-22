"""Auto-reply engine — detects conversational stalls and injects replies."""

import logging
import time

from bridge.autopilot.auto_reply_rule import AutoReplyRule

logger = logging.getLogger(__name__)

# Default rules shipped with Kaptn
DEFAULT_AUTO_REPLY_RULES: list[dict] = [
    {
        "id": "proceed-yes",
        "pattern": "should I proceed",
        "reply": "yes",
        "match": "end",
        "enabled": True,
    },
    {
        "id": "continue-yes",
        "pattern": "shall I continue|want me to continue|do you want me to",
        "reply": "yes, continue",
        "match": "end",
        "enabled": True,
    },
    {
        "id": "commit-yes",
        "pattern": "ready to commit|should I commit",
        "reply": "yes",
        "match": "end",
        "enabled": True,
    },
    {
        "id": "review-yes",
        "pattern": "want to review|want me to review",
        "reply": "yes",
        "match": "end",
        "enabled": True,
    },
    {
        "id": "discuss-yes",
        "pattern": "want to discuss|shall we discuss",
        "reply": "no, just implement it",
        "match": "end",
        "enabled": True,
    },
    {
        "id": "update-docs-yes",
        "pattern": "update the documentation|update docs",
        "reply": "yes",
        "match": "end",
        "enabled": True,
    },
    {
        "id": "update-tests-yes",
        "pattern": "update.*tests|add.*tests",
        "reply": "yes",
        "match": "end",
        "enabled": True,
    },
]


class AutoReplyEngine:
    """Evaluates the last CASCADE message against auto-reply rules.

    When Cascade finishes generating and asks a routine question, this
    engine detects the stall and returns the appropriate reply. It
    enforces cooldown and consecutive limits to prevent runaway automation.

    Attributes:
        rules: Ordered list of AutoReplyRule instances.
        cooldown_seconds: Minimum seconds between auto-replies.
        max_consecutive: Max consecutive auto-replies before pausing.
    """

    def __init__(
        self,
        rules: list[AutoReplyRule] | None = None,
        cooldown_seconds: float = 10.0,
        max_consecutive: int = 5,
    ) -> None:
        """Initialize the auto-reply engine.

        Args:
            rules: Ordered list of rules. Defaults to built-in rules.
            cooldown_seconds: Minimum seconds between auto-replies per window.
            max_consecutive: Max consecutive replies before pausing.
        """
        if rules is None:
            rules = [AutoReplyRule.from_dict(r) for r in DEFAULT_AUTO_REPLY_RULES]
        self.rules = rules
        self.cooldown_seconds = cooldown_seconds
        self.max_consecutive = max_consecutive
        self._last_reply_time: dict[str, float] = {}  # window -> timestamp
        self._consecutive_count: dict[str, int] = {}  # window -> count
        self._paused_windows: set[str] = set()
        self._last_checked_text: dict[str, str] = {}  # window -> last text we checked

    def check(self, window_name: str, last_assistant_text: str) -> tuple[str | None, str | None]:
        """Check if the last assistant message matches an auto-reply rule.

        Args:
            window_name: The IDE window name.
            last_assistant_text: The text of the last CASCADE (assistant) message.

        Returns:
            Tuple of (reply_text, rule_id) if a match is found.
            (None, None) if no match, paused, on cooldown, or already checked.
        """
        if not last_assistant_text:
            return None, None

        if window_name in self._paused_windows:
            return None, None

        # Don't re-check the same message text (avoid duplicate replies)
        if self._last_checked_text.get(window_name) == last_assistant_text:
            return None, None
        self._last_checked_text[window_name] = last_assistant_text

        # Check cooldown
        now = time.time()
        last_time = self._last_reply_time.get(window_name, 0)
        if now - last_time < self.cooldown_seconds:
            logger.debug(
                "Auto-reply cooldown active for '%s' (%.1fs remaining)",
                window_name, self.cooldown_seconds - (now - last_time),
            )
            return None, None

        # Evaluate rules in order (first match wins)
        for rule in self.rules:
            if rule.matches(last_assistant_text):
                # Check consecutive limit
                count = self._consecutive_count.get(window_name, 0) + 1
                if count > self.max_consecutive:
                    logger.warning(
                        "Auto-reply consecutive limit reached for '%s' (%d/%d) — pausing",
                        window_name, count, self.max_consecutive,
                    )
                    self._paused_windows.add(window_name)
                    return None, None

                # Match found — record and return
                self._last_reply_time[window_name] = now
                self._consecutive_count[window_name] = count
                logger.info(
                    "Auto-reply match: rule='%s' pattern='%s' reply='%s' window='%s' (%d/%d)",
                    rule.id, rule.pattern, rule.reply, window_name,
                    count, self.max_consecutive,
                )
                return rule.reply, rule.id

        return None, None

    def reset_consecutive(self, window_name: str) -> None:
        """Reset the consecutive counter for a window.

        Call this when a non-auto-reply event occurs (e.g., user sends
        a message manually, or an approval is handled).

        Args:
            window_name: The window to reset.
        """
        if window_name in self._consecutive_count:
            self._consecutive_count[window_name] = 0

    def resume_window(self, window_name: str) -> None:
        """Resume auto-reply for a paused window.

        Args:
            window_name: The window to resume.
        """
        self._paused_windows.discard(window_name)
        self._consecutive_count[window_name] = 0
        logger.info("Auto-reply resumed for window '%s'", window_name)

    def resume_all(self) -> None:
        """Resume auto-reply for all paused windows."""
        self._paused_windows.clear()
        self._consecutive_count.clear()
        logger.info("Auto-reply resumed for all windows")

    @property
    def paused_windows(self) -> set[str]:
        """Return the set of paused window names."""
        return set(self._paused_windows)

    def get_status(self) -> dict:
        """Return current auto-reply status for diagnostics.

        Returns:
            Dict with rules, cooldown, limits, and per-window state.
        """
        return {
            "rules": [
                {"id": r.id, "pattern": r.pattern, "reply": r.reply, "enabled": r.enabled}
                for r in self.rules
            ],
            "cooldown_seconds": self.cooldown_seconds,
            "max_consecutive": self.max_consecutive,
            "paused_windows": list(self._paused_windows),
            "consecutive_counts": dict(self._consecutive_count),
        }

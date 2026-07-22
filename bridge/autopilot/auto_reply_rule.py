"""Auto-reply rule — defines a pattern-to-reply mapping for conversational stalls."""

from dataclasses import dataclass, field


@dataclass
class AutoReplyRule:
    """A single auto-reply rule that maps a message pattern to a response.

    Rules are evaluated in order (first match wins) against the tail end
    of the last CASCADE message. If the pattern matches and the rule is
    enabled, the reply is injected into the chat input.

    Attributes:
        id: Unique rule identifier.
        pattern: Case-insensitive pattern to match. Pipe '|' for alternatives.
        reply: Text to inject as the user's response.
        match: Where to match — 'end' (tail of message) or 'anywhere'.
        enabled: Whether the rule is active.
    """

    id: str
    pattern: str
    reply: str
    match: str = "end"
    enabled: bool = True

    # How many chars from the end of the message to search for the pattern
    _TAIL_LENGTH: int = field(default=200, repr=False)

    def matches(self, text: str) -> bool:
        """Check if this rule's pattern matches the given message text.

        Args:
            text: The CASCADE message text to match against.

        Returns:
            True if the pattern matches according to the rule's match type.
        """
        if not self.enabled or not text or not self.pattern:
            return False

        text_lower = text.lower().strip()
        alternatives = [p.strip() for p in self.pattern.lower().split("|")]

        if self.match == "end":
            tail = text_lower[-self._TAIL_LENGTH:]
            return any(alt in tail for alt in alternatives)

        # match == "anywhere"
        return any(alt in text_lower for alt in alternatives)

    @classmethod
    def from_dict(cls, data: dict) -> "AutoReplyRule":
        """Create an AutoReplyRule from a config dict.

        Args:
            data: Dict with keys: id, pattern, reply, match (optional), enabled (optional).

        Returns:
            An AutoReplyRule instance.
        """
        return cls(
            id=data["id"],
            pattern=data["pattern"],
            reply=data["reply"],
            match=data.get("match", "end"),
            enabled=data.get("enabled", True),
        )

"""Rule evaluator — matches approval requests against configured rules."""

import fnmatch
import logging
import time
from collections import defaultdict

from bridge.autopilot.temp_rule_manager import TempRuleManager
from bridge.models import ApprovalAction, ApprovalCategory, ApprovalRequest

logger = logging.getLogger(__name__)


class RuleEvaluator:
    """Evaluates approval requests against a list of configured rules.

    Rules are checked in order — first match wins. If no rule matches,
    the request is escalated. Limits are tracked per rule *per scope* and
    enforced: the scope is the Claude session id when present (each Claude
    conversation gets its own allowance), otherwise the window name (each
    IDE window gets its own), falling back to a single global scope.
    """

    def __init__(self, rules: list[dict]) -> None:
        """Initialize the rule evaluator.

        Args:
            rules: List of rule dicts from config. Each rule has:
                - id (str): Unique rule identifier
                - category (str): ApprovalCategory value to match
                - action (str): "approve", "deny", or "escalate"
                - conditions (dict, optional): path_patterns, exclude_patterns, command_patterns
                - limits (dict, optional): max_per_session, max_per_minute, max_consecutive
        """
        self.rules = rules
        self.temp_rules: TempRuleManager | None = None
        # Counters keyed by (scope, rule_id) — scope is session/window
        self._session_counts: dict[tuple[str, str], int] = defaultdict(int)
        self._minute_timestamps: dict[tuple[str, str], list[float]] = defaultdict(list)
        self._consecutive_counts: dict[tuple[str, str], int] = defaultdict(int)
        self._last_rule_id: dict[str, str | None] = {}

    @staticmethod
    def _scope_for(request: ApprovalRequest) -> str:
        """Determine the limit scope for a request.

        Claude requests carry a session_id in details — limits are per
        conversation. CDP requests fall back to the window name.
        """
        details = request.details or {}
        return details.get("session_id") or request.window_name or "global"

    def evaluate(self, request: ApprovalRequest) -> tuple[ApprovalAction, str | None, str]:
        """Evaluate a request against all rules, returning the first match.

        Args:
            request: The approval request to evaluate.

        Returns:
            Tuple of (action, rule_id, reason).
        """
        # Check temporary rules first (newest first, take precedence)
        if self.temp_rules:
            window = request.window_name
            temp = self.temp_rules.match(request.category.value, window)
            if temp:
                action = ApprovalAction(temp.action) if temp.action in ApprovalAction.__members__.values() else ApprovalAction.ESCALATE
                if action == ApprovalAction.APPROVE:
                    self.temp_rules.record_approval(temp.id)
                logger.info("Temp rule '%s' matched: %s %s (window=%s)", temp.id, temp.action, temp.category, window)
                return action, temp.id, "temp_rule_matched"

        # Fall through to static rules
        for rule in self.rules:
            rule_id = rule.get("id", "unnamed")
            rule_category = rule.get("category", "")

            if not self._category_matches(rule_category, request.category):
                continue

            if not self._conditions_match(rule, request):
                continue

            # Rule matches — check limits
            action_str = rule.get("action", "escalate")
            action = ApprovalAction(action_str) if action_str in ApprovalAction.__members__.values() else ApprovalAction.ESCALATE

            if action == ApprovalAction.APPROVE:
                scope = self._scope_for(request)
                limit_exceeded, limit_reason = self._check_limits(rule, scope)
                if limit_exceeded:
                    logger.info("Rule '%s' matched but limit exceeded: %s", rule_id, limit_reason)
                    return ApprovalAction.ESCALATE, rule_id, f"limit_exceeded:{limit_reason}"

                self._increment_counters(rule_id, scope)

            logger.debug("Rule '%s' matched: category=%s action=%s", rule_id, rule_category, action_str)
            return action, rule_id, "rule_matched"

        logger.debug("No rule matched for category=%s action='%s'", request.category.value, request.action)
        return ApprovalAction.ESCALATE, None, "no_matching_rule"

    def _category_matches(self, rule_category: str, request_category: ApprovalCategory) -> bool:
        """Check if a rule's category matches the request's category.

        Args:
            rule_category: Category string from rule config.
            request_category: The request's ApprovalCategory.

        Returns:
            True if they match, or if rule_category is '*' (wildcard).
        """
        if rule_category == "*":
            return True
        return rule_category == request_category.value

    @staticmethod
    def _path_matches(path: str, pattern: str) -> bool:
        """Match a path against a glob pattern, handling **/ prefix.

        fnmatch doesn't treat ** as a recursive glob. This helper also tries
        matching against the pattern with **/ stripped so bare filenames work.

        Args:
            path: File path to test.
            pattern: Glob pattern (may start with **/).

        Returns:
            True if the path matches the pattern.
        """
        if fnmatch.fnmatch(path, pattern):
            return True
        if pattern.startswith("**/"):
            return fnmatch.fnmatch(path, pattern[3:])
        return False

    def _conditions_match(self, rule: dict, request: ApprovalRequest) -> bool:
        """Check if a rule's conditions match the request details.

        Args:
            rule: The rule dict.
            request: The approval request.

        Returns:
            True if all conditions are satisfied (or no conditions defined).
        """
        conditions = rule.get("conditions")
        if not conditions:
            return True

        # Path pattern matching (for file operations)
        path = request.details.get("path", "")
        if path:
            path_patterns = conditions.get("path_patterns")
            if path_patterns and not any(self._path_matches(path, p) for p in path_patterns):
                return False

            exclude_patterns = conditions.get("exclude_patterns")
            if exclude_patterns and any(self._path_matches(path, p) for p in exclude_patterns):
                return False

        # Command pattern matching
        command = request.details.get("command", request.action)
        command_patterns = conditions.get("command_patterns")
        if command_patterns and command:
            if not any(fnmatch.fnmatch(command, p) for p in command_patterns):
                return False

        # Tool name matching
        tool_name = request.details.get("tool_name", "")
        tool_names = conditions.get("tool_names")
        if tool_names and tool_name:
            if tool_name not in tool_names:
                return False

        return True

    def _check_limits(self, rule: dict, scope: str) -> tuple[bool, str]:
        """Check if a rule's limits have been exceeded within a scope.

        Args:
            rule: The rule dict containing limits.
            scope: The session/window scope for the counters.

        Returns:
            Tuple of (exceeded: bool, reason: str).
        """
        limits = rule.get("limits")
        if not limits:
            return False, ""

        key = (scope, rule.get("id", "unnamed"))

        # Max per session
        max_session = limits.get("max_per_session")
        if max_session is not None:
            current = self._session_counts[key]
            if current >= max_session:
                return True, f"max_per_session ({current}/{max_session})"

        # Max per minute (rolling window)
        max_minute = limits.get("max_per_minute")
        if max_minute is not None:
            now = time.time()
            timestamps = self._minute_timestamps[key]
            # Clean old timestamps
            timestamps[:] = [t for t in timestamps if now - t < 60.0]
            if len(timestamps) >= max_minute:
                return True, f"max_per_minute ({len(timestamps)}/{max_minute})"

        # Max consecutive
        max_consecutive = limits.get("max_consecutive")
        if max_consecutive is not None:
            if self._last_rule_id.get(scope) == key[1]:
                consecutive = self._consecutive_counts[key]
                if consecutive >= max_consecutive:
                    return True, f"max_consecutive ({consecutive}/{max_consecutive})"

        return False, ""

    def _increment_counters(self, rule_id: str, scope: str) -> None:
        """Increment limit counters after an approval.

        Args:
            rule_id: The ID of the rule that was triggered.
            scope: The session/window scope for the counters.
        """
        key = (scope, rule_id)
        self._session_counts[key] += 1
        self._minute_timestamps[key].append(time.time())

        if self._last_rule_id.get(scope) == rule_id:
            self._consecutive_counts[key] += 1
        else:
            self._consecutive_counts[key] = 1
            self._last_rule_id[scope] = rule_id

    def reset_rule_limit(self, rule_id: str) -> None:
        """Reset limit counters for a specific rule across all scopes.

        Args:
            rule_id: The ID of the rule whose limits should be reset.
        """
        prev = sum(c for (_, rid), c in self._session_counts.items() if rid == rule_id)
        for key in [k for k in self._session_counts if k[1] == rule_id]:
            del self._session_counts[key]
        for key in [k for k in self._minute_timestamps if k[1] == rule_id]:
            del self._minute_timestamps[key]
        for key in [k for k in self._consecutive_counts if k[1] == rule_id]:
            del self._consecutive_counts[key]
        for scope, last in list(self._last_rule_id.items()):
            if last == rule_id:
                self._last_rule_id[scope] = None
        logger.info("Rule '%s' limits reset (was %d)", rule_id, prev)

    def reset_limits(self) -> None:
        """Reset all limit counters across all scopes."""
        self._session_counts.clear()
        self._minute_timestamps.clear()
        self._consecutive_counts.clear()
        self._last_rule_id.clear()
        logger.info("All rule limits reset")

    def get_limit_status(self) -> dict[str, dict]:
        """Return current limit counters for all rules.

        Counts are summed across scopes; a per-scope breakdown is included
        under 'scopes' when any scope has activity.

        Returns:
            Dict mapping rule_id to their current counter values.
        """
        status = {}
        for rule in self.rules:
            rule_id = rule.get("id", "unnamed")
            limits = rule.get("limits", {})
            if not limits:
                continue
            scopes = {
                scope: count
                for (scope, rid), count in self._session_counts.items()
                if rid == rule_id
            }
            minute_count = sum(
                len(ts) for (_, rid), ts in self._minute_timestamps.items()
                if rid == rule_id
            )
            consecutive = max(
                (c for (_, rid), c in self._consecutive_counts.items() if rid == rule_id),
                default=0,
            )
            status[rule_id] = {
                "session_count": sum(scopes.values()),
                "minute_count": minute_count,
                "consecutive_count": consecutive,
                "limits": limits,
                "scopes": scopes,
            }
        return status

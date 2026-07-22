"""MCP tool: kaptn_defaults_set — modify AutoPilot config with persistence.

Changes are saved to kaptn.config.json on disk. The bridge subprocess
reads from this config on startup. To apply changes to a running bridge,
use kaptn_stop(disconnect=true) then kaptn_connect.
"""

import logging

from bridge.mcp import _state

logger = logging.getLogger(__name__)

VALID_ACTIONS = {"approve", "deny", "escalate"}
VALID_CATEGORIES = {
    "file_read", "file_write", "file_delete",
    "command_safe", "command_unsafe",
    "search", "tool_call", "unknown", "*",
}


@_state.mcp.tool()
def kaptn_defaults_set(
    rule_id: str | None = None,
    action: str | None = None,
    max_per_session: int | None = None,
    max_per_minute: int | None = None,
    max_consecutive: int | None = None,
    command_patterns: list[str] | None = None,
    approval_delay_seconds: float | None = None,
    default_watch_minutes: int | None = None,
    reset_on_manual_approve: bool | None = None,
    loop_same_action_threshold: int | None = None,
) -> dict:
    """Modify AutoPilot defaults and persist to config file.

    Changes are saved to kaptn.config.json. Restart the bridge
    (kaptn_stop disconnect=true, then kaptn_connect) to apply.

    To modify a rule, provide rule_id plus the fields to change.
    To modify global settings, omit rule_id and set the relevant fields.

    Args:
        rule_id: Rule to modify (e.g. "allow-unsafe-commands"). Required for rule changes.
        action: New action for the rule: "approve", "deny", or "escalate".
        max_per_session: Set max approvals per session (0 to remove limit).
        max_per_minute: Set max approvals per minute (0 to remove limit).
        max_consecutive: Set max consecutive approvals (0 to remove limit).
        command_patterns: Command patterns to always approve (e.g. ["echo *", "sleep *"]).
            Applied as conditions.command_patterns on the rule.
        approval_delay_seconds: Seconds to wait before auto-approving (sets poll interval).
        default_watch_minutes: Default duration for kaptn_watch when minutes not specified (1-480).
        reset_on_manual_approve: Whether manual user clicks reset rule limits.
        loop_same_action_threshold: How many identical actions before loop detection triggers.
    """
    if _state._config_manager is None:
        return {"error": "Config manager not initialized"}

    cfg = _state._config_manager.load()
    autopilot = cfg.get("autopilot", {})
    changes = []

    # --- Global settings ---
    if approval_delay_seconds is not None:
        if approval_delay_seconds < 0.5:
            return {"error": "approval_delay_seconds must be >= 0.5"}
        cfg.setdefault("poll_intervals", {})["approvals"] = approval_delay_seconds
        changes.append(f"poll_intervals.approvals = {approval_delay_seconds}s")

    if default_watch_minutes is not None:
        if default_watch_minutes < 1 or default_watch_minutes > 480:
            return {"error": "default_watch_minutes must be between 1 and 480"}
        autopilot["default_watch_minutes"] = default_watch_minutes
        changes.append(f"default_watch_minutes = {default_watch_minutes}")

    if reset_on_manual_approve is not None:
        autopilot["reset_on_manual_approve"] = reset_on_manual_approve
        changes.append(f"reset_on_manual_approve = {reset_on_manual_approve}")

    if loop_same_action_threshold is not None:
        if loop_same_action_threshold < 2:
            return {"error": "loop_same_action_threshold must be >= 2"}
        loop_cfg = autopilot.setdefault("loop_detection", {})
        loop_cfg["same_action_threshold"] = loop_same_action_threshold
        changes.append(f"loop_detection.same_action_threshold = {loop_same_action_threshold}")

    # --- Rule-specific changes ---
    if rule_id is not None:
        rules = autopilot.get("rules", [])
        rule = next((r for r in rules if r.get("id") == rule_id), None)
        if rule is None:
            return {"error": f"Rule '{rule_id}' not found. Use kaptn_defaults to see available rules."}

        if action is not None:
            if action not in VALID_ACTIONS:
                return {"error": f"Invalid action '{action}'. Must be one of: {', '.join(VALID_ACTIONS)}"}
            rule["action"] = action
            changes.append(f"rule '{rule_id}' action = {action}")

        # Update limits
        if any(x is not None for x in [max_per_session, max_per_minute, max_consecutive]):
            limits = rule.setdefault("limits", {})
            if max_per_session is not None:
                if max_per_session <= 0:
                    limits.pop("max_per_session", None)
                    changes.append(f"rule '{rule_id}' max_per_session removed")
                else:
                    limits["max_per_session"] = max_per_session
                    changes.append(f"rule '{rule_id}' max_per_session = {max_per_session}")
            if max_per_minute is not None:
                if max_per_minute <= 0:
                    limits.pop("max_per_minute", None)
                    changes.append(f"rule '{rule_id}' max_per_minute removed")
                else:
                    limits["max_per_minute"] = max_per_minute
                    changes.append(f"rule '{rule_id}' max_per_minute = {max_per_minute}")
            if max_consecutive is not None:
                if max_consecutive <= 0:
                    limits.pop("max_consecutive", None)
                    changes.append(f"rule '{rule_id}' max_consecutive removed")
                else:
                    limits["max_consecutive"] = max_consecutive
                    changes.append(f"rule '{rule_id}' max_consecutive = {max_consecutive}")
            if not limits:
                rule.pop("limits", None)

        # Update command patterns
        if command_patterns is not None:
            conditions = rule.setdefault("conditions", {})
            if command_patterns:
                conditions["command_patterns"] = command_patterns
                changes.append(f"rule '{rule_id}' command_patterns = {command_patterns}")
            else:
                conditions.pop("command_patterns", None)
                changes.append(f"rule '{rule_id}' command_patterns removed")
            if not conditions:
                rule.pop("conditions", None)

    if not changes:
        return {"error": "No changes specified. Provide at least one setting to modify."}

    # Persist to config file
    saved = _state._config_manager.save(cfg)

    logger.info("Config updated: %s (saved=%s)", "; ".join(changes), saved)
    return {
        "status": "updated",
        "changes": changes,
        "persisted": saved,
        "note": "Restart bridge (kaptn_stop disconnect=true, kaptn_connect) to apply changes.",
    }

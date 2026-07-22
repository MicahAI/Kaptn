"""Build the `kaptn status` report — servers, config, live usage, audit.

Pulls from four sources: the hook server's /status endpoint (live limit
counters), launchctl (agent state), CDP discovery (IDE windows), and the
audit database (decision history).
"""

import json
import logging
import urllib.error
import urllib.request

from bridge import lifecycle
from bridge.audit.audit_logger import AuditLogger
from bridge.cdp.cdp_discovery import CdpDiscovery

logger = logging.getLogger(__name__)


def fetch_live_status(port: int, timeout: float = 3.0) -> dict | None:
    """Fetch live AutoPilot state from the running hook server.

    Args:
        port: The hook server port.
        timeout: HTTP timeout in seconds.

    Returns:
        The /status payload, or None if the server is unreachable.
    """
    try:
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/status", timeout=timeout
        ) as response:
            return json.loads(response.read() or b"{}")
    except (urllib.error.URLError, OSError, TimeoutError, json.JSONDecodeError):
        return None


def audit_summary(audit: AuditLogger, hours: int = 24) -> dict:
    """Summarize audit history: total plus a decision tally for the window.

    Args:
        audit: The audit logger to query.
        hours: Lookback window for the tally.

    Returns:
        Dict with total, window_hours, and per-decision counts.
    """
    tally: dict[str, int] = {}
    for record in audit.get_recent_by_time(minutes=hours * 60):
        decision = record.get("decision", "?")
        tally[decision] = tally.get(decision, 0) + 1
    return {"total": audit.get_count(), "window_hours": hours, "tally": tally}


def build_report(cfg: dict, audit: AuditLogger) -> list[str]:
    """Assemble the full status report as printable lines.

    Args:
        cfg: The loaded Kaptn configuration.
        audit: An open audit logger for history queries.

    Returns:
        List of output lines.
    """
    claude_cfg = cfg.get("claude", {})
    hook_port = claude_cfg.get("hook_port", 3002)
    label = claude_cfg.get("launchd_label", lifecycle.DEFAULT_LAUNCHD_LABEL)
    live = fetch_live_status(hook_port)

    lines = ["Kaptn Status", ""]
    lines += _servers_section(cfg, hook_port, label, live)
    lines += _config_section(cfg)
    lines += _usage_section(live)
    lines += _audit_section(audit_summary(audit))
    return lines


def _servers_section(cfg: dict, hook_port: int, label: str, live: dict | None) -> list[str]:
    """Server health: hook server, launchd agent, CDP."""
    lines = ["── Servers ──"]

    if live is not None:
        state = "ON" if live.get("autopilot_enabled") else "OFF"
        lines.append(
            f"  ✅ Claude hook server: healthy on 127.0.0.1:{hook_port} "
            f"(AutoPilot {state}, {live.get('rules_loaded', '?')} rules)"
        )
    else:
        lines.append(f"  ❌ Claude hook server: not reachable on port {hook_port}")

    if lifecycle.launchd_agent_loaded(label):
        lines.append(f"  ✅ launchd agent: loaded ({label})")
    else:
        lines.append(f"  ⚪ launchd agent: not loaded ({label})")

    cdp_port = cfg.get("cdp_port", 9222)
    discovery = CdpDiscovery(port=cdp_port)
    if discovery.is_available():
        windows = [p.workspace_name or p.title for p in discovery.get_page_targets()]
        lines.append(f"  ✅ CDP: available on port {cdp_port} — {len(windows)} window(s): "
                     + ", ".join(windows))
    else:
        lines.append(f"  ⚪ CDP: no IDE on port {cdp_port} (Claude-only mode)")

    lines.append("")
    return lines


def _config_section(cfg: dict) -> list[str]:
    """AutoPilot rules table from config."""
    autopilot = cfg.get("autopilot", {})
    loop = autopilot.get("loop_detection", {})
    lines = [
        "── AutoPilot config ──",
        f"  enabled: {autopilot.get('enabled', False)}   "
        f"loop detection: {loop.get('enabled', False)} "
        f"(same={loop.get('same_action_threshold')}, "
        f"oscillation={loop.get('oscillation_threshold')})",
    ]
    for rule in autopilot.get("rules", []):
        limits = rule.get("limits", {})
        limit_text = "  ".join(f"{k}={v}" for k, v in limits.items())
        lines.append(
            f"  {rule.get('id', 'unnamed'):<24} {rule.get('category', '?'):<15} "
            f"{rule.get('action', '?'):<9} {limit_text}".rstrip()
        )
    lines.append("")
    return lines


def _usage_section(live: dict | None) -> list[str]:
    """Live limit counters from the running server, per rule and scope."""
    lines = ["── Usage (live) ──"]
    if live is None:
        lines += ["  (server not running — no live counters)", ""]
        return lines

    limit_status = live.get("limit_status", {})
    active = {rid: s for rid, s in limit_status.items() if s.get("session_count")}
    if not active:
        lines.append("  no rule usage recorded yet")
    for rule_id, stat in active.items():
        max_session = stat.get("limits", {}).get("max_per_session")
        cap = f"/{max_session}" if max_session is not None else ""
        scopes = stat.get("scopes", {})
        scope_text = ", ".join(
            f"{_short_scope(scope)}: {count}" for scope, count in sorted(scopes.items())
        )
        lines.append(f"  {rule_id:<24} {stat['session_count']}{cap} used   ({scope_text})")

    paused = live.get("paused_windows", [])
    lines.append(f"  paused windows: {', '.join(paused) if paused else 'none'}")
    lines.append("")
    return lines


def _short_scope(scope: str) -> str:
    """Abbreviate long scope ids (Claude session UUIDs) for display."""
    return scope if len(scope) <= 16 else scope[:8] + "…"


def _audit_section(summary: dict) -> list[str]:
    """Audit DB history summary."""
    tally = summary["tally"]
    tally_text = ", ".join(f"{count} {decision}" for decision, count in sorted(tally.items()))
    return [
        "── Audit ──",
        f"  total decisions: {summary['total']}   "
        f"last {summary['window_hours']}h: {sum(tally.values())}"
        + (f" ({tally_text})" if tally else ""),
    ]

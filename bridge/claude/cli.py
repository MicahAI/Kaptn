"""CLI commands for the Claude Code adapter — `kaptn claude ...`."""

import json
import logging
import time
import urllib.error
import urllib.request

import click

from bridge.claude import hook_guard
from bridge.claude.claude_setup import (
    default_settings_path,
    install_hook,
    uninstall_hook,
)
from bridge.claude.hook_guard import HookGuardError
from bridge.claude.hook_server import DEFAULT_HOOK_PORT
from bridge.config.config_manager import ConfigManager
from bridge.logging_config import setup_logging

logger = logging.getLogger(__name__)


@click.group("claude")
def claude_group():
    """Claude Code adapter — hook-based AutoPilot (no CDP needed)."""


def _configured_port(config: str) -> int:
    """Read the hook port from a Kaptn config file."""
    cfg = ConfigManager(config).load()
    return cfg.get("claude", {}).get("hook_port", DEFAULT_HOOK_PORT)


def _configured_answer_budget(config: str) -> float | None:
    """Read the hook client's answer budget from a Kaptn config file."""
    cfg = ConfigManager(config).load()
    return hook_guard.resolve_answer_budget(cfg.get("claude", {}))


def _echo_findings(findings: list) -> None:
    """Print hook-guard findings with severity markers."""
    for finding in findings:
        click.echo(f"{'❌' if finding.fatal else '⚠️ '} {finding}")


@claude_group.command("serve")
@click.option("--config", "-c", default="kaptn.config.json", help="Config file path.")
@click.option("--log-level", "-l", default="INFO", help="Log level.")
def serve(config: str, log_level: str):
    """Run the Kaptn hook server standalone (Claude Code only, no CDP)."""
    setup_logging(level=log_level)
    from bridge.main import KaptnBridge  # deferred — avoids circular import

    cfg = ConfigManager(config).load()
    cfg.setdefault("claude", {})["enabled"] = True
    bridge = KaptnBridge(cfg)

    if not bridge.hook_guard_self_check():
        click.echo("❌ Refusing to serve: Kaptn's own PreToolUse hook cannot gate as "
                   "configured (see the errors above). Run 'kaptn claude check' for "
                   "detail, then 'kaptn claude install' to rewrite a valid entry.")
        raise SystemExit(1)

    bridge.hook_server.start()
    click.echo(f"✅ Kaptn Claude hook server listening on 127.0.0.1:{bridge.hook_server.port}")
    click.echo(f"   AutoPilot: {'ON' if bridge.autopilot.enabled else 'OFF'}. Press Ctrl+C to stop.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        bridge.hook_server.stop()
        bridge.audit.close()


@claude_group.command("install")
@click.option("--config", "-c", default="kaptn.config.json", help="Config file path.")
@click.option("--project", "-p", default=None,
              help="Install into PROJECT/.claude/settings.json instead of user settings.")
@click.option("--settings", "settings_file", default=None,
              help="Explicit settings.json path (overrides --project).")
@click.option("--port", default=None, type=int,
              help="Hook server port (default: claude.hook_port from config).")
@click.option("--hook-timeout", default=None, type=int,
              help="Hook timeout in seconds (default: derived from the answer budget).")
@click.option("--answer-budget", default=None, type=float,
              help="Longest answer the hook client may take, in seconds "
                   "(default: claude.answer_budget_seconds from config).")
@click.option("--hold-until-answered", is_flag=True,
              help="Unbounded hold (ADR-0012): register an effectively unbounded "
                   "timeout so a legitimate hold is never killed.")
def install(config: str, project: str | None, settings_file: str | None,
            port: int | None, hook_timeout: int | None,
            answer_budget: float | None, hold_until_answered: bool):
    """Register the Kaptn PreToolUse hook in Claude Code settings."""
    from pathlib import Path

    setup_logging(level="WARNING")
    path = Path(settings_file) if settings_file else default_settings_path(project)
    resolved_port = port if port is not None else _configured_port(config)

    if hold_until_answered:
        budget = None
    elif answer_budget is not None:
        budget = answer_budget
    else:
        budget = _configured_answer_budget(config)
    timeout = hook_timeout if hook_timeout is not None else hook_guard.recommended_timeout(budget)

    try:
        changed = install_hook(path, resolved_port, timeout=timeout, answer_budget=budget)
    except HookGuardError as e:
        click.echo(f"❌ Refusing to register a hook that cannot gate:\n   {e}")
        raise SystemExit(1) from e
    except ValueError as e:
        click.echo(f"❌ {e}")
        raise SystemExit(1) from e

    if changed:
        click.echo(f"✅ Kaptn hook installed in {path} (port {resolved_port})")
    else:
        click.echo(f"✓ Kaptn hook already installed in {path} (port {resolved_port})")
    click.echo(f"   Timeout {timeout}s for an answer budget of "
               f"{hook_guard.describe_budget(budget)} — the hook must never be killed "
               "mid-answer (a killed hook abstains, and abstaining fails open).")
    click.echo("   Takes effect in new Claude Code sessions.")
    click.echo("   Run 'kaptn claude serve' (or 'kaptn start') so decisions are live —")
    click.echo("   when the bridge is down, the hook fails open to normal prompts.")


@claude_group.command("uninstall")
@click.option("--project", "-p", default=None,
              help="Remove from PROJECT/.claude/settings.json instead of user settings.")
@click.option("--settings", "settings_file", default=None,
              help="Explicit settings.json path (overrides --project).")
def uninstall(project: str | None, settings_file: str | None):
    """Remove the Kaptn PreToolUse hook from Claude Code settings."""
    from pathlib import Path

    setup_logging(level="WARNING")
    path = Path(settings_file) if settings_file else default_settings_path(project)

    try:
        removed = uninstall_hook(path)
    except ValueError as e:
        click.echo(f"❌ {e}")
        raise SystemExit(1) from e

    if removed:
        click.echo(f"✅ Kaptn hook removed from {path}")
    else:
        click.echo(f"✓ No Kaptn hook found in {path}")


@claude_group.command("check")
@click.option("--config", "-c", default="kaptn.config.json", help="Config file path.")
@click.option("--project", "-p", default=None,
              help="Project directory whose .claude settings are checked "
                   "(default: current directory).")
def check(config: str, project: str | None):
    """Audit every effective PreToolUse hook for silent-ungating configurations.

    Reads all the settings sources Claude Code merges and reports any
    PreToolUse hook — Kaptn's or third-party — that is async (its permission
    vote is forfeited) or under-margined (it can be killed before it answers,
    and a killed hook abstains, which fails open).
    """
    setup_logging(level="WARNING")
    budget = _configured_answer_budget(config)
    sources = hook_guard.effective_settings_sources(project)
    findings = hook_guard.check_effective_settings(project, budget, sources=sources)

    click.echo(f"Checked {len(sources)} settings source(s) against an answer budget of "
               f"{hook_guard.describe_budget(budget)} "
               f"(requires timeout ≥ {hook_guard.required_timeout(budget):g}s):")
    for source in sources:
        click.echo(f"   • {source}")

    if not findings:
        click.echo("✅ No async or under-margined PreToolUse hooks found.")
        return

    _echo_findings(findings)
    if any(f.fatal for f in findings):
        click.echo("\nKaptn's own gating hook cannot enforce anything as configured. "
                   "Re-run 'kaptn claude install' to rewrite a valid entry.")
        raise SystemExit(1)
    click.echo("\nWarnings only — Kaptn's own gating hook is sound.")


@claude_group.command("status")
@click.option("--config", "-c", default="kaptn.config.json", help="Config file path.")
@click.option("--port", default=None, type=int, help="Hook server port override.")
def status(config: str, port: int | None):
    """Check whether the Kaptn hook server is reachable."""
    setup_logging(level="WARNING")
    resolved_port = port if port is not None else _configured_port(config)
    url = f"http://127.0.0.1:{resolved_port}/health"

    try:
        with urllib.request.urlopen(url, timeout=3) as response:
            payload = json.loads(response.read() or b"{}")
    except (urllib.error.URLError, OSError, TimeoutError, json.JSONDecodeError):
        click.echo(f"❌ Hook server not reachable on port {resolved_port}. "
                   "Start it with 'kaptn claude serve' or 'kaptn start'.")
        raise SystemExit(1)

    click.echo(f"✅ Hook server healthy on port {resolved_port}: {payload.get('status', '?')}")

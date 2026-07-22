"""CLI commands for the Claude Code adapter — `kaptn claude ...`."""

import json
import logging
import time
import urllib.error
import urllib.request

import click

from bridge.claude.claude_setup import (
    DEFAULT_HOOK_TIMEOUT,
    default_settings_path,
    install_hook,
    uninstall_hook,
)
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
@click.option("--hook-timeout", default=DEFAULT_HOOK_TIMEOUT, type=int,
              help="Hook timeout in seconds.")
def install(config: str, project: str | None, settings_file: str | None,
            port: int | None, hook_timeout: int):
    """Register the Kaptn PreToolUse hook in Claude Code settings."""
    from pathlib import Path

    setup_logging(level="WARNING")
    path = Path(settings_file) if settings_file else default_settings_path(project)
    resolved_port = port if port is not None else _configured_port(config)

    try:
        changed = install_hook(path, resolved_port, timeout=hook_timeout)
    except ValueError as e:
        click.echo(f"❌ {e}")
        raise SystemExit(1) from e

    if changed:
        click.echo(f"✅ Kaptn hook installed in {path} (port {resolved_port})")
    else:
        click.echo(f"✓ Kaptn hook already installed in {path} (port {resolved_port})")
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

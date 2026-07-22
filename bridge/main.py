"""Kaptn CLI entry point — thin orchestrator that composes bridge components."""

import asyncio
import json
import logging
import signal
import sys
import uuid
from datetime import datetime

import click

from bridge.audit.audit_logger import AuditLogger
from bridge.autopilot.auto_pilot_engine import AutoPilotEngine
from bridge.autopilot.auto_reply_engine import AutoReplyEngine
from bridge.autopilot.auto_reply_rule import AutoReplyRule
from bridge.autopilot.escalation_handler import EscalationHandler
from bridge.autopilot.loop_detector import LoopDetector
from bridge.autopilot.rule_evaluator import RuleEvaluator
from bridge.cdp.cdp_connection import CdpConnection
from bridge.cdp.cdp_discovery import CdpDiscovery
from bridge.cdp.cdp_evaluator import CdpEvaluator
from bridge import lifecycle
from bridge.claude.claude_adapter import ClaudeAdapter
from bridge.claude.cli import claude_group
from bridge.claude.hook_server import ClaudeHookServer
from bridge.config.config_manager import ConfigManager
from bridge.drivers.windsurf_driver import WindsurfDriver
from bridge.logging_config import setup_logging
from bridge.logging.message_logger import MessageLogger
from bridge.models import ApprovalAction, ApprovalCategory, ApprovalRequest, AuditRecord, DecisionSource

logger = logging.getLogger(__name__)


class KaptnBridge:
    """Main bridge orchestrator — connects all components and runs the polling loop."""

    def __init__(self, config: dict) -> None:
        """Initialize the bridge with configuration.

        Args:
            config: Parsed configuration dict.
        """
        self.config = config
        self.discovery = CdpDiscovery(port=config.get("cdp_port", 9222))
        self.audit = AuditLogger(db_path=config.get("audit_db", "kaptn_audit.db"))
        self.escalation = EscalationHandler()
        self._running = False
        self._connections: dict[str, tuple[CdpConnection, WindsurfDriver]] = {}
        self._msg_state: dict[str, dict] = {}
        self._last_approval: dict[str, str] = {}  # window -> last approval context fingerprint
        self._escalated: dict[str, str] = {}  # window -> rule_id that caused escalation
        self._last_assistant_text: dict[str, str] = {}  # window -> last assistant message text
        self.message_logger = MessageLogger()

        # Build AutoPilot
        autopilot_config = config.get("autopilot", {})
        rules = autopilot_config.get("rules", [])
        loop_config = autopilot_config.get("loop_detection", {})

        self.autopilot = AutoPilotEngine(
            rule_evaluator=RuleEvaluator(rules),
            loop_detector=LoopDetector(
                same_action_threshold=loop_config.get("same_action_threshold", 3),
                oscillation_threshold=loop_config.get("oscillation_threshold", 3),
                history_size=loop_config.get("history_size", 20),
            ),
            enabled=autopilot_config.get("enabled", True),
        )
        self._reset_on_manual = autopilot_config.get("reset_on_manual_approve", True)

        # Build Auto-Reply engine
        reply_rule_dicts = autopilot_config.get("auto_reply_rules")
        reply_rules = (
            [AutoReplyRule.from_dict(r) for r in reply_rule_dicts]
            if reply_rule_dicts is not None
            else None  # None → use defaults
        )
        self.auto_reply = AutoReplyEngine(
            rules=reply_rules,
            cooldown_seconds=autopilot_config.get("auto_reply_cooldown_seconds", 10.0),
            max_consecutive=autopilot_config.get("auto_reply_max_consecutive", 5),
        )

        # Claude Code adapter — push-based approval source alongside CDP
        self.hook_server: ClaudeHookServer | None = None
        claude_config = config.get("claude", {})
        if claude_config.get("enabled", False):
            adapter = ClaudeAdapter(self.autopilot, self.audit, self.escalation)
            self.hook_server = ClaudeHookServer(
                adapter, port=claude_config.get("hook_port", 3002)
            )

    async def start(self) -> None:
        """Start the bridge — hook server, CDP connections, and the poll loop."""
        logger.info("Kaptn Bridge starting...")

        claude_active = self._start_hook_server()
        cdp_ok = await self._connect_cdp()
        if not cdp_ok and not claude_active:
            return

        # Seed in-memory state from recent audit records
        self._seed_state_from_audit()

        self._running = True
        logger.info("Kaptn Bridge running. AutoPilot: %s. Press Ctrl+C to stop.",
                     "ON" if self.autopilot.enabled else "OFF")

        await self._poll_loop()

    def _start_hook_server(self) -> bool:
        """Start the Claude hook server if configured.

        Returns:
            True if the hook server is running.
        """
        if not self.hook_server:
            return False
        try:
            self.hook_server.start()
        except OSError:
            logger.exception(
                "Could not start Claude hook server on port %d",
                self.hook_server.port,
            )
            self.hook_server = None
            return False
        return True

    async def _connect_cdp(self) -> bool:
        """Discover and connect to IDE windows over CDP.

        Returns:
            True if at least one window connected.
        """
        if not self.discovery.is_available():
            logger.warning(
                "CDP not available on port %d. Launch your IDE with: %s",
                self.config.get("cdp_port", 9222),
                "open -a Windsurf --args --remote-debugging-port=9222",
            )
            return False

        version = self.discovery.get_version()
        logger.info("Connected to: %s", version.get("Browser", "unknown"))

        pages = self.discovery.get_page_targets()
        if not pages:
            logger.warning("No IDE windows found. Open a workspace first.")
            return False

        logger.info("Found %d IDE window(s):", len(pages))
        for page in pages:
            logger.info("  - %s", page.workspace_name or page.title)

        # Connect to all page targets
        for page in pages:
            try:
                conn = CdpConnection(page.websocket_url)
                await conn.connect()
                evaluator = CdpEvaluator(conn)
                driver = WindsurfDriver(evaluator)

                # Validate selectors
                validation = await driver.validate_selectors()
                failed = [name for name, ok in validation.items() if not ok]
                if failed:
                    logger.warning("Window '%s': selectors failed: %s", page.workspace_name, failed)
                else:
                    logger.info("Window '%s': all selectors validated", page.workspace_name)

                # Install real-time message observer for messages.log
                observer_ok = await driver.install_message_observer()
                if not observer_ok:
                    logger.warning("Window '%s': message observer not installed", page.workspace_name)

                self._connections[page.workspace_name] = (conn, driver)
            except Exception:
                logger.exception("Failed to connect to window '%s'", page.workspace_name)

        if not self._connections:
            logger.warning("Could not connect to any IDE windows.")
            return False

        return True

    async def _poll_loop(self) -> None:
        """Main polling loop — checks for approvals and new messages across all connected windows."""
        approval_interval = self.config.get("poll_intervals", {}).get("approvals", 1.0)

        while self._running:
            for window_name, (conn, driver) in list(self._connections.items()):
                if not conn.connected:
                    logger.warning("Window '%s' disconnected, removing", window_name)
                    self._connections.pop(window_name, None)
                    self._msg_state.pop(window_name, None)
                    continue

                try:
                    # Check for new messages
                    await self._check_messages(window_name, driver)

                    # Check for approvals
                    approval = await driver.detect_approval()
                    if approval:
                        approval_type = approval.details.get("type", "")
                        tab_id = approval.details.get("tab_id", "")
                        fingerprint = f"{tab_id}|{approval_type}|{approval.action[:30]}"

                        if approval_type == "banner":
                            # Banner = navigation only — click to scroll, don't evaluate
                            if fingerprint != self._last_approval.get(window_name):
                                self._last_approval[window_name] = fingerprint
                                logger.info("[%s] Approval banner detected — clicking to navigate", window_name)
                                await driver.click_approval_banner()
                        elif fingerprint != self._last_approval.get(window_name):
                            # run_skip or generic — actual approval, evaluate through AutoPilot
                            approval.window_name = window_name
                            self._last_approval[window_name] = fingerprint
                            await self._handle_approval(approval, driver)
                    else:
                        # Approval gone — clear fingerprint so next one is processed
                        if self._last_approval.pop(window_name, None):
                            escalated_rule = self._escalated.pop(window_name, None)
                            if escalated_rule:
                                # Kaptn escalated → user handled it manually
                                logger.info("👤 [%s] User clicked approval (was escalated, rule=%s)", window_name, escalated_rule)
                                if self._reset_on_manual:
                                    self.autopilot.rule_evaluator.reset_rule_limit(escalated_rule)
                                    self.autopilot.resume_window(window_name)
                                    self.autopilot.loop_detector.clear()
                                    logger.info("[%s] Reset rule '%s' + resumed + cleared loop history — user says keep going", window_name, escalated_rule)
                            else:
                                logger.info("[%s] Approval dismissed ✓", window_name)
                except Exception:
                    logger.exception("Error polling window '%s'", window_name)

            await asyncio.sleep(approval_interval)

    async def _check_messages(self, window_name: str, driver: WindsurfDriver) -> None:
        """Check for new messages in the Cascade panel and log them.

        Uses two strategies:
        1. MutationObserver drain — real-time capture that bypasses scroll virtualization
        2. DOM extraction fallback — for initial scan and when observer is not installed

        Args:
            window_name: Name of the IDE window.
            driver: The WindsurfDriver for the window.
        """
        # Strategy 1: Drain observer buffer (real-time, reliable for user/assistant)
        observed = await driver.drain_observed_messages()
        for msg in observed:
            if msg.get("type") == "session_change":
                logger.info("🔄 [%s] Conversation changed (observer)", window_name)
                self.message_logger.log_session_marker(window_name)
                continue
            role = msg.get("role", "unknown")
            text = msg.get("text", "")
            ts_ms = msg.get("timestamp", 0)
            ts = datetime.fromtimestamp(ts_ms / 1000) if ts_ms else datetime.now()
            role_emoji = {"user": "👤", "assistant": "🤖", "thinking": "💭"}.get(role, "🔧")
            preview = text[:120].replace("\n", " ").strip()
            if role in ("user", "assistant", "thinking"):
                logger.info("%s [%s] %s: %s", role_emoji, window_name, role.upper(), preview)
            self.message_logger.log_message(window_name, role, text, ts)

            # Track last assistant message for auto-reply detection
            if role == "assistant" and text.strip():
                self._last_assistant_text[window_name] = text
            elif role == "user":
                # User sent a message — reset auto-reply consecutive counter
                self.auto_reply.reset_consecutive(window_name)

        # Strategy 2: DOM extraction — only on first scan per window.
        # After that, the MutationObserver (Strategy 1) handles new messages.
        # Heavy DOM queries (querySelectorAll, child iteration) cause Windsurf
        # to auto-scroll the cascade panel, so we avoid them during polling.
        state = self._msg_state.get(window_name, {"count": 0, "fingerprint": ""})
        if state["count"] > 0:
            # Already did initial scan — skip DOM extraction
            return

        messages = await driver.extract_messages(scroll=True)
        if not messages:
            return
        first_fingerprint = messages[0].text[:80] if messages else ""

        if first_fingerprint != state["fingerprint"]:
            if not observed:  # Only log session change if observer didn't already
                logger.info("🔄 [%s] Conversation changed — re-scanning messages", window_name)
                self.message_logger.log_session_marker(window_name)
            state = {"count": 0, "fingerprint": first_fingerprint}

        if len(messages) <= state["count"]:
            self._msg_state[window_name] = state
            return

        new_messages = messages[state["count"]:]
        state["count"] = len(messages)
        self._msg_state[window_name] = state

        for msg in new_messages:
            role_emoji = {
                "user": "👤", "assistant": "🤖", "tool_call": "🔧",
                "feedback": "📝", "show_more": "📄",
            }.get(msg.role, "❓")
            preview = msg.text[:120].replace("\n", " ").strip()
            logger.info("%s [%s] %s: %s", role_emoji, window_name, msg.role.upper(), preview)

    async def _check_auto_reply(self, window_name: str, driver: WindsurfDriver, has_approval: bool) -> None:
        """Check if the last CASCADE message warrants an auto-reply.

        Only fires when:
        - No approval dialog is visible (AutoPilot handles those)
        - AutoPilot is not paused for this window
        - An active watch session exists (auto-reply respects watch scope)
        - The last assistant message matches an allow-pattern

        Args:
            window_name: Name of the IDE window.
            driver: The WindsurfDriver for the window.
            has_approval: Whether an approval dialog is currently visible.
        """
        if has_approval:
            return

        if window_name in self.autopilot.paused_windows:
            return

        last_text = self._last_assistant_text.get(window_name, "")
        if not last_text:
            return

        reply, rule_id = self.auto_reply.check(window_name, last_text)
        if not reply:
            return

        # Inject the reply into Cascade
        success = await driver.inject_message(reply)
        if success:
            logger.info(
                "💬 [%s] AUTO-REPLY: '%s' (rule=%s)",
                window_name, reply, rule_id,
            )
            record = AuditRecord(
                id=str(uuid.uuid4()),
                timestamp=datetime.now(),
                window_name=window_name,
                tab_id="",
                mode="unknown",
                request=ApprovalRequest(
                    category=ApprovalCategory.AUTO_REPLY,
                    action=reply,
                    window_name=window_name,
                ),
                decision=ApprovalAction.APPROVE,
                source=DecisionSource.AUTOPILOT,
                rule_id=rule_id,
            )
            self.audit.log(record)
        else:
            logger.warning(
                "[%s] Auto-reply injection failed for rule '%s'",
                window_name, rule_id,
            )

    def _seed_state_from_audit(self) -> None:
        """Pre-populate in-memory state from recent audit records.

        Queries the audit DB for records from the last 30 minutes and
        rebuilds the approval fingerprint cache per window. This prevents
        re-processing approvals that were already handled in a previous session.
        """
        records = self.audit.get_recent_by_time(minutes=30)
        if not records:
            logger.debug("No recent audit records to seed state from")
            return

        seeded: dict[str, str] = {}
        for rec in records:
            window = rec.get("window_name", "")
            if window in seeded:
                continue  # Only keep the most recent per window (list is newest-first)

            tab_id = rec.get("tab_id", "")
            action_text = rec.get("action_text", "")
            details_raw = rec.get("details", "{}")
            try:
                details = json.loads(details_raw) if isinstance(details_raw, str) else details_raw
            except (json.JSONDecodeError, TypeError):
                details = {}

            approval_type = details.get("type", "")
            fingerprint = f"{tab_id}|{approval_type}|{action_text[:30]}"

            self._last_approval[window] = fingerprint
            seeded[window] = fingerprint

        if seeded:
            logger.info("Seeded state from audit DB: %d window(s) with recent approvals", len(seeded))
            for window, fp in seeded.items():
                logger.debug("  %s: %s", window, fp[:60])

    async def _handle_approval(self, request, driver: WindsurfDriver) -> None:
        """Process a detected approval request through AutoPilot.

        Args:
            request: The detected ApprovalRequest.
            driver: The WindsurfDriver for the window.
        """
        window = request.window_name or "?"
        action, rule_id, reason = self.autopilot.evaluate(request)

        # Record in audit log
        self.audit.create_record(
            request=request,
            decision=action,
            source=DecisionSource.AUTOPILOT,
            rule_id=rule_id,
            rule_action=action.value,
            limit_status=self.autopilot.rule_evaluator.get_limit_status(),
            loop_detected=(reason == "loop_detected"),
        )

        # Execute the decision
        clicked = False
        if action == ApprovalAction.APPROVE:
            clicked = await driver.click_approve()
        elif action == ApprovalAction.DENY:
            clicked = await driver.click_deny()
        elif action == ApprovalAction.ESCALATE:
            self.escalation.escalate(request, reason, rule_id)
            if rule_id:
                self._escalated[window] = rule_id
            return

        if not clicked:
            logger.warning("[%s] Failed to click %s — button not found", window, action.value)
            return

        # Post-click verification: wait briefly and check if approval is gone
        await asyncio.sleep(0.5)
        still_pending = await driver.detect_approval()
        if still_pending and still_pending.details.get("type") == "run_skip":
            logger.warning("[%s] Approval still pending after click — may not have worked", window)
        else:
            logger.info("[%s] ✅ %s executed successfully (rule=%s)", window, action.value.upper(), rule_id)

    async def stop(self) -> None:
        """Stop the bridge and close all connections."""
        self._running = False
        if self.hook_server:
            self.hook_server.stop()
        for window_name, (conn, _) in self._connections.items():
            await conn.disconnect()
            logger.info("Disconnected from '%s'", window_name)
        self._connections.clear()
        self.audit.close()
        logger.info("Kaptn Bridge stopped.")


@click.group()
def cli():
    """Kaptn — Remote command and control for AI coding assistants."""
    pass


@cli.command()
@click.option("--config", "-c", default="kaptn.config.json", help="Config file path.")
@click.option("--log-level", "-l", default="INFO", help="Log level (DEBUG, INFO, WARNING, ERROR).")
def start(config: str, log_level: str):
    """Start the Kaptn bridge and begin monitoring."""
    setup_logging(level=log_level)

    config_manager = ConfigManager(config)
    cfg = config_manager.load()

    bridge = KaptnBridge(cfg)

    loop = asyncio.new_event_loop()

    def shutdown_handler():
        loop.create_task(bridge.stop())

    loop.add_signal_handler(signal.SIGINT, shutdown_handler)
    loop.add_signal_handler(signal.SIGTERM, shutdown_handler)

    try:
        loop.run_until_complete(bridge.start())
    except KeyboardInterrupt:
        loop.run_until_complete(bridge.stop())
    finally:
        loop.close()


@cli.command("stop")
@click.option("--config", "-c", default="kaptn.config.json", help="Config file path.")
def stop_command(config: str):
    """Stop all running Kaptn servers (launchd agent and manual instances)."""
    setup_logging(level="WARNING")

    cfg = ConfigManager(config).load()
    label = cfg.get("claude", {}).get(
        "launchd_label", lifecycle.DEFAULT_LAUNCHD_LABEL
    )

    report = lifecycle.stop_all(label)

    if report["agent_stopped"]:
        click.echo(f"✅ launchd agent '{label}' stopped")
        click.echo("   (returns at next login — or now via 'launchctl bootstrap "
                   f"gui/$UID ~/Library/LaunchAgents/{label}.plist')")
    if report["stopped"]:
        pids = ", ".join(str(p) for p in report["stopped"])
        click.echo(f"✅ Stopped process(es): {pids}")
    if report["killed"]:
        pids = ", ".join(str(p) for p in report["killed"])
        click.echo(f"⚠️  Force-killed unresponsive process(es): {pids}")
    if not (report["agent_stopped"] or report["stopped"] or report["killed"]):
        click.echo("✓ Nothing was running.")


@cli.command("reset")
@click.option("--config", "-c", default="kaptn.config.json", help="Config file path.")
@click.option("--port", default=None, type=int, help="Hook server port override.")
def reset_command(config: str, port: int | None):
    """Reset AutoPilot limits, loop history, and pauses on the running server."""
    import urllib.error
    import urllib.request

    setup_logging(level="WARNING")

    cfg = ConfigManager(config).load()
    resolved_port = port if port is not None else cfg.get("claude", {}).get("hook_port", 3002)
    request = urllib.request.Request(
        f"http://127.0.0.1:{resolved_port}/reset", data=b"{}", method="POST"
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            json.loads(response.read() or b"{}")
    except (urllib.error.URLError, OSError, TimeoutError, json.JSONDecodeError):
        click.echo(f"❌ Hook server not reachable on port {resolved_port}.")
        click.echo("   (A server restart also resets limits: "
                   "launchctl kickstart -k gui/$UID/com.micahai.kaptn.claude)")
        raise SystemExit(1)

    click.echo("✅ AutoPilot reset — rule limits cleared, loop history cleared, "
               "paused windows resumed.")


@cli.command()
@click.option("--config", "-c", default="kaptn.config.json", help="Config file path.")
def status(config: str):
    """Check if CDP is available and list connected windows."""
    setup_logging(level="WARNING")

    config_manager = ConfigManager(config)
    cfg = config_manager.load()

    discovery = CdpDiscovery(port=cfg.get("cdp_port", 9222))

    if not discovery.is_available():
        click.echo("❌ CDP not available. Is the IDE running with --remote-debugging-port?")
        sys.exit(1)

    version = discovery.get_version()
    click.echo(f"✅ Connected to: {version.get('Browser', 'unknown')}")

    pages = discovery.get_page_targets()
    click.echo(f"\n📁 Windows ({len(pages)}):")
    for page in pages:
        click.echo(f"   - {page.workspace_name or page.title}")


@cli.command("log")
@click.option("--limit", "-n", default=20, help="Number of records to show.")
@click.option("--loops", is_flag=True, help="Show only loop detection events.")
@click.option("--db", default="kaptn_audit.db", help="Audit database path.")
def show_log(limit: int, loops: bool, db: str):
    """Show the audit log."""
    audit = AuditLogger(db_path=db)

    if loops:
        records = audit.get_loops(limit=limit)
        click.echo(f"🔄 Loop events (showing {len(records)}):\n")
    else:
        records = audit.get_recent(limit=limit)
        click.echo(f"📋 Audit log (showing {len(records)} of {audit.get_count()}):\n")

    for record in records:
        decision = record["decision"].upper()
        emoji = {"approved": "✅", "denied": "❌", "escalated": "⏳"}.get(record["decision"], "❓")
        click.echo(
            f"  {emoji} {record['timestamp'][:19]}  "
            f"{decision:>9}  {record['category']:>15}  "
            f"'{record['action_text'][:40]}'  "
            f"(rule={record['rule_id'] or 'none'}, source={record['source']})"
        )

    audit.close()


cli.add_command(claude_group)


@cli.group("mcp")
def mcp_group():
    """Kaptn MCP Server — expose AutoPilot to AI agents."""
    pass


@mcp_group.command("start")
@click.option("--config", "-c", default="kaptn.config.json", help="Config file path.")
@click.option("--log-level", "-l", default="INFO", help="Log level.")
@click.option("--no-connect", is_flag=True, help="Don't auto-connect bridge on startup.")
def mcp_start(config: str, log_level: str, no_connect: bool):
    """Start the Kaptn MCP server (stdio transport).

    The bridge runs as a separate subprocess that connects to the IDE via CDP.
    By default, the bridge auto-connects on startup.
    """
    setup_logging(level=log_level)

    import os
    from bridge.mcp.mcp_server import create_kaptn_mcp_server, mcp as mcp_instance

    config_path = os.path.abspath(config)
    config_manager = ConfigManager(config_path)

    create_kaptn_mcp_server(
        config_path=config_path,
        config_manager=config_manager,
        auto_connect=not no_connect,
    )

    logger.info("Starting Kaptn MCP server (stdio)...")
    mcp_instance.run()


if __name__ == "__main__":
    cli()

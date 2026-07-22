"""Bridge worker subprocess — standalone process that runs the Kaptn bridge.

Spawned by the MCP server's kaptn_connect tool. Discovers CDP targets,
connects to IDE windows, runs the poll loop, and communicates via atomic
JSON files:

    progress.json — bridge → MCP (status, errors, windows)
    commands.json — MCP → bridge (temp rules, config changes)

Usage:
    python -m bridge.mcp._bridge_worker --config kaptn.config.json
"""

import argparse
import asyncio
import logging
import os
import signal
import sys
import time
from pathlib import Path

from bridge.mcp._progress import (
    clear_commands,
    read_commands,
    write_progress,
)

logger = logging.getLogger("kaptn.bridge_worker")


def _write_status(
    *,
    running: bool,
    windows: list[str] | None = None,
    error: str | None = None,
    cdp_port: int = 9222,
    pid: int | None = None,
    retry_at: float | None = None,
) -> None:
    """Write current bridge status to progress file."""
    data = {
        "running": running,
        "pid": pid or os.getpid(),
        "cdp_port": cdp_port,
        "timestamp": time.time(),
    }
    if windows is not None:
        data["windows"] = windows
    if error:
        data["error"] = error
    if retry_at:
        data["retry_at"] = retry_at
    write_progress(data)


async def _run_bridge(config_path: str, reconnect_delay: float = 5.0) -> None:
    """Main bridge loop with graceful reconnect.

    Args:
        config_path: Path to kaptn.config.json.
        reconnect_delay: Seconds to wait before retrying after CDP failure.
    """
    from bridge.autopilot.temp_rule_manager import TempRuleManager
    from bridge.config.config_manager import ConfigManager
    from bridge.main import KaptnBridge

    config_manager = ConfigManager(config_path)
    cfg = config_manager.load()
    cdp_port = cfg.get("cdp_port", 9222)

    # Resolve relative paths against ~/.kaptn/ (CWD is / when launched as MCP subprocess)
    kaptn_home = os.path.join(Path.home(), ".kaptn")
    os.makedirs(kaptn_home, exist_ok=True)

    audit_db = cfg.get("audit_db", "kaptn_audit.db")
    if not os.path.isabs(audit_db):
        cfg["audit_db"] = os.path.join(kaptn_home, audit_db)
        logger.info("Resolved audit_db: %s", cfg["audit_db"])

    bridge: KaptnBridge | None = None
    temp_rules = TempRuleManager()

    while True:
        try:
            # Create bridge and wire up temp rules
            bridge = KaptnBridge(cfg)
            bridge.autopilot.rule_evaluator.temp_rules = temp_rules

            _write_status(running=True, windows=[], cdp_port=cdp_port)
            logger.info("Bridge worker starting (CDP port %d)...", cdp_port)

            # bridge.start() does: CDP discovery → connect → poll loop
            # If CDP not available, it logs and returns (doesn't raise)
            # We need to check if connections were established
            await _start_with_status(bridge, cdp_port, temp_rules)

        except Exception:
            logger.exception("Bridge worker crashed")
            _write_status(
                running=True,
                error="Bridge crashed unexpectedly, retrying...",
                cdp_port=cdp_port,
                retry_at=time.time() + reconnect_delay,
            )

        finally:
            if bridge:
                try:
                    await bridge.stop()
                except Exception:
                    logger.exception("Error during bridge shutdown")

        logger.info("Reconnecting in %.0fs...", reconnect_delay)
        await asyncio.sleep(reconnect_delay)


async def _start_with_status(bridge, cdp_port: int, temp_rules) -> None:
    """Start the bridge with status reporting and command polling.

    Overrides the standard bridge.start() to integrate progress
    reporting and command file monitoring.

    Args:
        bridge: KaptnBridge instance.
        cdp_port: CDP port for status reporting.
        temp_rules: TempRuleManager shared with command processing.
    """
    from bridge.cdp.cdp_connection import CdpConnection
    from bridge.cdp.cdp_evaluator import CdpEvaluator
    from bridge.drivers.windsurf_driver import WindsurfDriver

    # Phase 1: CDP Discovery
    if not bridge.discovery.is_available():
        error_msg = (
            f"CDP not available on port {cdp_port}. "
            f"Launch your IDE with: open -a Windsurf --args --remote-debugging-port={cdp_port}"
        )
        logger.error(error_msg)
        _write_status(running=True, error=error_msg, cdp_port=cdp_port)
        return  # Will trigger reconnect loop

    version = bridge.discovery.get_version()
    logger.info("Connected to: %s", version.get("Browser", "unknown"))

    # Phase 2: Find and connect to windows
    pages = bridge.discovery.get_page_targets()
    if not pages:
        _write_status(
            running=True,
            error="CDP connected but no IDE windows found. Open a workspace first.",
            cdp_port=cdp_port,
        )
        return

    for page in pages:
        try:
            conn = CdpConnection(page.websocket_url)
            await conn.connect()
            evaluator = CdpEvaluator(conn)
            driver = WindsurfDriver(evaluator)

            validation = await driver.validate_selectors()
            failed = [name for name, ok in validation.items() if not ok]
            if failed:
                logger.warning("Window '%s': selectors failed: %s", page.workspace_name, failed)
            else:
                logger.info("Window '%s': all selectors validated", page.workspace_name)

            # Clean up any stale JS from previous Kaptn sessions
            await driver.cleanup_injected_js()

            bridge._connections[page.workspace_name] = (conn, driver)
        except Exception:
            logger.exception("Failed to connect to window '%s'", page.workspace_name)

    if not bridge._connections:
        _write_status(
            running=True,
            error="CDP found windows but could not connect to any.",
            cdp_port=cdp_port,
        )
        return

    # Phase 3: Connected — report success
    window_names = list(bridge._connections.keys())
    _write_status(running=True, windows=window_names, cdp_port=cdp_port)
    logger.info("Bridge running with %d window(s): %s", len(window_names), window_names)

    bridge._seed_state_from_audit()
    bridge._running = True

    # Snapshot existing banners so we don't click stale approvals from previous sessions
    for window_name, (conn, driver) in bridge._connections.items():
        try:
            approval = await driver.detect_approval()
            if approval and approval.details.get("type") == "banner":
                tab_id = approval.details.get("tab_id", "")
                fingerprint = f"{tab_id}|banner|{approval.action[:30]}"
                bridge._last_approval[window_name] = fingerprint
                logger.info("[%s] Snapshotted existing banner on connect — will not click", window_name)
        except Exception:
            logger.debug("Error snapshotting banners for '%s'", window_name)

    # Phase 4: Poll loop with command file monitoring
    approval_interval = bridge.config.get("poll_intervals", {}).get("approvals", 1.0)
    command_check_counter = 0
    _observer_installed: set[str] = set()  # Track which windows have observers

    while bridge._running:
        # Normal bridge polling
        for window_name, (conn, driver) in list(bridge._connections.items()):
            if not conn.connected:
                logger.warning("Window '%s' disconnected, removing", window_name)
                bridge._connections.pop(window_name, None)
                bridge._msg_state.pop(window_name, None)
                _observer_installed.discard(window_name)
                continue

            # Only do heavy DOM operations on actively watched windows.
            # CDP Runtime.evaluate on cascade panel causes Windsurf to scroll.
            is_watched = bool(temp_rules.get_active_rules(window=window_name))

            try:
                if is_watched:
                    # Install observer on first watched poll
                    if window_name not in _observer_installed:
                        if await driver.install_message_observer():
                            _observer_installed.add(window_name)
                        else:
                            logger.warning("[%s] Failed to install observer", window_name)
                    await bridge._check_messages(window_name, driver)

                    approval = await driver.detect_approval()
                    has_approval = bool(approval)
                    if approval:
                        approval_type = approval.details.get("type", "")
                        tab_id = approval.details.get("tab_id", "")
                        fingerprint = f"{tab_id}|{approval_type}|{approval.action[:30]}"

                        if approval_type == "banner":
                            if fingerprint != bridge._last_approval.get(window_name):
                                bridge._last_approval[window_name] = fingerprint
                                logger.info("[%s] Approval banner — clicking to navigate", window_name)
                                await driver.click_approval_banner()
                        elif fingerprint != bridge._last_approval.get(window_name):
                            approval.window_name = window_name
                            bridge._last_approval[window_name] = fingerprint
                            await bridge._handle_approval(approval, driver)
                    else:
                        if bridge._last_approval.pop(window_name, None):
                            escalated_rule = bridge._escalated.pop(window_name, None)
                            if escalated_rule:
                                logger.info(
                                    "👤 [%s] User clicked approval (was escalated, rule=%s)",
                                    window_name, escalated_rule,
                                )
                                if bridge._reset_on_manual:
                                    bridge.autopilot.rule_evaluator.reset_rule_limit(escalated_rule)
                                    bridge.autopilot.resume_window(window_name)
                                    bridge.autopilot.loop_detector.clear()
                            else:
                                logger.info("[%s] Approval dismissed ✓", window_name)

                    # Check for conversational stalls (Auto-Answer)
                    await bridge._check_auto_reply(window_name, driver, has_approval)

                    # Send heartbeat to keep injected JS alive
                    await driver.send_heartbeat()
            except Exception:
                logger.exception("Error polling window '%s'", window_name)

        # Check for commands from MCP server (every 3 poll cycles to reduce IO)
        command_check_counter += 1
        if command_check_counter >= 3:
            command_check_counter = 0
            _process_commands(temp_rules, bridge)

        # Update window list in progress
        if not bridge._connections:
            _write_status(
                running=True,
                error="All windows disconnected.",
                cdp_port=bridge.config.get("cdp_port", 9222),
            )
            return  # Will trigger reconnect loop

        await asyncio.sleep(approval_interval)


def _process_commands(temp_rules, bridge) -> None:
    """Read and execute pending commands from the MCP server.

    Args:
        temp_rules: TempRuleManager to apply temp rule commands to.
        bridge: KaptnBridge instance for config changes.
    """
    commands = read_commands()
    if not commands:
        return

    # Process temp rule commands
    for rule_cmd in commands.get("temp_rules", []):
        try:
            action = rule_cmd.get("action")
            if action == "create_watch":
                temp_rules.create_watch(
                    window=rule_cmd.get("window", ""),
                    minutes=rule_cmd.get("minutes", 10),
                    categories=rule_cmd.get("categories"),
                    source="mcp",
                )
                logger.info("Applied watch command: window=%s minutes=%d",
                           rule_cmd.get("window"), rule_cmd.get("minutes"))
            elif action == "create_rule":
                temp_rules.create_rule(
                    category=rule_cmd.get("category", ""),
                    minutes=rule_cmd.get("minutes", 10),
                    window=rule_cmd.get("window"),
                    max_count=rule_cmd.get("max_count"),
                )
                logger.info("Applied temp rule: category=%s", rule_cmd.get("category"))
            elif action == "stop_rule":
                rule_id = rule_cmd.get("rule_id")
                if rule_id:
                    temp_rules.remove_rule(rule_id)
                    logger.info("Removed temp rule: %s", rule_id)
            elif action == "stop_window":
                window = rule_cmd.get("window", "")
                removed = temp_rules.remove_by_window(window)
                logger.info("Removed %d rules for window '%s'", removed, window)
            elif action == "stop_all":
                temp_rules.clear_all()
                logger.info("Cleared all temp rules")
            elif action == "resume_window":
                window = rule_cmd.get("window", "")
                bridge.autopilot.resume_window(window)
                logger.info("Resumed window '%s'", window)
            elif action == "resume_all":
                bridge.autopilot.paused_windows.clear()
                logger.info("Resumed all windows")
        except Exception:
            logger.exception("Failed to process command: %s", rule_cmd)

    # Clear commands after processing
    clear_commands()

    # Update progress with current temp rules
    active_rules = temp_rules.get_active_rules()
    progress = {
        "running": True,
        "pid": os.getpid(),
        "cdp_port": bridge.config.get("cdp_port", 9222),
        "timestamp": time.time(),
        "windows": list(bridge._connections.keys()),
        "temp_rules": [r.to_dict() for r in active_rules],
    }
    write_progress(progress)


def main() -> None:
    """Entry point for the bridge worker subprocess."""
    parser = argparse.ArgumentParser(description="Kaptn bridge worker subprocess")
    parser.add_argument("--config", default="kaptn.config.json", help="Config file path")
    parser.add_argument("--log-level", default="INFO", help="Log level")
    args = parser.parse_args()

    # Set up logging to stderr (redirected to ~/.kaptn/logs/bridge_worker.log by tool_connect)
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)-8s [%(name)s] %(message)s",
        stream=sys.stderr,
    )

    # === Startup instrumentation ===
    logger.info("=" * 60)
    logger.info("Bridge worker subprocess starting")
    logger.info("  PID: %d", os.getpid())
    logger.info("  Python: %s", sys.executable)
    logger.info("  Python version: %s", sys.version)
    logger.info("  Config: %s (exists=%s)", args.config, os.path.exists(args.config))
    logger.info("  CWD: %s", os.getcwd())
    logger.info("  PYTHONPATH: %s", os.environ.get("PYTHONPATH", "(not set)"))
    logger.info("  sys.path: %s", sys.path[:5])
    logger.info("  Log level: %s", args.log_level)
    logger.info("=" * 60)

    # Verify config file exists early
    if not os.path.exists(args.config):
        logger.error("Config file not found: %s", args.config)
        _write_status(running=False, error=f"Config file not found: {args.config}")
        sys.exit(1)

    # Test imports that commonly fail
    try:
        logger.info("Testing imports...")
        from bridge.config.config_manager import ConfigManager  # noqa: F401
        from bridge.main import KaptnBridge  # noqa: F401
        from bridge.cdp.cdp_discovery import CdpDiscovery  # noqa: F401
        logger.info("All imports OK")
    except Exception:
        logger.exception("Import failed — check PYTHONPATH and dependencies")
        _write_status(running=False, error="Import error — see ~/.kaptn/logs/bridge_worker.log")
        sys.exit(1)

    _write_status(running=True, cdp_port=9222)

    loop = asyncio.new_event_loop()

    def shutdown(signum, frame):
        logger.info("Bridge worker received signal %d, shutting down...", signum)
        _write_status(running=False)
        loop.stop()

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    try:
        loop.run_until_complete(_run_bridge(args.config))
    except KeyboardInterrupt:
        logger.info("KeyboardInterrupt received")
    except Exception:
        logger.exception("Bridge worker crashed with unhandled exception")
        _write_status(running=False, error="Unhandled exception — see ~/.kaptn/logs/bridge_worker.log")
    finally:
        _write_status(running=False)
        clear_commands()
        loop.close()
        logger.info("Bridge worker stopped (PID %d)", os.getpid())


if __name__ == "__main__":
    main()

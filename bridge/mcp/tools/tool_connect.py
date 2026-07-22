"""MCP tool: kaptn_connect — start the bridge subprocess to connect to the IDE."""

import logging
import os
import subprocess
import sys
import time

from bridge.mcp import _progress, _state
from bridge.setup.windsurf_setup import check_cdp_configured, configure_cdp

logger = logging.getLogger(__name__)


def _find_project_root() -> str | None:
    """Walk up from this file to find the project root (directory containing pyproject.toml).

    Returns:
        Absolute path to project root, or None if not found.
    """
    current = os.path.abspath(__file__)
    # Walk up at most 10 levels to avoid infinite loop
    for _ in range(10):
        current = os.path.dirname(current)
        if not current or current == os.path.dirname(current):
            break  # reached filesystem root
        if os.path.isfile(os.path.join(current, "pyproject.toml")):
            return current
    return None


@_state.mcp.tool()
def kaptn_connect(
    config: str | None = None,
    log_level: str = "INFO",
) -> dict:
    """Connect Kaptn to your IDE via CDP (Chrome DevTools Protocol).

    Spawns a background bridge process that discovers and connects to
    IDE windows. The bridge runs independently and survives MCP restarts.

    Check connection status with kaptn_status.

    Args:
        config: Path to kaptn.config.json. Uses default if not provided.
        log_level: Log level for the bridge worker (DEBUG, INFO, WARNING, ERROR).
    """
    # Check if already running
    if _progress.is_bridge_running():
        progress = _progress.read_progress()
        windows = progress.get("windows", [])
        error = progress.get("error")
        result = {
            "status": "already_running",
            "pid": progress.get("pid"),
            "windows": windows,
        }
        if error:
            result["error"] = error
        return result

    # Resolve config path
    config_path = config or _state._config_path or "kaptn.config.json"
    config_path = os.path.abspath(config_path)

    if not os.path.exists(config_path):
        return {"error": f"Config file not found: {config_path}"}

    # Build subprocess command
    worker_module = "bridge.mcp._bridge_worker"
    cmd = [
        sys.executable, "-m", worker_module,
        "--config", config_path,
        "--log-level", log_level,
    ]

    # Ensure PYTHONPATH includes the project root so worker can import bridge.*
    env = os.environ.copy()
    project_root = _find_project_root()
    if project_root:
        python_path = env.get("PYTHONPATH", "")
        if project_root not in python_path:
            env["PYTHONPATH"] = f"{project_root}{os.pathsep}{python_path}" if python_path else project_root
    else:
        logger.warning("Could not find project root (no pyproject.toml found). "
                        "Bridge worker may fail to import if package is not installed.")

    # Ensure ~/.kaptn/logs/ exists
    _progress._ensure_dir()

    # Log full startup context for debugging
    logger.info("=== kaptn_connect startup ===")
    logger.info("  python: %s", sys.executable)
    logger.info("  cmd: %s", cmd)
    logger.info("  config: %s (exists=%s)", config_path, os.path.exists(config_path))
    logger.info("  project_root: %s", project_root)
    logger.info("  PYTHONPATH: %s", env.get("PYTHONPATH", ""))
    logger.info("  log_file: %s", _progress.WORKER_LOG_FILE)
    logger.info("  cwd: %s", os.getcwd())

    # Write stderr to ~/.kaptn/logs/bridge_worker.log (not PIPE — unread pipes kill the subprocess)
    try:
        log_file = open(_progress.WORKER_LOG_FILE, "a")
        # Write startup marker so we can always find the start of a run
        log_file.write(f"\n{'='*60}\n")
        log_file.write(f"=== Bridge worker starting at {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n")
        log_file.write(f"  python: {sys.executable}\n")
        log_file.write(f"  cmd: {cmd}\n")
        log_file.write(f"  config: {config_path}\n")
        log_file.write(f"  PYTHONPATH: {env.get('PYTHONPATH', '')}\n")
        log_file.write(f"  cwd: {os.getcwd()}\n")
        log_file.write(f"{'='*60}\n")
        log_file.flush()
    except OSError as e:
        return {"error": f"Cannot create log file {_progress.WORKER_LOG_FILE}: {e}"}

    try:
        proc = subprocess.Popen(
            cmd,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=log_file,
            start_new_session=True,  # survives parent death
        )
    except OSError as e:
        log_file.close()
        return {"error": f"Failed to spawn bridge worker: {e}"}

    # Write initial progress so status tool can see it immediately
    _progress.write_progress({
        "running": True,
        "pid": proc.pid,
        "timestamp": time.time(),
        "windows": [],
    })

    logger.info("Bridge worker spawned (PID %d), log: %s", proc.pid, _progress.WORKER_LOG_FILE)

    # Wait briefly then check if CDP is reachable — if not, guide setup
    time.sleep(2)
    progress = _progress.read_progress()
    error = progress.get("error", "")

    if "CDP not available" in error or "not available" in error.lower():
        setup_result = _check_and_setup_cdp()
        if setup_result:
            return {
                "status": "started",
                "pid": proc.pid,
                "log_file": _progress.WORKER_LOG_FILE,
                "cdp_setup": setup_result,
                "message": setup_result.get("message", "Bridge started but CDP not available."),
            }

    return {
        "status": "started",
        "pid": proc.pid,
        "log_file": _progress.WORKER_LOG_FILE,
        "message": "Bridge connecting to IDE. Use kaptn_status to check progress.",
    }


def _check_and_setup_cdp() -> dict | None:
    """Check if CDP is configured in Windsurf's argv.json and auto-configure if not.

    Returns:
        Setup guidance dict, or None if CDP is already configured.
    """
    status = check_cdp_configured()

    if status["configured"]:
        return {
            "configured": True,
            "message": (
                f"CDP port {status['current_port']} is configured in {status['path']} "
                "but Windsurf may not be running or needs a restart. "
                "Please restart Windsurf, then run kaptn_connect again."
            ),
        }

    # Not configured — auto-configure
    result = configure_cdp()
    if result["success"]:
        action = result["action"]
        if action == "already_configured":
            return {
                "configured": True,
                "message": (
                    "CDP is configured but Windsurf needs a restart. "
                    "Please restart Windsurf, then run kaptn_connect again."
                ),
            }
        return {
            "configured": True,
            "action": action,
            "path": result["path"],
            "message": (
                f"CDP remote debugging has been enabled in {result['path']}. "
                "Please **restart Windsurf** for the change to take effect, "
                "then run kaptn_connect again."
            ),
        }

    return {
        "configured": False,
        "error": result.get("error", "Unknown error"),
        "message": (
            f"Failed to configure CDP: {result.get('error')}. "
            "You can manually add '\"remote-debugging-port\": \"9222\"' to "
            f"{status['path']}"
        ),
    }

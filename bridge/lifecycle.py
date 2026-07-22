"""Process lifecycle helpers — find and stop running Kaptn servers.

`kaptn stop` needs to handle two ways a server can be running:

1. The macOS launchd agent (KeepAlive) — must be booted out via launchctl
   first, otherwise killing its process just makes launchd restart it.
2. Manual foreground/background invocations (`kaptn start`,
   `kaptn claude serve`, `kaptn mcp start`) — terminated by pid.
"""

import logging
import os
import signal
import subprocess
import sys
import time

logger = logging.getLogger(__name__)

DEFAULT_LAUNCHD_LABEL = "com.micahai.kaptn.claude"
DEFAULT_GRACE_SECONDS = 5.0

_PROCESS_PATTERNS = ("kaptn start", "kaptn claude serve", "kaptn mcp start")


def launchd_agent_loaded(label: str, uid: int | None = None) -> bool:
    """Check whether the Kaptn launchd agent is loaded (macOS only).

    Args:
        label: The launchd job label.
        uid: User id for the gui domain (defaults to the current user).

    Returns:
        True if the agent is loaded in the user's gui domain.
    """
    if sys.platform != "darwin":
        return False
    uid = os.getuid() if uid is None else uid
    result = subprocess.run(
        ["launchctl", "print", f"gui/{uid}/{label}"], capture_output=True
    )
    return result.returncode == 0


def bootout_launchd_agent(label: str, uid: int | None = None) -> bool:
    """Unload the Kaptn launchd agent so KeepAlive stops resurrecting it.

    The agent stays unloaded until next login (RunAtLoad) or a manual
    `launchctl bootstrap`.

    Args:
        label: The launchd job label.
        uid: User id for the gui domain (defaults to the current user).

    Returns:
        True if the bootout succeeded.
    """
    if sys.platform != "darwin":
        return False
    uid = os.getuid() if uid is None else uid
    result = subprocess.run(
        ["launchctl", "bootout", f"gui/{uid}/{label}"], capture_output=True
    )
    if result.returncode != 0:
        logger.warning(
            "launchctl bootout failed for %s: %s",
            label, result.stderr.decode(errors="replace").strip(),
        )
        return False
    return True


def find_kaptn_processes() -> list[int]:
    """Find pids of running Kaptn server processes.

    Matches manual and launchd-managed invocations by command line.
    The current process is excluded (`kaptn stop` must not stop itself).

    Returns:
        Sorted list of matching pids.
    """
    pids: set[int] = set()
    for pattern in _PROCESS_PATTERNS:
        result = subprocess.run(
            ["pgrep", "-f", pattern], capture_output=True, text=True
        )
        if result.returncode != 0:
            continue
        for token in result.stdout.split():
            try:
                pids.add(int(token))
            except ValueError:
                continue
    pids.discard(os.getpid())
    return sorted(pids)


def terminate_processes(
    pids: list[int], grace_seconds: float = DEFAULT_GRACE_SECONDS
) -> tuple[list[int], list[int]]:
    """SIGTERM each pid, escalating to SIGKILL after a grace period.

    Args:
        pids: Process ids to stop.
        grace_seconds: How long to wait for graceful exit before SIGKILL.

    Returns:
        Tuple of (stopped_gracefully, force_killed) pid lists.
    """
    for pid in pids:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        except PermissionError:
            logger.warning("No permission to stop pid %d", pid)

    remaining = set(pids)
    deadline = time.time() + grace_seconds
    while remaining and time.time() < deadline:
        remaining = {pid for pid in remaining if _alive(pid)}
        if remaining:
            time.sleep(0.2)

    killed = []
    for pid in remaining:
        try:
            os.kill(pid, signal.SIGKILL)
            killed.append(pid)
        except ProcessLookupError:
            pass

    stopped = [pid for pid in pids if pid not in killed]
    return stopped, killed


def _alive(pid: int) -> bool:
    """Check whether a process still exists.

    Child processes that exited but haven't been reaped are zombies —
    os.kill(pid, 0) still succeeds on them, which would wrongly escalate
    to SIGKILL. Reap our own children with waitpid first.
    """
    try:
        done_pid, _ = os.waitpid(pid, os.WNOHANG)
        if done_pid == pid:
            return False
    except ChildProcessError:
        pass  # not our child — fall through to the signal probe

    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def stop_all(
    label: str = DEFAULT_LAUNCHD_LABEL,
    grace_seconds: float = DEFAULT_GRACE_SECONDS,
) -> dict:
    """Stop every running Kaptn server: launchd agent first, then processes.

    Args:
        label: The launchd job label to boot out.
        grace_seconds: SIGTERM grace period before SIGKILL.

    Returns:
        Report dict with keys:
        - agent_stopped (bool): launchd agent was loaded and booted out.
        - stopped (list[int]): pids that exited on SIGTERM (or were gone).
        - killed (list[int]): pids that needed SIGKILL.
    """
    report = {"agent_stopped": False, "stopped": [], "killed": []}

    if launchd_agent_loaded(label):
        report["agent_stopped"] = bootout_launchd_agent(label)
        time.sleep(0.5)  # bootout signals the job — let it wind down

    pids = find_kaptn_processes()
    if pids:
        stopped, killed = terminate_processes(pids, grace_seconds)
        report["stopped"] = stopped
        report["killed"] = killed

    return report

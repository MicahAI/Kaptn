"""Install/uninstall the Kaptn PreToolUse hook in Claude Code settings.

Mirrors bridge.setup.windsurf_setup: writes the hook entry into a Claude
Code settings.json (user-level ~/.claude/settings.json by default, or a
project's .claude/settings.json). Entries are marked by the hook-client
module path so they can be found and removed cleanly.

Every write goes through bridge.claude.hook_guard first: an entry that would
forfeit its permission vote (async) or be killed before it answers is refused
rather than written. See that module and ADR-0012 for why.
"""

import json
import logging
import sys
from pathlib import Path

from bridge.claude.hook_guard import (
    DEFAULT_ANSWER_BUDGET_SECONDS,
    HOOK_MARKER,
    HookGuardError,
    is_kaptn_entry,
    validate_gating_entry,
    validate_gating_timeout,
)

logger = logging.getLogger(__name__)

__all__ = [
    "HOOK_MARKER",
    "HookGuardError",
    "DEFAULT_HOOK_TIMEOUT",
    "default_settings_path",
    "build_hook_command",
    "install_hook",
    "uninstall_hook",
]

DEFAULT_HOOK_TIMEOUT = 10


def default_settings_path(project: str | None = None) -> Path:
    """Resolve the Claude Code settings.json path.

    Args:
        project: Project directory for a project-scoped install, or None
            for the user-level settings.

    Returns:
        Path to the settings.json file.
    """
    if project:
        return Path(project).expanduser() / ".claude" / "settings.json"
    return Path.home() / ".claude" / "settings.json"


def build_hook_command(
    port: int,
    python: str | None = None,
    answer_budget: float | None = DEFAULT_ANSWER_BUDGET_SECONDS,
) -> str:
    """Build the hook command line registered in settings.

    Uses an absolute interpreter path so the hook works regardless of the
    shell PATH Claude Code runs with. The answer budget is baked in so the
    client's deadline and the registered hook timeout are always derived
    from the same number — they cannot drift into a killable gap.

    Args:
        port: The Kaptn hook server port.
        python: Interpreter to use (defaults to the current one — the
            Kaptn venv when invoked via the kaptn CLI).
        answer_budget: Client answer budget in seconds, or None for an
            unbounded hold.

    Returns:
        The command string.
    """
    interpreter = python or sys.executable
    budget = "none" if answer_budget is None else f"{answer_budget:g}"
    return (
        f'"{interpreter}" -m bridge.claude.hook_client '
        f"--port {port} --timeout {budget}"
    )


def install_hook(
    settings_path: Path,
    port: int,
    timeout: int = DEFAULT_HOOK_TIMEOUT,
    python: str | None = None,
    answer_budget: float | None = DEFAULT_ANSWER_BUDGET_SECONDS,
) -> bool:
    """Install (or update) the Kaptn PreToolUse hook entry.

    Idempotent: any existing Kaptn entries are replaced, other hooks are
    left untouched.

    The entry is validated before anything is written — a hook that would
    forfeit its vote or be killed mid-answer is never registered.

    Args:
        settings_path: The settings.json to modify.
        port: Hook server port baked into the command.
        timeout: Hook timeout in seconds.
        python: Interpreter override (mainly for tests).
        answer_budget: Longest answer the hook client can produce, in
            seconds; None for an ADR-0012 unbounded hold. The registered
            timeout must clear a margin over it.

    Returns:
        True if the file content changed.

    Raises:
        ValueError: If the existing settings file is not valid JSON.
        HookGuardError: If the entry would silently disable gating.
    """
    source = f"{settings_path} (Kaptn gating hook)"
    validate_gating_timeout(timeout, answer_budget, source=source)

    settings = _load_settings(settings_path)
    before = json.dumps(settings, sort_keys=True)

    entry = {
        "matcher": "*",
        "hooks": [{
            "type": "command",
            "command": build_hook_command(port, python, answer_budget),
            "timeout": timeout,
        }],
    }
    validate_gating_entry(entry, source=source)

    hooks = settings.setdefault("hooks", {})
    entries = [e for e in hooks.get("PreToolUse", []) if not is_kaptn_entry(e)]
    entries.append(entry)
    hooks["PreToolUse"] = entries

    changed = json.dumps(settings, sort_keys=True) != before
    if changed:
        _write_settings(settings_path, settings)
        logger.info("Installed Kaptn hook in %s (port=%d)", settings_path, port)
    return changed


def uninstall_hook(settings_path: Path) -> bool:
    """Remove all Kaptn hook entries from a settings file.

    Args:
        settings_path: The settings.json to modify.

    Returns:
        True if an entry was removed, False if none was present.

    Raises:
        ValueError: If the existing settings file is not valid JSON.
    """
    if not settings_path.exists():
        return False

    settings = _load_settings(settings_path)
    hooks = settings.get("hooks", {})
    entries = hooks.get("PreToolUse", [])
    kept = [e for e in entries if not is_kaptn_entry(e)]
    if kept == entries:
        return False

    if kept:
        hooks["PreToolUse"] = kept
    else:
        hooks.pop("PreToolUse", None)
        if not hooks:
            settings.pop("hooks", None)

    _write_settings(settings_path, settings)
    logger.info("Removed Kaptn hook from %s", settings_path)
    return True


def _load_settings(settings_path: Path) -> dict:
    """Load a settings file, returning {} if it doesn't exist.

    Raises:
        ValueError: If the file exists but is not valid JSON — never
            silently overwrite a user's settings.
    """
    if not settings_path.exists():
        return {}
    try:
        return json.loads(settings_path.read_text())
    except json.JSONDecodeError as e:
        raise ValueError(f"{settings_path} is not valid JSON: {e}") from e


def _write_settings(settings_path: Path, settings: dict) -> None:
    """Write settings JSON, creating parent directories as needed."""
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(json.dumps(settings, indent=2) + "\n")

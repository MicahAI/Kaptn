"""Install/uninstall the Kaptn PreToolUse hook in Claude Code settings.

Mirrors bridge.setup.windsurf_setup: writes the hook entry into a Claude
Code settings.json (user-level ~/.claude/settings.json by default, or a
project's .claude/settings.json). Entries are marked by the hook-client
module path so they can be found and removed cleanly.
"""

import json
import logging
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

HOOK_MARKER = "bridge.claude.hook_client"
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


def build_hook_command(port: int, python: str | None = None) -> str:
    """Build the hook command line registered in settings.

    Uses an absolute interpreter path so the hook works regardless of the
    shell PATH Claude Code runs with.

    Args:
        port: The Kaptn hook server port.
        python: Interpreter to use (defaults to the current one — the
            Kaptn venv when invoked via the kaptn CLI).

    Returns:
        The command string.
    """
    interpreter = python or sys.executable
    return f'"{interpreter}" -m bridge.claude.hook_client --port {port}'


def install_hook(
    settings_path: Path,
    port: int,
    timeout: int = DEFAULT_HOOK_TIMEOUT,
    python: str | None = None,
) -> bool:
    """Install (or update) the Kaptn PreToolUse hook entry.

    Idempotent: any existing Kaptn entries are replaced, other hooks are
    left untouched.

    Args:
        settings_path: The settings.json to modify.
        port: Hook server port baked into the command.
        timeout: Hook timeout in seconds.
        python: Interpreter override (mainly for tests).

    Returns:
        True if the file content changed.

    Raises:
        ValueError: If the existing settings file is not valid JSON.
    """
    settings = _load_settings(settings_path)
    before = json.dumps(settings, sort_keys=True)

    hooks = settings.setdefault("hooks", {})
    entries = [e for e in hooks.get("PreToolUse", []) if not _is_kaptn_entry(e)]
    entries.append({
        "matcher": "*",
        "hooks": [{
            "type": "command",
            "command": build_hook_command(port, python),
            "timeout": timeout,
        }],
    })
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
    kept = [e for e in entries if not _is_kaptn_entry(e)]
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


def _is_kaptn_entry(entry: dict) -> bool:
    """Check whether a PreToolUse entry was installed by Kaptn."""
    for hook in entry.get("hooks", []):
        if HOOK_MARKER in str(hook.get("command", "")):
            return True
    return False


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

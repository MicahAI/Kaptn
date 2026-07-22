"""Windsurf IDE setup — detect and configure CDP remote debugging port."""

import json
import logging
import platform
import re
from pathlib import Path

logger = logging.getLogger(__name__)

# Default CDP port for Kaptn
DEFAULT_CDP_PORT = 9222


def _get_argv_path() -> Path:
    """Return the platform-specific path to Windsurf's argv.json.

    Returns:
        Path to argv.json.
    """
    system = platform.system()
    if system == "Darwin":
        return Path.home() / ".windsurf" / "argv.json"
    elif system == "Windows":
        appdata = Path.home() / "AppData" / "Roaming" / "Windsurf"
        return appdata / "argv.json"
    else:
        # Linux — same dotfile convention as macOS
        return Path.home() / ".windsurf" / "argv.json"


def _read_jsonc(path: Path) -> tuple[str, dict]:
    """Read a JSONC file (JSON with comments) and return raw text + parsed dict.

    Strips // line comments before parsing. Preserves the raw text so
    we can do a minimal in-place edit rather than rewriting the file.

    Args:
        path: Path to the JSONC file.

    Returns:
        Tuple of (raw_text, parsed_dict).

    Raises:
        FileNotFoundError: If the file doesn't exist.
        json.JSONDecodeError: If parsing fails after stripping comments.
    """
    raw = path.read_text(encoding="utf-8")
    # Strip // line comments (but not inside strings — good enough for argv.json)
    stripped = re.sub(r'^\s*//.*$', '', raw, flags=re.MULTILINE)
    data = json.loads(stripped)
    return raw, data


def check_cdp_configured(port: int = DEFAULT_CDP_PORT) -> dict:
    """Check if Windsurf's argv.json has remote-debugging-port configured.

    Args:
        port: Expected CDP port number.

    Returns:
        Dict with keys:
        - configured (bool): True if the port is already set.
        - path (str): Path to argv.json.
        - current_port (str|None): Current port value if configured.
        - file_exists (bool): Whether argv.json exists.
    """
    argv_path = _get_argv_path()
    result = {
        "configured": False,
        "path": str(argv_path),
        "current_port": None,
        "file_exists": argv_path.exists(),
    }

    if not argv_path.exists():
        return result

    try:
        _raw, data = _read_jsonc(argv_path)
        current = data.get("remote-debugging-port")
        if current is not None:
            result["configured"] = True
            result["current_port"] = str(current)
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Failed to read %s: %s", argv_path, e)
        result["error"] = str(e)

    return result


def configure_cdp(port: int = DEFAULT_CDP_PORT) -> dict:
    """Add remote-debugging-port to Windsurf's argv.json.

    If the file exists, patches it in-place by inserting the key before
    the closing brace. If the file doesn't exist, creates a minimal one.

    Args:
        port: CDP port number to configure.

    Returns:
        Dict with keys:
        - success (bool): Whether the config was written.
        - path (str): Path to argv.json.
        - action (str): "already_configured", "patched", "created", or "error".
        - restart_required (bool): Whether Windsurf needs to be restarted.
    """
    argv_path = _get_argv_path()
    port_str = str(port)

    # Check if already configured
    status = check_cdp_configured(port)
    if status["configured"]:
        return {
            "success": True,
            "path": str(argv_path),
            "action": "already_configured",
            "current_port": status["current_port"],
            "restart_required": False,
        }

    try:
        if argv_path.exists():
            # Patch existing file — insert before the last closing brace
            raw = argv_path.read_text(encoding="utf-8")
            # Find the last } and insert our key before it
            last_brace = raw.rfind("}")
            if last_brace == -1:
                return {
                    "success": False,
                    "path": str(argv_path),
                    "action": "error",
                    "error": "argv.json has no closing brace — cannot patch",
                    "restart_required": False,
                }

            # Check if we need a comma before our new entry
            # Look backwards from the brace for the last non-whitespace/comment char
            before = raw[:last_brace].rstrip()
            needs_comma = before and before[-1] not in (",", "{")

            insert = ""
            if needs_comma:
                insert += ","
            insert += f'\n\n\t// Enable CDP for Kaptn autopilot\n\t"remote-debugging-port": "{port_str}"\n'

            patched = raw[:last_brace] + insert + raw[last_brace:]
            argv_path.write_text(patched, encoding="utf-8")
            logger.info("Patched %s with remote-debugging-port=%s", argv_path, port_str)

            return {
                "success": True,
                "path": str(argv_path),
                "action": "patched",
                "restart_required": True,
            }
        else:
            # Create new file
            argv_path.parent.mkdir(parents=True, exist_ok=True)
            content = (
                "// Windsurf CLI arguments — managed by Kaptn\n"
                "{\n"
                f'\t// Enable CDP for Kaptn autopilot\n'
                f'\t"remote-debugging-port": "{port_str}"\n'
                "}\n"
            )
            argv_path.write_text(content, encoding="utf-8")
            logger.info("Created %s with remote-debugging-port=%s", argv_path, port_str)

            return {
                "success": True,
                "path": str(argv_path),
                "action": "created",
                "restart_required": True,
            }

    except OSError as e:
        logger.error("Failed to write %s: %s", argv_path, e)
        return {
            "success": False,
            "path": str(argv_path),
            "action": "error",
            "error": str(e),
            "restart_required": False,
        }

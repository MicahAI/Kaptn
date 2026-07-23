"""Configuration manager — loads and validates kaptn.config.json."""

import json
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_CONFIG = {
    "mode": "local",
    "cdp_port": 9222,
    "bridge_port": 3001,
    "ide": "windsurf",
    "audit_db": "kaptn_audit.db",
    "claude": {
        "enabled": True,
        "hook_port": 3002,
        "launchd_label": "com.micahai.kaptn.claude",
    },
    "poll_intervals": {
        "messages": 2.0,
        "approvals": 1.0,
        "status": 5.0,
    },
    "autopilot": {
        "enabled": True,
        "rules": [
            {
                "id": "allow-file-reads",
                "category": "file_read",
                "action": "approve",
            },
            {
                "id": "allow-file-writes",
                "category": "file_write",
                "action": "approve",
                "limits": {"max_per_session": 50},
            },
            {
                "id": "block-file-deletes",
                "category": "file_delete",
                "action": "deny",
            },
            {
                "id": "allow-safe-commands",
                "category": "command_safe",
                "action": "approve",
                "limits": {"max_per_session": 100},
            },
            {
                "id": "escalate-unsafe-commands",
                "category": "command_unsafe",
                "action": "escalate",
            },
            {
                "id": "allow-search",
                "category": "search",
                "action": "approve",
            },
            {
                "id": "escalate-unknown",
                "category": "unknown",
                "action": "escalate",
            },
        ],
        "loop_detection": {
            "enabled": True,
            "same_action_threshold": 3,
            "oscillation_threshold": 3,
            "history_size": 20,
        },
    },
    "logging": {
        "level": "INFO",
        "format": "console",
        "file": None,
        "per_module": {},
    },
}


class ConfigManager:
    """Loads, validates, and provides access to Kaptn configuration.

    Merges user config file with defaults. Missing keys fall back to defaults.
    """

    DEFAULT_PATH = "kaptn.config.json"

    def __init__(self, config_path: str = DEFAULT_PATH) -> None:
        """Initialize the config manager.

        Args:
            config_path: Path to the JSON config file. When left at the
                default, the path is resolved so the CLI works from any
                directory (see _resolve_default).
        """
        self.config_path = self._resolve_default(config_path)

    @classmethod
    def _resolve_default(cls, config_path: str) -> Path:
        """Resolve the default config path so `kaptn` works from any cwd.

        Explicit paths are used as-is. For the bare default, resolution
        order is: ./kaptn.config.json if present, then $KAPTN_CONFIG,
        then ~/.kaptn/kaptn.config.json if present, else the cwd default
        (original behavior).

        Args:
            config_path: The path passed to the constructor.

        Returns:
            The resolved Path.
        """
        path = Path(config_path)
        if config_path != cls.DEFAULT_PATH or path.exists():
            return path

        env_path = os.environ.get("KAPTN_CONFIG")
        if env_path:
            return Path(env_path)

        home_path = Path.home() / ".kaptn" / "kaptn.config.json"
        if home_path.exists():
            return home_path

        return path

    def load(self) -> dict:
        """Load config from file, merged with defaults.

        If the file doesn't exist, returns defaults and creates the file.

        Returns:
            Merged configuration dict.
        """
        if not self.config_path.exists():
            logger.info("No config file found at %s, using defaults", self.config_path)
            self._write_defaults()
            return dict(DEFAULT_CONFIG)

        try:
            with open(self.config_path) as f:
                user_config = json.load(f)
            logger.info("Loaded config from %s", self.config_path)
        except json.JSONDecodeError as e:
            logger.error("Invalid JSON in %s: %s — using defaults", self.config_path, e)
            return dict(DEFAULT_CONFIG)

        merged = self._deep_merge(dict(DEFAULT_CONFIG), user_config)
        self._absolutize_audit_db(merged)
        return merged

    def _absolutize_audit_db(self, config: dict) -> None:
        """Resolve a relative audit_db path against the config file's directory.

        Keeps `kaptn log`/`kaptn status` pointed at the real audit DB no
        matter which directory the CLI runs from.
        """
        audit_db = config.get("audit_db")
        if audit_db and audit_db != ":memory:" and not Path(audit_db).is_absolute():
            # resolve() the file first so a symlinked config (e.g.
            # ~/.kaptn/kaptn.config.json) anchors to its real directory
            config["audit_db"] = str(self.config_path.resolve().parent / audit_db)

    def save(self, config: dict) -> bool:
        """Write config dict back to disk.

        Args:
            config: The full configuration dict to persist.

        Returns:
            True if saved successfully, False on error.
        """
        try:
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.config_path, "w") as f:
                json.dump(config, f, indent=2)
                f.write("\n")
            logger.info("Config saved to %s", self.config_path)
            return True
        except OSError as e:
            logger.error("Failed to save config to %s: %s", self.config_path, e)
            return False

    def _write_defaults(self) -> None:
        """Write default config to disk."""
        try:
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.config_path, "w") as f:
                json.dump(DEFAULT_CONFIG, f, indent=2)
            logger.info("Default config written to %s", self.config_path)
        except OSError as e:
            logger.warning("Could not write default config: %s", e)

    @staticmethod
    def _deep_merge(base: dict, override: dict) -> dict:
        """Recursively merge override into base. Override values take precedence.

        Args:
            base: Base configuration dict.
            override: User-provided overrides.

        Returns:
            Merged dict.
        """
        result = dict(base)
        for key, value in override.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = ConfigManager._deep_merge(result[key], value)
            else:
                result[key] = value
        return result

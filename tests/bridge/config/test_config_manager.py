"""Tests for ConfigManager path resolution and audit_db absolutization."""

import json

from bridge.config.config_manager import ConfigManager


class TestDefaultPathResolution:
    def test_explicit_path_used_as_is(self, tmp_path):
        explicit = tmp_path / "custom.json"
        assert ConfigManager(str(explicit)).config_path == explicit

    def test_cwd_file_wins_when_present(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "kaptn.config.json").write_text("{}")
        cm = ConfigManager()
        assert cm.config_path.resolve() == (tmp_path / "kaptn.config.json").resolve()

    def test_env_var_fallback(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)  # no cwd config file
        env_config = tmp_path / "elsewhere" / "kaptn.config.json"
        monkeypatch.setenv("KAPTN_CONFIG", str(env_config))
        assert ConfigManager().config_path == env_config

    def test_home_fallback(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("KAPTN_CONFIG", raising=False)
        monkeypatch.setenv("HOME", str(tmp_path))
        home_config = tmp_path / ".kaptn" / "kaptn.config.json"
        home_config.parent.mkdir()
        home_config.write_text("{}")
        assert ConfigManager().config_path == home_config

    def test_plain_default_when_nothing_else(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("KAPTN_CONFIG", raising=False)
        monkeypatch.setenv("HOME", str(tmp_path))  # no ~/.kaptn
        assert str(ConfigManager().config_path) == "kaptn.config.json"


class TestAuditDbResolution:
    def test_relative_audit_db_resolved_to_config_dir(self, tmp_path):
        config = tmp_path / "kaptn.config.json"
        config.write_text(json.dumps({"audit_db": "kaptn_audit.db"}))
        cfg = ConfigManager(str(config)).load()
        assert cfg["audit_db"] == str(tmp_path.resolve() / "kaptn_audit.db")

    def test_absolute_audit_db_untouched(self, tmp_path):
        config = tmp_path / "kaptn.config.json"
        config.write_text(json.dumps({"audit_db": "/var/data/audit.db"}))
        assert ConfigManager(str(config)).load()["audit_db"] == "/var/data/audit.db"

    def test_symlinked_config_resolves_to_target_dir(self, tmp_path):
        real_dir = tmp_path / "real"
        real_dir.mkdir()
        real_config = real_dir / "kaptn.config.json"
        real_config.write_text(json.dumps({"audit_db": "kaptn_audit.db"}))

        link_dir = tmp_path / "linkhome"
        link_dir.mkdir()
        link = link_dir / "kaptn.config.json"
        link.symlink_to(real_config)

        cfg = ConfigManager(str(link)).load()
        assert cfg["audit_db"] == str(real_dir.resolve() / "kaptn_audit.db")

    def test_memory_db_untouched(self, tmp_path):
        config = tmp_path / "kaptn.config.json"
        config.write_text(json.dumps({"audit_db": ":memory:"}))
        assert ConfigManager(str(config)).load()["audit_db"] == ":memory:"


class TestClaudeDefaults:
    """The hook-governor knobs must be discoverable from config, not only code."""

    def test_answer_budget_is_a_documented_default(self):
        from bridge.config.config_manager import DEFAULT_CONFIG

        assert "answer_budget_seconds" in DEFAULT_CONFIG["claude"]

    def test_default_matches_what_the_client_actually_uses(self):
        from bridge.claude.hook_client import DEFAULT_TIMEOUT_SECONDS
        from bridge.config.config_manager import DEFAULT_CONFIG

        assert DEFAULT_CONFIG["claude"]["answer_budget_seconds"] == DEFAULT_TIMEOUT_SECONDS

    def test_guard_resolves_the_shipped_default(self):
        from bridge.claude.hook_guard import required_timeout, resolve_answer_budget
        from bridge.config.config_manager import DEFAULT_CONFIG

        budget = resolve_answer_budget(DEFAULT_CONFIG["claude"])
        assert budget == 5.0
        assert required_timeout(budget) == 10.0  # the timeout install registers

    def test_null_budget_survives_the_merge_as_an_unbounded_hold(self, tmp_path):
        import json

        from bridge.claude.hook_guard import resolve_answer_budget
        from bridge.config.config_manager import ConfigManager

        path = tmp_path / "kaptn.config.json"
        path.write_text(json.dumps({"claude": {"answer_budget_seconds": None}}))
        cfg = ConfigManager(str(path)).load()
        assert resolve_answer_budget(cfg["claude"]) is None
        assert cfg["claude"]["hook_port"] == 3002  # other defaults still merged

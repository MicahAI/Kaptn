"""Tests for windsurf_setup — detect and configure CDP in argv.json."""

import pytest

from bridge.setup.windsurf_setup import (
    _read_jsonc,
    check_cdp_configured,
    configure_cdp,
)


class TestReadJsonc:
    """Tests for JSONC (JSON with comments) parsing."""

    def test_strips_line_comments(self, tmp_path):
        f = tmp_path / "test.json"
        f.write_text('// comment\n{\n\t// another\n\t"key": "val"\n}\n')
        raw, data = _read_jsonc(f)
        assert data == {"key": "val"}
        assert "// comment" in raw

    def test_preserves_raw_text(self, tmp_path):
        content = '{\n\t"a": 1\n}\n'
        f = tmp_path / "test.json"
        f.write_text(content)
        raw, data = _read_jsonc(f)
        assert raw == content
        assert data == {"a": 1}

    def test_file_not_found(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            _read_jsonc(tmp_path / "nope.json")


class TestCheckCdpConfigured:
    """Tests for check_cdp_configured."""

    def test_configured(self, tmp_path, monkeypatch):
        argv = tmp_path / "argv.json"
        argv.write_text('{\n\t"remote-debugging-port": "9222"\n}\n')
        monkeypatch.setattr("bridge.setup.windsurf_setup._get_argv_path", lambda: argv)

        result = check_cdp_configured()
        assert result["configured"] is True
        assert result["current_port"] == "9222"
        assert result["file_exists"] is True

    def test_not_configured(self, tmp_path, monkeypatch):
        argv = tmp_path / "argv.json"
        argv.write_text('{\n\t"enable-crash-reporter": true\n}\n')
        monkeypatch.setattr("bridge.setup.windsurf_setup._get_argv_path", lambda: argv)

        result = check_cdp_configured()
        assert result["configured"] is False
        assert result["current_port"] is None
        assert result["file_exists"] is True

    def test_file_missing(self, tmp_path, monkeypatch):
        monkeypatch.setattr("bridge.setup.windsurf_setup._get_argv_path", lambda: tmp_path / "nope.json")

        result = check_cdp_configured()
        assert result["configured"] is False
        assert result["file_exists"] is False

    def test_with_comments(self, tmp_path, monkeypatch):
        argv = tmp_path / "argv.json"
        argv.write_text(
            '// Windsurf config\n'
            '{\n'
            '\t// Enable CDP for Kaptn\n'
            '\t"remote-debugging-port": "9222"\n'
            '}\n'
        )
        monkeypatch.setattr("bridge.setup.windsurf_setup._get_argv_path", lambda: argv)

        result = check_cdp_configured()
        assert result["configured"] is True
        assert result["current_port"] == "9222"


class TestConfigureCdp:
    """Tests for configure_cdp."""

    def test_already_configured(self, tmp_path, monkeypatch):
        argv = tmp_path / "argv.json"
        argv.write_text('{\n\t"remote-debugging-port": "9222"\n}\n')
        monkeypatch.setattr("bridge.setup.windsurf_setup._get_argv_path", lambda: argv)

        result = configure_cdp()
        assert result["success"] is True
        assert result["action"] == "already_configured"
        assert result["restart_required"] is False

    def test_patches_existing_file(self, tmp_path, monkeypatch):
        argv = tmp_path / "argv.json"
        original = (
            '// Windsurf config\n'
            '{\n'
            '\t"enable-crash-reporter": true\n'
            '}\n'
        )
        argv.write_text(original)
        monkeypatch.setattr("bridge.setup.windsurf_setup._get_argv_path", lambda: argv)

        result = configure_cdp()
        assert result["success"] is True
        assert result["action"] == "patched"
        assert result["restart_required"] is True

        # Verify the file is valid JSONC with the port
        _, data = _read_jsonc(argv)
        assert data["remote-debugging-port"] == "9222"
        assert data["enable-crash-reporter"] is True

    def test_creates_new_file(self, tmp_path, monkeypatch):
        argv = tmp_path / "windsurf" / "argv.json"
        monkeypatch.setattr("bridge.setup.windsurf_setup._get_argv_path", lambda: argv)

        result = configure_cdp()
        assert result["success"] is True
        assert result["action"] == "created"
        assert result["restart_required"] is True
        assert argv.exists()

        _, data = _read_jsonc(argv)
        assert data["remote-debugging-port"] == "9222"

    def test_custom_port(self, tmp_path, monkeypatch):
        argv = tmp_path / "argv.json"
        argv.write_text('{\n\t"enable-crash-reporter": true\n}\n')
        monkeypatch.setattr("bridge.setup.windsurf_setup._get_argv_path", lambda: argv)

        result = configure_cdp(port=9333)
        assert result["success"] is True

        _, data = _read_jsonc(argv)
        assert data["remote-debugging-port"] == "9333"

    def test_patches_real_windsurf_format(self, tmp_path, monkeypatch):
        """Test with the actual format of Windsurf's argv.json."""
        argv = tmp_path / "argv.json"
        argv.write_text(
            '// This configuration file allows you to pass permanent command line arguments to VS Code.\n'
            '// Only a subset of arguments is currently supported to reduce the likelihood of breaking\n'
            '// the installation.\n'
            '//\n'
            '// PLEASE DO NOT CHANGE WITHOUT UNDERSTANDING THE IMPACT\n'
            '//\n'
            '// NOTE: Changing this file requires a restart of VS Code.\n'
            '{\n'
            '\t// Use software rendering instead of hardware accelerated rendering.\n'
            '\t// This can help in cases where you see rendering issues in VS Code.\n'
            '\t// "disable-hardware-acceleration": true,\n'
            '\n'
            '\t// Allows to disable crash reporting.\n'
            '\t// Should restart the app if the value is changed.\n'
            '\t"enable-crash-reporter": true,\n'
            '\n'
            '\t// Unique id used for correlating crash reports sent from this instance.\n'
            '\t// Do not edit this value.\n'
            '\t"crash-reporter-id": "33317d9c-52d6-400c-8e8e-b1ecfa68b016"\n'
            '}\n'
        )
        monkeypatch.setattr("bridge.setup.windsurf_setup._get_argv_path", lambda: argv)

        result = configure_cdp()
        assert result["success"] is True
        assert result["action"] == "patched"

        # Verify the patched file is valid JSONC
        _, data = _read_jsonc(argv)
        assert data["remote-debugging-port"] == "9222"
        assert data["enable-crash-reporter"] is True
        assert data["crash-reporter-id"] == "33317d9c-52d6-400c-8e8e-b1ecfa68b016"

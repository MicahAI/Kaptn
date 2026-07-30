"""The `logging` config section is honored.

Every key in it existed in kaptn.config.json and matched a setup_logging()
parameter, but no call site ever passed them — the whole block was inert.
"""

import logging

from bridge.logging_config import setup_logging, setup_logging_from_config


def teardown_function():
    setup_logging(level="INFO")  # restore a sane root state for other tests


def _bridge_logger():
    return logging.getLogger("bridge")


class TestSetupLoggingFromConfig:
    def test_level_comes_from_config(self):
        setup_logging_from_config({"logging": {"level": "ERROR"}})
        assert _bridge_logger().level == logging.ERROR

    def test_cli_override_wins(self):
        setup_logging_from_config({"logging": {"level": "ERROR"}}, level="DEBUG")
        assert _bridge_logger().level == logging.DEBUG

    def test_defaults_to_info_without_a_logging_section(self):
        setup_logging_from_config({})
        assert _bridge_logger().level == logging.INFO

    def test_null_logging_section_is_tolerated(self):
        setup_logging_from_config({"logging": None})
        assert _bridge_logger().level == logging.INFO

    def test_file_handler_is_attached(self, tmp_path):
        log_file = tmp_path / "kaptn.log"
        setup_logging_from_config({"logging": {"level": "INFO", "file": str(log_file)}})
        logging.getLogger("bridge.test").warning("hello")
        assert log_file.exists()
        assert "hello" in log_file.read_text()

    def test_json_format_is_applied(self):
        from bridge.logging_config import JsonFormatter

        setup_logging_from_config({"logging": {"format": "json"}})
        handlers = _bridge_logger().handlers
        assert any(isinstance(h.formatter, JsonFormatter) for h in handlers)

    def test_per_module_overrides_are_applied(self):
        setup_logging_from_config({"logging": {"per_module": {"bridge.cdp": "DEBUG"}}})
        assert logging.getLogger("bridge.cdp").level == logging.DEBUG

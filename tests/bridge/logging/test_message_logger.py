"""Tests for MessageLogger — captures USER/CASCADE messages to messages.log."""

import os
import tempfile
from datetime import datetime

from bridge.logging.message_logger import MessageLogger


class TestMessageLogger:

    def _make_logger(self, tmp_path):
        log_path = os.path.join(tmp_path, "messages.log")
        return MessageLogger(log_path=log_path), log_path

    def test_logs_user_message(self, tmp_path):
        ml, path = self._make_logger(str(tmp_path))
        ts = datetime(2026, 3, 8, 21, 15, 13, 748000)
        ml.log_message("Kaptn", "user", "What is the status?", timestamp=ts)
        ml.close()

        content = open(path).read()
        assert "[2026-03-08 21:15:13.748] [Kaptn] USER: What is the status?" in content

    def test_logs_assistant_as_cascade(self, tmp_path):
        ml, path = self._make_logger(str(tmp_path))
        ts = datetime(2026, 3, 8, 21, 15, 18, 6000)
        ml.log_message("Kaptn", "assistant", "The bridge is running.", timestamp=ts)
        ml.close()

        content = open(path).read()
        assert "[Kaptn] CASCADE: The bridge is running." in content

    def test_ignores_tool_call(self, tmp_path):
        ml, path = self._make_logger(str(tmp_path))
        ml.log_message("Kaptn", "tool_call", "Running git status...")
        ml.close()

        content = open(path).read() if os.path.exists(path) else ""
        assert "tool_call" not in content
        assert "git status" not in content

    def test_ignores_feedback(self, tmp_path):
        ml, path = self._make_logger(str(tmp_path))
        ml.log_message("Kaptn", "feedback", "some feedback")
        ml.close()

        content = open(path).read() if os.path.exists(path) else ""
        assert "feedback" not in content

    def test_multiline_collapsed(self, tmp_path):
        ml, path = self._make_logger(str(tmp_path))
        ml.log_message("Kaptn", "user", "line one\nline two\n  line three")
        ml.close()

        lines = open(path).readlines()
        assert len(lines) == 1
        assert "line one line two line three" in lines[0]

    def test_session_marker(self, tmp_path):
        ml, path = self._make_logger(str(tmp_path))
        ml.log_session_marker("Kaptn")
        ml.close()

        content = open(path).read()
        assert "[Kaptn] New conversation" in content
        assert "---" in content

    def test_multiple_messages_ordered(self, tmp_path):
        ml, path = self._make_logger(str(tmp_path))
        ts1 = datetime(2026, 3, 8, 21, 0, 0)
        ts2 = datetime(2026, 3, 8, 21, 0, 5)
        ts3 = datetime(2026, 3, 8, 21, 0, 10)

        ml.log_message("Kaptn", "user", "Hello", timestamp=ts1)
        ml.log_message("Kaptn", "assistant", "Hi there!", timestamp=ts2)
        ml.log_message("Kaptn", "user", "Do something", timestamp=ts3)
        ml.close()

        lines = [l for l in open(path).readlines() if l.strip()]
        assert len(lines) == 3
        assert "USER: Hello" in lines[0]
        assert "CASCADE: Hi there!" in lines[1]
        assert "USER: Do something" in lines[2]

    def test_mixed_roles_filters_correctly(self, tmp_path):
        ml, path = self._make_logger(str(tmp_path))
        ml.log_message("Kaptn", "user", "What time is it?")
        ml.log_message("Kaptn", "tool_call", "Running clock...")
        ml.log_message("Kaptn", "assistant", "It is 9pm.")
        ml.log_message("Kaptn", "feedback", "thumbs up")
        ml.log_message("Kaptn", "show_more", "click to expand")
        ml.close()

        lines = [l for l in open(path).readlines() if l.strip()]
        assert len(lines) == 2
        assert "USER:" in lines[0]
        assert "CASCADE:" in lines[1]

    def test_window_name_in_output(self, tmp_path):
        ml, path = self._make_logger(str(tmp_path))
        ml.log_message("TelemetryMCPV2", "user", "query data")
        ml.close()

        content = open(path).read()
        assert "[TelemetryMCPV2]" in content

    def test_creates_directory(self):
        with tempfile.TemporaryDirectory() as td:
            nested = os.path.join(td, "sub", "dir", "messages.log")
            ml = MessageLogger(log_path=nested)
            ml.log_message("Kaptn", "user", "test")
            ml.close()
            assert os.path.exists(nested)

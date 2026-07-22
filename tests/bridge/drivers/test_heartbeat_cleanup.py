"""Tests for heartbeat self-cleanup behavior in WindsurfDriver.

Uses a mock CdpEvaluator to verify the Python-side methods work correctly.
The actual JS cleanup logic can be tested end-to-end via trigger_cleanup_check
against a real CDP connection (see integration test comments below).
"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from bridge.drivers.windsurf_driver import WindsurfDriver


@pytest.fixture
def mock_driver():
    """Create a WindsurfDriver with a mocked evaluator."""
    evaluator = MagicMock()
    evaluator.evaluate = AsyncMock()
    return WindsurfDriver(evaluator)


class TestSendHeartbeat:
    """Tests for WindsurfDriver.send_heartbeat."""

    async def test_sends_heartbeat_js(self, mock_driver):
        mock_driver.evaluator.evaluate.return_value = 1234567890
        result = await mock_driver.send_heartbeat()
        assert result is True
        # Verify it evaluated the heartbeat assignment
        call_args = mock_driver.evaluator.evaluate.call_args[0][0]
        assert "__kaptnHeartbeat" in call_args
        assert "Date.now()" in call_args

    async def test_returns_false_on_failure(self, mock_driver):
        mock_driver.evaluator.evaluate.return_value = None
        result = await mock_driver.send_heartbeat()
        assert result is False


class TestGetObserverStatus:
    """Tests for WindsurfDriver.get_observer_status."""

    async def test_returns_status_dict(self, mock_driver):
        mock_driver.evaluator.evaluate.return_value = {
            "installed": True,
            "heartbeat_age_ms": 500,
            "cleanup_pending": False,
            "globals": ["__kaptnObserver", "__kaptnMessages", "__kaptnHeartbeat"],
        }
        status = await mock_driver.get_observer_status()
        assert status["installed"] is True
        assert status["heartbeat_age_ms"] == 500
        assert status["cleanup_pending"] is False
        assert "__kaptnObserver" in status["globals"]

    async def test_returns_defaults_on_failure(self, mock_driver):
        mock_driver.evaluator.evaluate.return_value = None
        status = await mock_driver.get_observer_status()
        assert status["installed"] is False
        assert status["heartbeat_age_ms"] == -1
        assert status["globals"] == []

    async def test_no_observer_installed(self, mock_driver):
        mock_driver.evaluator.evaluate.return_value = {
            "installed": False,
            "heartbeat_age_ms": -1,
            "cleanup_pending": False,
            "globals": [],
        }
        status = await mock_driver.get_observer_status()
        assert status["installed"] is False
        assert status["globals"] == []


class TestTriggerCleanupCheck:
    """Tests for WindsurfDriver.trigger_cleanup_check."""

    async def test_fresh_heartbeat(self, mock_driver):
        mock_driver.evaluator.evaluate.return_value = {
            "action": "fresh",
            "heartbeat_age_ms": 100,
        }
        result = await mock_driver.trigger_cleanup_check(stale_ms=300000, grace_ms=300000)
        assert result["action"] == "fresh"

    async def test_stale_starts_pending(self, mock_driver):
        mock_driver.evaluator.evaluate.return_value = {
            "action": "stale_pending",
            "heartbeat_age_ms": 400000,
        }
        result = await mock_driver.trigger_cleanup_check(stale_ms=0, grace_ms=300000)
        assert result["action"] == "stale_pending"

    async def test_grace_period_waiting(self, mock_driver):
        mock_driver.evaluator.evaluate.return_value = {
            "action": "grace_waiting",
            "heartbeat_age_ms": 500000,
        }
        result = await mock_driver.trigger_cleanup_check(stale_ms=0, grace_ms=300000)
        assert result["action"] == "grace_waiting"

    async def test_cleanup_triggered(self, mock_driver):
        mock_driver.evaluator.evaluate.return_value = {
            "action": "cleaned",
            "heartbeat_age_ms": 999999999,
        }
        # stale_ms=0, grace_ms=0 → immediate cleanup
        result = await mock_driver.trigger_cleanup_check(stale_ms=0, grace_ms=0)
        assert result["action"] == "cleaned"

    async def test_error_on_failure(self, mock_driver):
        mock_driver.evaluator.evaluate.return_value = None
        result = await mock_driver.trigger_cleanup_check()
        assert result["action"] == "error"

    async def test_cleanup_check_includes_thresholds(self, mock_driver):
        """Verify custom thresholds are passed into the JS."""
        mock_driver.evaluator.evaluate.return_value = {"action": "fresh", "heartbeat_age_ms": 0}
        await mock_driver.trigger_cleanup_check(stale_ms=12345, grace_ms=67890)
        js_code = mock_driver.evaluator.evaluate.call_args[0][0]
        assert "12345" in js_code
        assert "67890" in js_code


class TestObserverInstallIncludesCleanup:
    """Verify the observer installation JS includes the cleanup timer."""

    async def test_observer_js_has_heartbeat_init(self, mock_driver):
        mock_driver.evaluator.evaluate.return_value = {"installed": True}
        await mock_driver.install_message_observer()
        js_code = mock_driver.evaluator.evaluate.call_args[0][0]

        # Verify heartbeat initialization
        assert "__kaptnHeartbeat = Date.now()" in js_code

        # Verify cleanup timer setup
        assert "__kaptnCleanupTimer" in js_code
        assert "__kaptnCleanupPending" in js_code

        # Verify stale/grace thresholds (5 min each)
        assert "5 * 60 * 1000" in js_code

        # Verify cleanup deletes all globals
        assert "delete window.__kaptnObserver" in js_code
        assert "delete window.__kaptnMessages" in js_code
        assert "delete window.__kaptnHeartbeat" in js_code

    async def test_observer_js_clears_previous_timer(self, mock_driver):
        mock_driver.evaluator.evaluate.return_value = {"installed": True}
        await mock_driver.install_message_observer()
        js_code = mock_driver.evaluator.evaluate.call_args[0][0]

        # Should clear any previous cleanup timer on reinstall
        assert "clearInterval(window.__kaptnCleanupTimer)" in js_code


# ============================================================================
# Integration test (requires live CDP connection)
# ============================================================================
# To run a real end-to-end cleanup test against a live Windsurf instance:
#
#   1. Start Windsurf with --remote-debugging-port=9222
#   2. Run: pytest tests/bridge/drivers/test_heartbeat_cleanup.py -k "integration" -v
#
# The test installs the observer, verifies it's alive, triggers cleanup
# with zero thresholds, then verifies everything is gone.
#
# @pytest.mark.integration
# async def test_cleanup_lifecycle_live():
#     from bridge.cdp.cdp_connection import CdpConnection
#     from bridge.cdp.cdp_discovery import CdpDiscovery
#     from bridge.cdp.cdp_evaluator import CdpEvaluator
#
#     discovery = CdpDiscovery(port=9222)
#     pages = discovery.get_page_targets()
#     assert pages, "No Windsurf windows found"
#
#     conn = CdpConnection(pages[0].websocket_url)
#     await conn.connect()
#     driver = WindsurfDriver(CdpEvaluator(conn))
#
#     # Install observer
#     assert await driver.install_message_observer()
#
#     # Verify it's alive
#     status = await driver.get_observer_status()
#     assert status["installed"] is True
#     assert "__kaptnObserver" in status["globals"]
#
#     # Send heartbeat
#     assert await driver.send_heartbeat()
#
#     # Force cleanup with zero thresholds (immediate)
#     result = await driver.trigger_cleanup_check(stale_ms=999999999, grace_ms=0)
#     assert result["action"] == "fresh"  # heartbeat is fresh
#
#     # Now trigger stale + immediate cleanup
#     result = await driver.trigger_cleanup_check(stale_ms=0, grace_ms=0)
#     # First call starts pending
#     assert result["action"] == "stale_pending"
#     # Second call cleans (pending is now set, grace=0 expired)
#     result = await driver.trigger_cleanup_check(stale_ms=0, grace_ms=0)
#     assert result["action"] == "cleaned"
#
#     # Verify everything is gone
#     status = await driver.get_observer_status()
#     assert status["installed"] is False
#     assert status["globals"] == []
#
#     await conn.close()

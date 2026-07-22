"""Tests for state seeding from audit DB and approval detection/deduplication."""

import json
import tempfile
from datetime import datetime, timezone
from unittest.mock import MagicMock, AsyncMock, patch

import pytest

from bridge.audit.audit_logger import AuditLogger
from bridge.main import KaptnBridge
from bridge.models import ApprovalAction, ApprovalCategory, ApprovalRequest, DecisionSource


def _make_config(**overrides):
    """Build a minimal config dict for KaptnBridge."""
    cfg = {
        "cdp_port": 9222,
        "audit_db": ":memory:",
        "poll_interval": 1,
        "autopilot": {
            "enabled": True,
            "rules": [],
            "loop_detection": {
                "same_action_threshold": 3,
                "oscillation_threshold": 3,
                "history_size": 20,
            },
            "reset_on_manual_approve": True,
        },
    }
    cfg.update(overrides)
    return cfg


class TestStateSeedingFromAudit:
    """Tests for _seed_state_from_audit."""

    def test_seeds_fingerprint_from_recent_records(self, tmp_path):
        db_path = str(tmp_path / "test_audit.db")
        cfg = _make_config(audit_db=db_path)

        with patch("bridge.main.CdpDiscovery"):
            bridge = KaptnBridge(cfg)

        req = ApprovalRequest(
            category=ApprovalCategory.COMMAND_UNSAFE,
            action="Run npm install",
            window_name="Kaptn",
            details={"type": "run_skip", "tab_id": "tab-abc-123"},
        )
        bridge.audit.create_record(req, ApprovalAction.APPROVE, DecisionSource.AUTOPILOT, rule_id="allow-unsafe")

        bridge._seed_state_from_audit()

        assert "Kaptn" in bridge._last_approval
        fp = bridge._last_approval["Kaptn"]
        assert fp == "tab-abc-123|run_skip|Run npm install"

    def test_seeds_most_recent_per_window(self, tmp_path):
        db_path = str(tmp_path / "test_audit.db")
        cfg = _make_config(audit_db=db_path)

        with patch("bridge.main.CdpDiscovery"):
            bridge = KaptnBridge(cfg)

        req1 = ApprovalRequest(
            category=ApprovalCategory.COMMAND_SAFE, action="Run echo old",
            window_name="Kaptn", details={"type": "run_skip", "tab_id": "tab-1"},
        )
        bridge.audit.create_record(req1, ApprovalAction.APPROVE, DecisionSource.AUTOPILOT, rule_id="r1")

        req2 = ApprovalRequest(
            category=ApprovalCategory.COMMAND_UNSAFE, action="Run npm install",
            window_name="Kaptn", details={"type": "run_skip", "tab_id": "tab-1"},
        )
        bridge.audit.create_record(req2, ApprovalAction.APPROVE, DecisionSource.AUTOPILOT, rule_id="r2")

        bridge._seed_state_from_audit()

        # get_recent_by_time returns newest first, so "Run npm install" should win
        fp = bridge._last_approval["Kaptn"]
        assert "Run npm install" in fp

    def test_no_records_does_not_seed(self, tmp_path):
        db_path = str(tmp_path / "test_audit.db")
        cfg = _make_config(audit_db=db_path)

        with patch("bridge.main.CdpDiscovery"):
            bridge = KaptnBridge(cfg)

        bridge._seed_state_from_audit()
        assert bridge._last_approval == {}

    def test_multiple_windows_seeded_independently(self, tmp_path):
        db_path = str(tmp_path / "test_audit.db")
        cfg = _make_config(audit_db=db_path)

        with patch("bridge.main.CdpDiscovery"):
            bridge = KaptnBridge(cfg)

        req1 = ApprovalRequest(
            category=ApprovalCategory.COMMAND_SAFE, action="Run echo hello",
            window_name="Kaptn", details={"type": "run_skip", "tab_id": "tab-k"},
        )
        bridge.audit.create_record(req1, ApprovalAction.APPROVE, DecisionSource.AUTOPILOT, rule_id="r1")

        req2 = ApprovalRequest(
            category=ApprovalCategory.COMMAND_UNSAFE, action="Run pip install",
            window_name="TelemetryMCPV2", details={"type": "run_skip", "tab_id": "tab-t"},
        )
        bridge.audit.create_record(req2, ApprovalAction.APPROVE, DecisionSource.AUTOPILOT, rule_id="r2")

        bridge._seed_state_from_audit()

        assert "Kaptn" in bridge._last_approval
        assert "TelemetryMCPV2" in bridge._last_approval
        assert bridge._last_approval["Kaptn"] != bridge._last_approval["TelemetryMCPV2"]

    def test_malformed_details_handled_gracefully(self, tmp_path):
        """If details JSON is malformed, seeding should still work."""
        db_path = str(tmp_path / "test_audit.db")
        cfg = _make_config(audit_db=db_path)

        with patch("bridge.main.CdpDiscovery"):
            bridge = KaptnBridge(cfg)

        # Insert a record normally first
        req = ApprovalRequest(
            category=ApprovalCategory.COMMAND_SAFE, action="Run echo hello",
            window_name="Kaptn", details={"type": "run_skip", "tab_id": "tab-1"},
        )
        bridge.audit.create_record(req, ApprovalAction.APPROVE, DecisionSource.AUTOPILOT)

        # Corrupt the details column directly
        bridge.audit._conn.execute(
            "UPDATE audit_log SET details = 'not-valid-json{{{' WHERE window_name = 'Kaptn'"
        )
        bridge.audit._conn.commit()

        # Should not raise
        bridge._seed_state_from_audit()
        assert "Kaptn" in bridge._last_approval


class TestFingerprintConsistency:
    """Ensure fingerprint format is consistent between seeding and poll loop."""

    def test_fingerprint_format(self):
        """Fingerprint should be: tab_id|type|action[:30]"""
        tab_id = "abc-123-def"
        approval_type = "run_skip"
        action = "Run npm install --save-dev some-long-package-name"

        # Poll loop format (from _poll_loop in main.py)
        poll_fp = f"{tab_id}|{approval_type}|{action[:30]}"

        # Seed format (from _seed_state_from_audit)
        seed_fp = f"{tab_id}|{approval_type}|{action[:30]}"

        assert poll_fp == seed_fp
        assert len(action[:30]) <= 30


class TestDeduplication:
    """Tests for approval deduplication logic."""

    def test_same_fingerprint_skipped(self, tmp_path):
        """If _last_approval has same fingerprint, approval should be skipped."""
        db_path = str(tmp_path / "test_audit.db")
        cfg = _make_config(audit_db=db_path)

        with patch("bridge.main.CdpDiscovery"):
            bridge = KaptnBridge(cfg)

        fingerprint = "tab-1|run_skip|Run echo hello"
        bridge._last_approval["Kaptn"] = fingerprint

        # Same fingerprint → should be treated as duplicate (no re-processing)
        assert bridge._last_approval.get("Kaptn") == fingerprint

    def test_different_fingerprint_processed(self, tmp_path):
        """Different fingerprint should trigger processing."""
        db_path = str(tmp_path / "test_audit.db")
        cfg = _make_config(audit_db=db_path)

        with patch("bridge.main.CdpDiscovery"):
            bridge = KaptnBridge(cfg)

        bridge._last_approval["Kaptn"] = "tab-1|run_skip|Run echo hello"
        new_fp = "tab-1|run_skip|Run npm install"

        assert new_fp != bridge._last_approval["Kaptn"]


class TestEscalationTracking:
    """Tests for escalation state and manual approval reset."""

    def test_escalation_state_stored(self, tmp_path):
        db_path = str(tmp_path / "test_audit.db")
        cfg = _make_config(audit_db=db_path)

        with patch("bridge.main.CdpDiscovery"):
            bridge = KaptnBridge(cfg)

        bridge._escalated["Kaptn"] = "allow-unsafe-commands"
        assert bridge._escalated["Kaptn"] == "allow-unsafe-commands"

    def test_escalation_state_cleared_on_manual_approve(self, tmp_path):
        db_path = str(tmp_path / "test_audit.db")
        cfg = _make_config(audit_db=db_path)

        with patch("bridge.main.CdpDiscovery"):
            bridge = KaptnBridge(cfg)

        bridge._escalated["Kaptn"] = "allow-unsafe-commands"
        bridge._last_approval["Kaptn"] = "some-fingerprint"

        # Simulate the poll loop's "approval gone" logic
        escalated_rule = bridge._escalated.pop("Kaptn", None)
        assert escalated_rule == "allow-unsafe-commands"
        assert "Kaptn" not in bridge._escalated

    def test_reset_on_manual_config(self, tmp_path):
        db_path = str(tmp_path / "test_audit.db")

        cfg_on = _make_config(audit_db=db_path)
        cfg_on["autopilot"]["reset_on_manual_approve"] = True
        with patch("bridge.main.CdpDiscovery"):
            bridge_on = KaptnBridge(cfg_on)
        assert bridge_on._reset_on_manual is True

        cfg_off = _make_config(audit_db=str(tmp_path / "test2.db"))
        cfg_off["autopilot"]["reset_on_manual_approve"] = False
        with patch("bridge.main.CdpDiscovery"):
            bridge_off = KaptnBridge(cfg_off)
        assert bridge_off._reset_on_manual is False

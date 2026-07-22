"""Tests for AuditLogger — persistent approval decision recording."""


from bridge.audit.audit_logger import AuditLogger
from bridge.models import (
    ApprovalAction, ApprovalCategory, ApprovalRequest, DecisionSource,
)


class TestAuditLogger:
    """Tests for the AuditLogger class."""

    def setup_method(self):
        """Create an in-memory audit logger for each test."""
        self.logger = AuditLogger(db_path=":memory:")

    def teardown_method(self):
        """Close the logger after each test."""
        self.logger.close()

    def _make_request(self, action: str = "Edit main.py",
                      category: str = "file_write", window: str = "TestProject") -> ApprovalRequest:
        """Helper to create an ApprovalRequest."""
        return ApprovalRequest(
            category=ApprovalCategory(category),
            action=action,
            window_name=window,
            mode="execute",
        )

    def test_create_record_returns_record(self):
        """create_record returns an AuditRecord with correct fields."""
        request = self._make_request()
        record = self.logger.create_record(
            request=request,
            decision=ApprovalAction.APPROVE,
            source=DecisionSource.AUTOPILOT,
            rule_id="allow-writes",
        )
        assert record.id is not None
        assert record.decision == ApprovalAction.APPROVE
        assert record.source == DecisionSource.AUTOPILOT
        assert record.rule_id == "allow-writes"

    def test_get_count_after_logging(self):
        """get_count reflects logged records."""
        assert self.logger.get_count() == 0

        self.logger.create_record(
            request=self._make_request(),
            decision=ApprovalAction.APPROVE,
            source=DecisionSource.AUTOPILOT,
        )
        assert self.logger.get_count() == 1

        self.logger.create_record(
            request=self._make_request(action="Edit b.py"),
            decision=ApprovalAction.DENY,
            source=DecisionSource.MANUAL,
        )
        assert self.logger.get_count() == 2

    def test_get_recent_returns_newest_first(self):
        """get_recent returns records in reverse chronological order."""
        for i in range(5):
            self.logger.create_record(
                request=self._make_request(action=f"Edit {i}.py"),
                decision=ApprovalAction.APPROVE,
                source=DecisionSource.AUTOPILOT,
            )

        records = self.logger.get_recent(limit=3)
        assert len(records) == 3
        assert "Edit 4.py" in records[0]["action_text"]

    def test_get_recent_filters_by_window(self):
        """get_recent filters by window_name when specified."""
        self.logger.create_record(
            request=self._make_request(window="ProjectA"),
            decision=ApprovalAction.APPROVE,
            source=DecisionSource.AUTOPILOT,
        )
        self.logger.create_record(
            request=self._make_request(window="ProjectB"),
            decision=ApprovalAction.DENY,
            source=DecisionSource.MANUAL,
        )

        records_a = self.logger.get_recent(window_name="ProjectA")
        assert len(records_a) == 1
        assert records_a[0]["window_name"] == "ProjectA"

    def test_get_loops_returns_only_loop_records(self):
        """get_loops returns only records where loop_detected is True."""
        self.logger.create_record(
            request=self._make_request(),
            decision=ApprovalAction.APPROVE,
            source=DecisionSource.AUTOPILOT,
            loop_detected=False,
        )
        self.logger.create_record(
            request=self._make_request(action="Looped action"),
            decision=ApprovalAction.DENY,
            source=DecisionSource.AUTOPILOT,
            loop_detected=True,
        )

        loops = self.logger.get_loops()
        assert len(loops) == 1
        assert loops[0]["action_text"] == "Looped action"
        assert loops[0]["loop_detected"] == 1

    def test_get_count_with_window_filter(self):
        """get_count filters by window_name."""
        self.logger.create_record(
            request=self._make_request(window="A"),
            decision=ApprovalAction.APPROVE, source=DecisionSource.AUTOPILOT,
        )
        self.logger.create_record(
            request=self._make_request(window="A"),
            decision=ApprovalAction.APPROVE, source=DecisionSource.AUTOPILOT,
        )
        self.logger.create_record(
            request=self._make_request(window="B"),
            decision=ApprovalAction.APPROVE, source=DecisionSource.AUTOPILOT,
        )

        assert self.logger.get_count(window_name="A") == 2
        assert self.logger.get_count(window_name="B") == 1
        assert self.logger.get_count() == 3

    def test_close_and_reopen_not_supported(self):
        """After close, get_count returns 0 gracefully."""
        self.logger.create_record(
            request=self._make_request(),
            decision=ApprovalAction.APPROVE, source=DecisionSource.AUTOPILOT,
        )
        self.logger.close()
        assert self.logger.get_count() == 0

    def test_record_stores_details_as_json(self):
        """Request details are stored as JSON and retrievable."""
        request = self._make_request()
        request.details = {"path": "/src/main.py", "diff_lines": 42}

        self.logger.create_record(
            request=request,
            decision=ApprovalAction.APPROVE,
            source=DecisionSource.AUTOPILOT,
        )

        records = self.logger.get_recent(limit=1)
        assert '"path"' in records[0]["details"]
        assert '"diff_lines"' in records[0]["details"]

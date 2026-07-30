"""Tests for the hook guard — the two silent-ungating modes of ADR-0012.

Mode 1: an async PreToolUse hook forfeits its permission vote.
Mode 2: a PreToolUse hook killed at its timeout abstains, which fails open.
"""

import json

import pytest

from bridge.claude.hook_guard import (
    DEFAULT_ANSWER_BUDGET_SECONDS,
    PLATFORM_DEFAULT_TIMEOUT_SECONDS,
    UNBOUNDED_HOLD_TIMEOUT_SECONDS,
    HookGuardError,
    check_effective_settings,
    check_settings,
    client_budget_from_command,
    recommended_timeout,
    required_timeout,
    resolve_answer_budget,
    validate_gating_entry,
    validate_gating_timeout,
)

KAPTN_COMMAND = '"/venv/bin/python" -m bridge.claude.hook_client --port 3002'


def kaptn_entry(**hook_extra) -> dict:
    """A Kaptn-marked PreToolUse entry, with overrides merged into the hook."""
    hook = {"type": "command", "command": KAPTN_COMMAND, "timeout": 10}
    hook.update(hook_extra)
    return {"matcher": "*", "hooks": [hook]}


def third_party_entry(**hook_extra) -> dict:
    """A third-party PreToolUse entry."""
    hook = {"type": "command", "command": "/usr/local/bin/other-governor"}
    hook.update(hook_extra)
    return {"matcher": "*", "hooks": [hook]}


def settings_with(*entries, stop=None) -> dict:
    hooks = {"PreToolUse": list(entries)}
    if stop is not None:
        hooks["Stop"] = stop
    return {"hooks": hooks}


class TestAsyncOnGatingHook:
    """Mode 1 — async forfeits the vote."""

    def test_async_rejected_on_pretooluse(self):
        with pytest.raises(HookGuardError) as e:
            validate_gating_entry(kaptn_entry(**{"async": True}))
        assert '"async": true' in str(e.value)
        assert "FORFEITS" in str(e.value)

    def test_async_rewake_rejected_on_pretooluse(self):
        with pytest.raises(HookGuardError) as e:
            validate_gating_entry(kaptn_entry(asyncRewake=True))
        assert '"asyncRewake": true' in str(e.value)
        assert "UNGATED" in str(e.value)

    def test_async_at_entry_level_rejected(self):
        entry = kaptn_entry()
        entry["async"] = True
        with pytest.raises(HookGuardError):
            validate_gating_entry(entry)

    def test_falsy_async_is_allowed(self):
        validate_gating_entry(kaptn_entry(**{"async": False}))
        validate_gating_entry(kaptn_entry(asyncRewake=False))

    def test_clean_entry_passes(self):
        validate_gating_entry(kaptn_entry())


class TestAsyncRewakeOnStop:
    """asyncRewake on Stop is a planned feature (ADR-0012 idle leg) — never banned."""

    def test_stop_async_rewake_is_not_a_finding(self):
        settings = settings_with(kaptn_entry(), stop=[
            {"hooks": [{"type": "command",
                        "command": "kaptn-relay",
                        "asyncRewake": True,
                        "async": True,
                        "timeout": 1}]},
        ])
        assert check_settings(settings, source="s") == []

    def test_stop_only_settings_produce_no_findings(self):
        settings = {"hooks": {"Stop": [
            {"hooks": [{"type": "command", "command": "relay", "asyncRewake": True}]},
        ]}}
        assert check_settings(settings, source="s") == []


class TestTimeoutMargin:
    """Mode 2 — a killed hook abstains, and abstaining fails open."""

    def test_margin_required_for_default_budget(self):
        assert required_timeout(5.0) == 10.0
        assert recommended_timeout(5.0) == 10

    def test_todays_registered_timeout_passes_by_rule(self):
        validate_gating_timeout(10, DEFAULT_ANSWER_BUDGET_SECONDS)

    def test_margin_violation_detected(self):
        with pytest.raises(HookGuardError) as e:
            validate_gating_timeout(6, DEFAULT_ANSWER_BUDGET_SECONDS)
        assert "10s is required" in str(e.value)
        assert "ABSTAINING" in str(e.value)

    def test_margin_scales_with_a_larger_budget(self):
        assert required_timeout(300.0) == 600.0
        with pytest.raises(HookGuardError):
            validate_gating_timeout(120, 300.0)
        validate_gating_timeout(900, 300.0)

    def test_small_budget_uses_the_absolute_floor(self):
        assert required_timeout(1.0) == 6.0  # 1 + 5, not 1 * 2

    def test_unbounded_hold_requires_an_unbounded_timeout(self):
        assert required_timeout(None) == UNBOUNDED_HOLD_TIMEOUT_SECONDS
        with pytest.raises(HookGuardError) as e:
            validate_gating_timeout(3600, None)
        assert "unbounded hold" in str(e.value)
        validate_gating_timeout(UNBOUNDED_HOLD_TIMEOUT_SECONDS, None)

    def test_missing_timeout_is_scored_as_the_platform_default(self):
        validate_gating_timeout(None, DEFAULT_ANSWER_BUDGET_SECONDS)  # 600 clears 10
        with pytest.raises(HookGuardError) as e:
            validate_gating_timeout(None, None)  # 600 does not clear an unbounded hold
        assert f"{PLATFORM_DEFAULT_TIMEOUT_SECONDS}s default applies" in str(e.value)

    def test_non_positive_budget_rejected(self):
        with pytest.raises(ValueError):
            required_timeout(0)


class TestCheckSettings:
    def test_kaptn_async_is_fatal(self):
        findings = check_settings(
            settings_with(kaptn_entry(**{"async": True})), source="s",
        )
        assert [f.code for f in findings] == ["pretooluse_async"]
        assert findings[0].fatal
        assert "Kaptn's" in findings[0].detail

    def test_kaptn_under_margin_is_fatal(self):
        findings = check_settings(settings_with(kaptn_entry(timeout=3)), source="s")
        assert [f.code for f in findings] == ["pretooluse_under_margin"]
        assert findings[0].fatal

    def test_third_party_async_pretooluse_warns(self):
        findings = check_settings(
            settings_with(kaptn_entry(), third_party_entry(**{"async": True})),
            source="user settings",
        )
        assert len(findings) == 1
        finding = findings[0]
        assert finding.code == "pretooluse_async"
        assert finding.severity == "warning"
        assert not finding.fatal
        assert "third-party" in finding.detail
        assert "FORFEITS its permission vote" in finding.detail
        assert "user settings" in finding.source

    def test_third_party_under_margin_warns_advisory(self):
        findings = check_settings(
            settings_with(third_party_entry(timeout=2)), source="s",
        )
        assert [f.severity for f in findings] == ["warning"]
        assert "answer time is unknown" in findings[0].detail

    def test_third_party_threshold_is_clamped_under_an_unbounded_hold(self):
        # A hold budget must not declare every third-party hook on the machine
        # broken: their advisory threshold is clamped to the platform default.
        settings = settings_with(third_party_entry(timeout=3600))
        assert check_settings(settings, source="s", answer_budget=None) == []
        assert check_settings(settings_with(third_party_entry()), source="s",
                              answer_budget=None) == []

    def test_clean_settings_produce_no_findings(self):
        assert check_settings(settings_with(kaptn_entry()), source="s") == []

    def test_tolerates_malformed_settings(self):
        assert check_settings({}, source="s") == []
        assert check_settings({"hooks": {"PreToolUse": "nonsense"}}, source="s") == []
        assert check_settings({"hooks": {"PreToolUse": [None, 7]}}, source="s") == []
        assert check_settings({"hooks": {"PreToolUse": [{"hooks": [{"timeout": "soon"}]}]}},
                              source="s") == []


class TestRegisteredBudget:
    """The budget baked into the command is ground truth, not config's claim."""

    def test_parses_a_baked_in_budget(self):
        assert client_budget_from_command(f"{KAPTN_COMMAND} --timeout 30") == (True, 30.0)
        assert client_budget_from_command(f"{KAPTN_COMMAND} --timeout=30") == (True, 30.0)

    def test_parses_an_unbounded_budget(self):
        assert client_budget_from_command(f"{KAPTN_COMMAND} --timeout none") == (True, None)
        assert client_budget_from_command(f"{KAPTN_COMMAND} --timeout 0") == (True, None)

    def test_absent_or_unparseable_budget(self):
        assert client_budget_from_command(KAPTN_COMMAND) == (False, None)
        assert client_budget_from_command(f"{KAPTN_COMMAND} --timeout soon") == (False, None)
        assert client_budget_from_command('"unbalanced --timeout 5') == (False, None)

    def test_margin_is_checked_against_the_registered_budget(self):
        # Config claims 5s (10s would do), but the client can take 30s.
        entry = kaptn_entry(timeout=10)
        entry["hooks"][0]["command"] = f"{KAPTN_COMMAND} --timeout 30"
        codes = [f.code for f in check_settings(settings_with(entry), source="s")]
        assert "pretooluse_under_margin" in codes
        assert "answer_budget_drift" in codes

    def test_registered_budget_matching_config_is_silent(self):
        entry = kaptn_entry(timeout=10)
        entry["hooks"][0]["command"] = f"{KAPTN_COMMAND} --timeout 5"
        assert check_settings(settings_with(entry), source="s") == []

    def test_registered_unbounded_hold_demands_an_unbounded_timeout(self):
        entry = kaptn_entry(timeout=3600)
        entry["hooks"][0]["command"] = f"{KAPTN_COMMAND} --timeout none"
        findings = check_settings(settings_with(entry), source="s", answer_budget=None)
        assert [f.code for f in findings] == ["pretooluse_under_margin"]
        assert findings[0].fatal

    def test_legacy_entry_without_a_baked_budget_falls_back_to_config(self):
        assert check_settings(settings_with(kaptn_entry()), source="s") == []


class TestEffectiveSettings:
    def test_findings_are_aggregated_across_sources(self, tmp_path):
        user = tmp_path / "user.json"
        project = tmp_path / "project.json"
        user.write_text(json.dumps(settings_with(kaptn_entry())))
        project.write_text(json.dumps(settings_with(third_party_entry(**{"async": True}))))

        findings = check_effective_settings(sources=[user, project])
        assert len(findings) == 1
        assert str(project) in findings[0].source

    def test_unreadable_source_warns_rather_than_raises(self, tmp_path):
        broken = tmp_path / "broken.json"
        broken.write_text("{not json")
        findings = check_effective_settings(sources=[broken])
        assert [f.code for f in findings] == ["settings_unreadable"]
        assert not findings[0].fatal


class TestResolveAnswerBudget:
    def test_defaults_when_unset(self):
        assert resolve_answer_budget({}) == DEFAULT_ANSWER_BUDGET_SECONDS

    def test_explicit_null_means_unbounded_hold(self):
        assert resolve_answer_budget({"answer_budget_seconds": None}) is None

    def test_explicit_value(self):
        assert resolve_answer_budget({"answer_budget_seconds": 30}) == 30.0

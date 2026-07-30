"""Guards against the two silent-ungating modes of the Claude Code hook governor.

Both modes were confirmed empirically, with controls, against Claude Code
2.1.220 on 2026-07-29. The evidence and the two governing rules are recorded in
``docs/adr/0012-remote-approval-on-the-hook-framework.md``.

**Mode 1 — async forfeits the vote.** A PreToolUse hook that returns an async
response (``"async": true``, or ``"asyncRewake": true``) is backgrounded and
never casts a permission verdict. The tool proceeds through the normal
permission flow — ungated. Verified with a control pair: a synchronous deny
hook blocked a tool through ``--allowedTools Bash``; the identical async
variant let it run. This is structural, not a race: ``executePreToolHooks``
omits ``forceSyncExecution``.

**Mode 2 — a killed hook is an abstaining hook.** When Claude Code kills a
PreToolUse command hook at its configured ``timeout``, the hook's would-be vote
is *discarded* and the call resolves through the remaining hooks and permission
rules. Verified with a control: the same slow-deny hook blocked the tool when
allowed to complete (timeout 60, deny at 30 s) and the tool *ran* when the hook
was killed mid-sleep (timeout 5). 600 s is only the platform *default* when no
per-hook ``timeout`` is set; a per-hook ``timeout`` raises it (a 660 s hold was
measured under ``timeout: 3600``).

Either way the governor looks healthy in logs and gates nothing. Hence the two
rules enforced here: **never go async on a gating hook**, and **never be
scheduled for death** — the registered timeout must comfortably exceed the
longest answer the hook client can produce.

Scope — this matters: these rules bind **PreToolUse**, the gating event, and
nothing else. ``asyncRewake`` on a **Stop** hook is a planned, legitimate Kaptn
feature (ADR-0012's message-injection idle leg: exit code 2 wakes an idle
session so a phone can reach a stopped session). A Stop hook casts no
permission verdict, so it has none to forfeit. Do not generalize the ban.
"""

import json
import logging
import math
import shlex
import sys
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

#: The one event whose hooks cast a permission verdict. Only these are guarded.
GATING_EVENT = "PreToolUse"

#: Settings keys that background a hook and thereby forfeit its vote.
ASYNC_KEYS = ("async", "asyncRewake")

#: Marks a hook entry as installed by Kaptn (matched against the command line).
HOOK_MARKER = "bridge.claude.hook_client"

#: What Claude Code kills a command hook at when no per-hook timeout is set.
PLATFORM_DEFAULT_TIMEOUT_SECONDS = 600

#: Longest answer bridge.claude.hook_client can currently produce (its own
#: request timeout). The margin is computed from this, never hardcoded.
DEFAULT_ANSWER_BUDGET_SECONDS = 5.0

#: Margin: the registered timeout must be at least this multiple of the answer
#: budget, and at least this many seconds above it.
MARGIN_FACTOR = 2.0
MIN_MARGIN_SECONDS = 5.0

#: What "effectively unbounded" means for ADR-0012 hold-until-answered, where
#: the client has no answer deadline at all (answer budget of None).
UNBOUNDED_HOLD_TIMEOUT_SECONDS = 86400

_ADR = "docs/adr/0012-remote-approval-on-the-hook-framework.md"

WHY_ASYNC = (
    "an async PreToolUse hook is backgrounded and FORFEITS its permission vote — "
    "the tool then proceeds through the normal permission flow, UNGATED. "
    "The governor still looks healthy in logs while gating nothing"
)

WHY_KILLED = (
    "a PreToolUse hook killed at its timeout is an ABSTAINING hook — its vote is "
    "discarded and the call resolves through the remaining hooks and permission "
    "rules, i.e. fail-open. A governor that can be killed before it answers is "
    "not a governor"
)


class HookGuardError(ValueError):
    """A hook configuration that would silently disable gating."""


@dataclass(frozen=True)
class Finding:
    """One problem found in an effective settings source.

    Attributes:
        severity: ``"error"`` for Kaptn's own gating hook (we know it is
            broken), ``"warning"`` for third-party hooks (we cannot know their
            answer time, so the call is advisory).
        code: Stable machine-readable identifier.
        source: Where the offending config lives.
        detail: Human-readable message including *why* it ungates.
    """

    severity: str
    code: str
    source: str
    detail: str

    @property
    def fatal(self) -> bool:
        """Whether this finding should stop setup/startup."""
        return self.severity == "error"

    def __str__(self) -> str:
        return f"[{self.code}] {self.source}: {self.detail}"


def resolve_answer_budget(claude_config: dict) -> float | None:
    """Read the hook client's answer budget from a Kaptn ``claude`` config.

    Args:
        claude_config: The ``claude`` section of kaptn.config.json.

    Returns:
        Seconds the hook client may take to answer, or None for an unbounded
        hold (ADR-0012 hold-until-answered — the client has no deadline).
    """
    if "answer_budget_seconds" not in claude_config:
        return DEFAULT_ANSWER_BUDGET_SECONDS
    value = claude_config["answer_budget_seconds"]
    return None if value is None else float(value)


def required_timeout(answer_budget: float | None) -> float:
    """The smallest registered hook timeout that keeps the hook from being killed.

    The margin scales with the budget rather than hardcoding today's 5 s / 10 s
    pair, so a configurable hold budget (ADR-0012) stays covered.

    Args:
        answer_budget: Longest answer the hook client can produce, or None for
            an unbounded hold.

    Returns:
        Required registered timeout, in seconds.

    Raises:
        ValueError: If the budget is zero or negative.
    """
    if answer_budget is None:
        return float(UNBOUNDED_HOLD_TIMEOUT_SECONDS)
    if answer_budget <= 0:
        raise ValueError(
            "answer_budget_seconds must be positive, or null for an unbounded hold"
        )
    return max(answer_budget * MARGIN_FACTOR, answer_budget + MIN_MARGIN_SECONDS)


def recommended_timeout(answer_budget: float | None) -> int:
    """The timeout to register for a given answer budget (rounded up)."""
    return int(math.ceil(required_timeout(answer_budget)))


def describe_budget(answer_budget: float | None) -> str:
    """Render an answer budget for error messages."""
    return "unbounded hold" if answer_budget is None else f"{answer_budget:g}s"


def is_kaptn_entry(entry: dict) -> bool:
    """Check whether a hook entry was installed by Kaptn."""
    return any(HOOK_MARKER in str(h.get("command", "")) for h in _hooks_of(entry))


def client_budget_from_command(command: str) -> tuple[bool, float | None]:
    """Extract the answer budget baked into a registered hook command.

    ``kaptn claude install`` writes ``--timeout <budget>`` into the command so
    the client's deadline and the registered hook timeout come from the same
    number. Reading it back means the margin is checked against what is
    *actually registered*, not against what config claims.

    Args:
        command: The registered command line.

    Returns:
        ``(found, budget)`` — ``found`` is False for entries installed before
        the budget was baked in (or hand-written ones); ``budget`` is None for
        an unbounded hold.
    """
    try:
        tokens = shlex.split(command)
    except ValueError:
        return (False, None)

    for index, token in enumerate(tokens):
        raw = None
        if token.startswith("--timeout="):
            raw = token.split("=", 1)[1]
        elif token == "--timeout" and index + 1 < len(tokens):
            raw = tokens[index + 1]
        if raw is None:
            continue
        if raw.strip().lower() in ("none", "unbounded", "hold", "0"):
            return (True, None)
        try:
            seconds = float(raw)
        except ValueError:
            return (False, None)
        return (True, None if seconds <= 0 else seconds)
    return (False, None)


def async_flags(obj: dict) -> list[str]:
    """Return the async-style keys set truthy on a hook or entry object."""
    return [key for key in ASYNC_KEYS if obj.get(key)]


def validate_gating_entry(entry: dict, *, source: str = "the gating hook entry") -> None:
    """Reject a PreToolUse entry that would forfeit its permission vote.

    Applies to PreToolUse entries only — callers must not pass Stop entries,
    where ``asyncRewake`` is legitimate (see the module docstring).

    Args:
        entry: A single ``hooks.PreToolUse[]`` entry.
        source: Label used in the error message.

    Raises:
        HookGuardError: If the entry or any of its hooks is async.
    """
    for obj in (entry, *_hooks_of(entry)):
        flags = async_flags(obj)
        if flags:
            keys = ", ".join(f'"{k}": true' for k in flags)
            raise HookGuardError(
                f"{source}: {keys} is not allowed on a {GATING_EVENT} hook — "
                f"{WHY_ASYNC}. (Legitimate on Stop hooks; forbidden here.) "
                f"See {_ADR}."
            )


def validate_gating_timeout(
    timeout: float | None,
    answer_budget: float | None = DEFAULT_ANSWER_BUDGET_SECONDS,
    *,
    source: str = "the gating hook entry",
) -> None:
    """Reject a registered timeout that leaves the governor killable.

    Args:
        timeout: The registered ``timeout``, or None if the entry omits it (in
            which case the platform default applies and is checked instead).
        answer_budget: Longest answer the hook client can produce; None for an
            unbounded hold.
        source: Label used in the error message.

    Raises:
        HookGuardError: If the effective timeout does not clear the margin.
    """
    required = required_timeout(answer_budget)
    effective = PLATFORM_DEFAULT_TIMEOUT_SECONDS if timeout is None else float(timeout)
    if effective >= required:
        return

    unset = "" if timeout is not None else (
        f" (no timeout registered, so Claude Code's {PLATFORM_DEFAULT_TIMEOUT_SECONDS}s "
        "default applies)"
    )
    raise HookGuardError(
        f"{source}: registered {GATING_EVENT} timeout {effective:g}s{unset} does not "
        f"clear the margin over the hook client's answer budget "
        f"({describe_budget(answer_budget)}); at least {required:g}s is required. "
        f"Why it matters: {WHY_KILLED}. See {_ADR}."
    )


def check_settings(
    settings: dict,
    *,
    source: str,
    answer_budget: float | None = DEFAULT_ANSWER_BUDGET_SECONDS,
) -> list[Finding]:
    """Audit every PreToolUse hook in one settings document.

    Kaptn's own gating hook is held to the full margin and its problems are
    errors. Third-party hooks are advisory: their answer time is unknowable, so
    the under-margin threshold is clamped to the platform default rather than
    to an unbounded hold budget — otherwise a hold-until-answered configuration
    would flag every third-party hook on the machine. Async third-party hooks
    are always reported: that one is structural, not a guess.

    Args:
        settings: A parsed settings.json document.
        source: Label identifying where it came from.
        answer_budget: The hook client's answer budget; None for unbounded.

    Returns:
        Findings, possibly empty.
    """
    findings: list[Finding] = []
    hooks = settings.get("hooks") if isinstance(settings, dict) else None
    entries = (hooks or {}).get(GATING_EVENT) if isinstance(hooks, dict) else None
    if not isinstance(entries, list):
        return findings

    strict = required_timeout(answer_budget)
    advisory = min(strict, float(PLATFORM_DEFAULT_TIMEOUT_SECONDS))

    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            continue
        mine = is_kaptn_entry(entry)
        owner = "Kaptn's" if mine else "A third-party"
        severity = "error" if mine else "warning"
        threshold = strict if mine else advisory

        for obj in (entry, *_hooks_of(entry)):
            flags = async_flags(obj)
            if flags:
                keys = ", ".join(f'"{k}": true' for k in flags)
                findings.append(Finding(
                    severity=severity,
                    code="pretooluse_async",
                    source=f"{source} [{GATING_EVENT}#{index}]",
                    detail=(
                        f"{owner} {GATING_EVENT} hook sets {keys} — {WHY_ASYNC}. "
                        f"Remove it (it stays legitimate on Stop hooks)."
                    ),
                ))

        for hook in _hooks_of(entry):
            if hook.get("type", "command") != "command":
                continue

            # For Kaptn's own hook, the budget baked into the registered
            # command is ground truth — config can claim anything.
            budget = answer_budget
            hook_threshold = threshold
            if mine:
                found, registered_budget = client_budget_from_command(
                    str(hook.get("command", ""))
                )
                if found:
                    budget = registered_budget
                    hook_threshold = required_timeout(budget)
                    if budget != answer_budget:
                        findings.append(Finding(
                            severity="warning",
                            code="answer_budget_drift",
                            source=f"{source} [{GATING_EVENT}#{index}]",
                            detail=(
                                f"the registered command answers within "
                                f"{describe_budget(budget)} but config says "
                                f"{describe_budget(answer_budget)}. The registered "
                                "value is what actually runs; re-run "
                                "'kaptn claude install' to bring them back in line."
                            ),
                        ))

            registered = hook.get("timeout")
            effective = (
                PLATFORM_DEFAULT_TIMEOUT_SECONDS if registered is None
                else _as_seconds(registered)
            )
            if effective is None or effective >= hook_threshold:
                continue
            findings.append(Finding(
                severity=severity,
                code="pretooluse_under_margin",
                source=f"{source} [{GATING_EVENT}#{index}]",
                detail=(
                    f"{owner} {GATING_EVENT} hook has an effective timeout of "
                    f"{effective:g}s, below the {hook_threshold:g}s margin"
                    + (
                        f" required for an answer budget of {describe_budget(budget)}"
                        if mine else
                        " (advisory — its answer time is unknown to Kaptn)"
                    )
                    + f". If it is killed first, {WHY_KILLED}."
                ),
            ))

    return findings


def effective_settings_sources(project: str | Path | None = None) -> list[Path]:
    """The settings files Claude Code actually merges, in precedence order.

    Note: hooks contributed by plugins or by ``--settings`` on the command line
    do not live in these files and are outside what this check can see.

    Args:
        project: Project directory for the project-scoped sources, or None to
            use the current working directory.

    Returns:
        Existing settings paths, lowest precedence first.
    """
    root = Path(project).expanduser() if project else Path.cwd()
    candidates = [
        _managed_settings_path(),
        Path.home() / ".claude" / "settings.json",
        root / ".claude" / "settings.json",
        root / ".claude" / "settings.local.json",
    ]
    return [p for p in candidates if p and p.is_file()]


def check_effective_settings(
    project: str | Path | None = None,
    answer_budget: float | None = DEFAULT_ANSWER_BUDGET_SECONDS,
    *,
    sources: list[Path] | None = None,
) -> list[Finding]:
    """Audit every PreToolUse hook across all effective settings sources.

    Unreadable or malformed sources produce a warning rather than an
    exception — a broken third-party file must not stop the governor.

    Args:
        project: Project directory, or None for the working directory.
        answer_budget: The hook client's answer budget; None for unbounded.
        sources: Explicit source list (mainly for tests).

    Returns:
        Findings across all sources.
    """
    findings: list[Finding] = []
    for path in (sources if sources is not None else effective_settings_sources(project)):
        try:
            settings = json.loads(Path(path).read_text())
        except (OSError, json.JSONDecodeError) as e:
            findings.append(Finding(
                severity="warning",
                code="settings_unreadable",
                source=str(path),
                detail=f"could not be read, so its {GATING_EVENT} hooks were not checked: {e}",
            ))
            continue
        findings.extend(check_settings(settings, source=str(path), answer_budget=answer_budget))
    return findings


def log_findings(findings: list[Finding], log: logging.Logger | None = None) -> None:
    """Log findings at a severity matching each one."""
    log = log or logger
    for finding in findings:
        if finding.fatal:
            log.error("Hook guard: %s", finding)
        else:
            log.warning("Hook guard: %s", finding)


def startup_self_check(
    project: str | Path | None = None,
    answer_budget: float | None = DEFAULT_ANSWER_BUDGET_SECONDS,
    *,
    sources: list[Path] | None = None,
    log: logging.Logger | None = None,
) -> list[Finding]:
    """Run the effective-settings audit and log it. Returns the findings.

    Callers decide what to do with fatal findings; the check itself never
    raises, so a hook-guard bug can never take down the bridge on its own.
    """
    findings = check_effective_settings(project, answer_budget, sources=sources)
    log_findings(findings, log)
    return findings


def _hooks_of(entry: dict) -> list[dict]:
    """The hook objects inside a settings entry, defensively typed."""
    hooks = entry.get("hooks") if isinstance(entry, dict) else None
    return [h for h in hooks if isinstance(h, dict)] if isinstance(hooks, list) else []


def _as_seconds(value: object) -> float | None:
    """Coerce a settings timeout to seconds, or None if it isn't a number."""
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _managed_settings_path() -> Path | None:
    """The enterprise-managed settings path for this platform, if any."""
    if sys.platform == "darwin":
        return Path("/Library/Application Support/ClaudeCode/managed-settings.json")
    if sys.platform.startswith("linux"):
        return Path("/etc/claude-code/managed-settings.json")
    if sys.platform.startswith("win"):
        return Path("C:/ProgramData/ClaudeCode/managed-settings.json")
    return None

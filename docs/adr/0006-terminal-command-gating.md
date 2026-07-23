# ADR-0006: Terminal command gating

- **Status:** Proposed
- **Date:** 2026-07-23
- **Deciders:** MicahAI
- **Supersedes / Superseded by:** —

## Context

`kaptn shell install` (v1.2.0) *audits* interactive shell commands via zsh
`preexec`/`precmd` — a flight recorder, never a gate. A natural extension:
actually *confirm* dangerous commands typed by a human (or a script) in
the terminal, using the same classifier and rules that govern Claude —
so a tired human's `rm -rf` gets the same friction an agent's would.

## Decision

**TBD.** Leading option: an opt-in `accept-line` widget that runs the
classifier on Enter and only prompts for dangerous categories
(delete / hard-reset / force-push), letting everything else through.

## Options considered

1. **zle `accept-line` wrapper (leading).** On Enter, hand the command to
   `kaptn check`; block + confirm only for high-risk categories. Pro:
   reuses the whole rule engine; opt-in; low friction if scoped to
   dangerous categories. Con: zsh-only; interactive top-level commands
   only; a determined user can bypass; must never wedge the shell.
2. **Audit-only (status quo).** Pro: zero friction, already shipped.
   Con: doesn't prevent anything.

## Consequences

- **Positive:** extends Kaptn's guardrails to the human's own shell;
  makes the deny-list concept shell-wide.
- **Negative / cost:** shell integration is delicate (a bug that blocks
  the prompt is unacceptable); coverage gaps (scripts, subshells, other
  shells) mean it's friction, not true enforcement — see ADR-0007.
- **Neutral:** shares the classifier with the Claude path.

## Open questions

- Which categories prompt by default (deletes only, or more)?
- Fail-open guarantee if `kaptn check` errors or is slow?
- bash/fish support, or zsh-only v1?

## References

- `kaptn/standalone/terminal_audit.py`, `kaptn/claude/tool_classifier.py`

# ADR-0005: Config-driven tool allowlist

- **Status:** Proposed
- **Date:** 2026-07-23
- **Deciders:** MicahAI
- **Supersedes / Superseded by:** —

## Context

Benign internal tools (`SendUserFile`, `ToolSearch`, `Monitor`, …) were
escalating as `unknown` and getting discovered one prompt at a time, each
fixed by editing `AGENT_TOOLS` in the classifier and shipping a plugin
release. That's slow and puts a user-specific preference inside product
code. The rule engine already supports `conditions.tool_names`, so a user
could own these decisions in `~/.kaptn/kaptn.config.json` without a
release.

## Decision

**TBD.** Leading option: ship a default `allow-internal-tools` rule keyed
on `tool_names`, documented so users extend it themselves; keep only
genuinely universal internal tools hard-coded in the classifier.

## Options considered

1. **Config rule with `tool_names` (leading).** e.g. a `tool_call` (or
   dedicated category) rule listing allowed tool names, user-editable.
   Pro: no release to add a tool; user owns their allowlist; effective
   immediately (config re-read per call). Con: two places tools can be
   allowed (classifier default + config) — needs clear precedence.
2. **Keep hard-coding in the classifier.** Pro: one source of truth.
   Con: every new tool = a release; product code holds user preference.
3. **Auto-learn:** offer to allowlist a tool after the user approves it N
   times. Pro: zero-friction. Con: surprising; risks silently widening
   the allowlist.

## Consequences

- **Positive:** users stop filing "allow this tool" one at a time;
  product code stays generic.
- **Negative / cost:** precedence rules between built-in and config
  allowlists must be unambiguous and documented.
- **Neutral:** reduces churn on `tool_classifier.py`.

## Open questions

- New `internal_tool` category, or reuse `tool_call`?
- Precedence: config overrides built-ins, or union?
- Ship a starter allowlist in `kaptn.config.example.json`?

## References

- `kaptn/claude/tool_classifier.py` (`AGENT_TOOLS`)
- `kaptn/autopilot/rule_evaluator.py` (`conditions.tool_names`)

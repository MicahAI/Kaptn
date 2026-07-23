# ADR-0003: Sensitive & external actions

- **Status:** Proposed
- **Date:** 2026-07-23
- **Deciders:** MicahAI
- **Supersedes / Superseded by:** —

## Context

Most of what an agent does is routine; the few actions worth catching —
writes *outside* the project, network egress, secret-file reads, package
installs, git pushes / external sends — are buried in the firehose. The
risk scorer (`kaptn/risk.py`) already flags several of these signals; we
have full commands and cwd. What's missing is a focused stream that
isolates "the stuff you'd actually want to know about."

## Decision

**TBD.** Leading option: a "Sensitive" dashboard tab + `kaptn log
--sensitive` that filters to a curated set of signal categories, each
labeled with *why* it's flagged.

## Options considered

1. **Signal-based filter over the audit (leading).** Reuse/extend the
   risk signals: egress (`curl|wget|nc`), secret paths (`.env`, keys,
   `.aws`), writes outside cwd/project, `pip/npm/brew install`, `git
   push` / `gh` / external MCP posts. Pro: builds on existing scoring.
   Con: heuristic; misses obfuscated cases; classifies, doesn't block.
2. **Dedicated "egress" tracking** parsing hosts from network commands
   to show *where* data went. Pro: high-value security signal.
   Con: command parsing is fiddly and easy to evade.

## Consequences

- **Positive:** turns the audit into a security-review surface; aligns
  with the broader "track how AI exposes systems" thesis.
- **Negative / cost:** advisory only (it reports, doesn't gate — gating
  is rules/hard_deny); false positives/negatives inherent to regex.
- **Neutral:** the flagged set is a natural source list for ADR-0004
  push alerts.

## Open questions

- Which signals ship in v1 vs. later?
- "Outside the project" needs a project-root notion — derive from cwd, or
  require config?
- Should some sensitive categories *default* to escalate rules, not just
  reporting?

## References

- `kaptn/risk.py` (signal patterns), `kaptn/dashboard/api.py`

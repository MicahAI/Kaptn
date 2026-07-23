# ADR-0002: Session story & live activity

- **Status:** Proposed
- **Date:** 2026-07-23
- **Deciders:** MicahAI
- **Supersedes / Superseded by:** —

## Context

The raw feed answers "what commands ran" but not "what is this session
*trying to do*." Users want a plain-English narration ("editing the
report generator in document-summarizer, ran the test suite, committed")
and a live indicator of whether a session is active, idle, or waiting on
a prompt. We already have per-session records with tool, category, path,
and timestamps.

## Decision

**TBD.** Leading option: a heuristic narrator (no LLM) that clusters a
session's recent actions by directory/tool/intent, plus an
active/idle/waiting status from record recency and unresolved
escalations.

## Options considered

1. **Heuristic narration (leading).** Group by working directory and
   tool; detect phases (reading → editing → testing → committing) from
   category/command patterns. Pro: stdlib, deterministic, cheap, offline.
   Con: coarse; won't capture true intent.
2. **LLM summarization.** Feed recent actions to a model for a real
   summary. Pro: genuinely readable. Con: adds a dependency/API key,
   cost, latency, and breaks the "stdlib, no-deps, offline" property that
   makes the plugin trivial to install.
3. **Hybrid.** Heuristic by default; optional LLM summary if the user
   configures a key.

## Consequences

- **Positive:** directly targets "I can't tell what it's doing."
- **Negative / cost:** heuristics can mislead; "waiting" is inferred
  (an unresolved escalation, per ADR context) not authoritative.
- **Neutral:** the live status feeds ADR-0004 (push alerts: "session
  waiting on you").

## Open questions

- Active/idle threshold (e.g. no records for N seconds = idle)?
- Is "waiting on you" reliable given we can't see prompt state directly
  (only unresolved escalations)?
- Keep it strictly stdlib, or allow an opt-in LLM summarizer?

## References

- `kaptn/dashboard/api.py` (`sessions`), `kaptn/labels.py`

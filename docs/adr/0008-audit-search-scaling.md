# ADR-0008: Audit search scaling (FTS)

- **Status:** Proposed
- **Date:** 2026-07-23
- **Deciders:** MicahAI
- **Supersedes / Superseded by:** —

## Context

`kaptn log` filters (`--grep`, `--min-risk`, storms, sessions, dashboard
aggregations) currently pull the most recent N records and filter/sort in
Python. That's instant at today's volume (~2k records), but terminal
audit and multi-session use could push the DB into six figures, where
full scans get slow and `--grep` misses anything older than the fetch
window.

## Decision

**TBD, not yet needed.** Leading option: add SQLite FTS5 over
`action_text` + `details`, plus indexes on `timestamp`/`decision`/
`category`, when volume warrants — a contained change to the audit layer.

## Options considered

1. **SQLite FTS5 + indexes (leading).** Virtual table for text search,
   B-tree indexes for filters. Pro: stays stdlib (sqlite3 ships FTS5);
   fast; search covers full history. Con: schema migration; index upkeep;
   slightly more write cost.
2. **Do nothing until it hurts.** Pro: no work. Con: silent degradation;
   `--grep` correctness gap (only searches the fetch window) exists
   *today*, not just at scale.
3. **External store (DuckDB, etc.).** Pro: analytics power. Con: breaks
   the zero-dependency promise.

## Consequences

- **Positive:** correct, fast search over the entire history regardless
  of size.
- **Negative / cost:** a migration for existing `~/.kaptn/kaptn_audit.db`
  files; keep FTS in sync on insert.
- **Neutral:** enables richer analytics (ADR-0002/0003) cheaply.

## Open questions

- Trigger threshold — build it now for correctness (`--grep` window bug),
  or wait for volume?
- Backfill FTS for existing rows on first upgrade?
- Retention/rotation policy for the audit DB independent of FTS?

## References

- `kaptn/audit/audit_logger.py`, `scripts/kaptn-ctl` (`cmd_log`)

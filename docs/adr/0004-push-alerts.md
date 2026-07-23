# ADR-0004: Push alerts

- **Status:** Proposed
- **Date:** 2026-07-23
- **Deciders:** MicahAI
- **Supersedes / Superseded by:** —

## Context

Watching the dashboard is optional; some events warrant a ping regardless
— a high-risk action, a pending escalation waiting on the user, a
sensitive/external action (ADR-0003), or a detected command storm. Kaptn
has no notification path today; everything is pull.

## Decision

**TBD.** Leading option: an opt-in notifier that watches the audit stream
and fires on configured triggers, via a pluggable sink (macOS
notification first).

## Options considered

1. **Local OS notification (leading).** A watcher process (or the running
   dashboard/daemon) tails new records and posts native notifications
   (`osascript`/`terminal-notifier` on macOS). Pro: no external service,
   no secrets. Con: only when a Kaptn process is running; local only.
2. **Webhook / chat sink.** POST to a user-provided URL (Slack, etc.).
   Pro: reaches the phone. Con: introduces an outbound network + secret
   (webhook URL) into a tool whose selling point is local & self-
   contained; needs careful consent.
3. **Reuse Claude Code's own notifications** (`agentPushNotifEnabled`)
   where possible, rather than a parallel channel.

## Consequences

- **Positive:** "you don't have to watch it" — the missing half of
  visibility.
- **Negative / cost:** needs a long-running watcher (the daemonless hook
  model has no persistent process by default); alert fatigue if triggers
  are too loose.
- **Neutral:** trigger definitions overlap with ADR-0002 (waiting) and
  ADR-0003 (sensitive) — share the signal layer.

## Open questions

- Where does the watcher live — the dashboard server, a new `kaptn watch`
  daemon, or a launchd agent?
- Default triggers (deny? escalation pending? risk ≥ N? storm?)?
- Rate-limiting / batching to avoid fatigue.

## References

- `kaptn/dashboard/server.py`, `kaptn/lifecycle.py` (launchd), ADR-0003

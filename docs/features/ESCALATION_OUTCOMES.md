# Escalation Outcomes — Feature Design

**Status**: Proposed (future enhancement — not yet implemented)
**Related**: [AUTOPILOT.md](AUTOPILOT.md) (deny-with-override semantics), [CLAUDE_CODE.md](CLAUDE_CODE.md) (hook adapter), [CONFIG.md](CONFIG.md)

## 1. Problem

In Claude Code hook mode, an `ask` decision (escalation or soft deny) is
fire-and-forget: Kaptn surfaces the permission prompt but never learns what
the user chose. The audit trail records AutoPilot's verdict (`deny`,
`escalate`) without the resolution, so `kaptn status` cannot distinguish
*escalation-approved* from *escalation-denied*, and
`reset_on_manual_approve` cannot work in hook mode at all (Kaptn never sees
the manual approve).

IDE/CDP mode does not have this gap — the driver watches the same dialog
the user clicks.

## 2. Signal available

Claude Code has no "permission denied" hook event. The observable contract:

- **Approved** → the tool executes → a **PostToolUse** hook fires. Direct
  evidence.
- **Denied** → the tool never runs → no event. Must be inferred from
  absence: a later PreToolUse in the same session (or SessionEnd) arrives
  while the escalation's PostToolUse never did.

So *approved* is stamped immediately; *denied* is stamped at the session's
next event; leftovers at session end are *unresolved/abandoned*.

## 3. Design

1. **Hook registration** (`bridge/claude/claude_setup.py`): install
   PostToolUse (matcher `*`) and SessionEnd entries alongside PreToolUse,
   pointing at the same hook client/server.
2. **Correlation** (`bridge/claude/claude_adapter.py`): when answering
   `ask`, stash a pending record — keyed by `tool_use_id` if present in the
   hook payload (verify; recent Claude Code versions include it), else by
   `(session_id, tool_name, hash(tool_input))` — holding the audit row id
   and timestamp.
   - PostToolUse matches a pending → **escalation-approved**.
   - Later PreToolUse for the session → older unmatched pendings for that
     session → **escalation-denied**.
   - SessionEnd → remaining pendings → **unresolved**.
   - TTL sweep for sessions that vanish without SessionEnd.
3. **Audit schema** (`bridge/audit`): add `resolution` + `resolved_at`
   columns (`ALTER TABLE` migration for existing DBs) and an
   `update_resolution(record_id, ...)` method. `kaptn status` tallies
   approved/denied/unresolved next to the existing counts.
4. **Parity win**: on escalation-approved, trigger the same
   `reset_on_manual_approve` limit-reset path the IDE mode uses.
5. **Tests**: correlation (approved, denied-by-next-event, abandoned),
   DB migration on an existing audit DB, setup writes all hook entries.

## 4. Accepted caveats

- Identical retried commands can mis-correlate without `tool_use_id` —
  confirming that field is the first implementation step.
- "Denied" timestamps lag until the next session event.
- A PostToolUse with an error response still counts as approved (the user
  let it run; it failed on its own).

## 5. Estimate

~200–300 lines plus tests. Tracked in GitHub issue #1.

# Remote Approval — Implementation Guide (ADR-0012)

**Status**: Ready to build · ADR: [0012](../adr/0012-remote-approval-on-the-hook-framework.md) (Accepted 2026-07-30)
**Scope**: hold-until-answered remote approval, presence-aware push, seamless
desk↔phone switching, and hook-channel message injection, for Claude Code
first, behind the `AgentChannel` seam.

## 0. Invariants (measured, do not violate)

These came from live probes against Claude Code 2.1.220 (2026-07-29) and
are the ground rules every phase inherits:

| # | Invariant | Why |
|---|---|---|
| I1 | The gating PreToolUse hook is **synchronous, always** | `async` forfeits the vote — tool runs ungated |
| I2 | The hook must **never be killed** — registered `timeout` effectively unbounded (86400), and Kaptn answers before any budget it sets itself | A killed hook abstains → fail-open toward the allowlist |
| I3 | Holds are real: 70 min measured; 600 s applies only when no `timeout` is set | Hold-until-answered is the primary semantic |
| I4 | The hook server (**:3002**) stays bound to `127.0.0.1` forever | It gates tool execution; remote surface is a separate server |
| I5 | Relayed captain messages are worthless without the SessionStart nonce briefing | A literal `[KAPTN-RELAY]` prefix was still challenged in probes |
| I6 | Journal every hold **before** pinging the phone | Bridge crash mid-hold loses the thread; the registry is the recovery |
| I7 | Push payloads carry no code, paths, or commands | APNs/Web Push is the only cloud touchpoint |

## 1. Architecture at a glance

```
Claude Code session ──PreToolUse──▶ hook_client ──HTTP──▶ hook_server :3002 (localhost only)
                                                              │
                                                        ClaudeAdapter
                                                              │ escalate?
                                                     PendingDecisionRegistry (SQLite)
                                                              │ hold (threading.Event)
                                       ┌──────────────────────┴───────────────┐
                                 answered locally                     remote server :3003
                                 (terminal / curl)                    (Tailscale IP, Bearer auth)
                                                                       ├─ REST: /pending /answer /events
                                                                       ├─ SSE stream → PWA
                                                                       └─ static PWA + Web Push
```

Two servers, deliberately:
- `bridge/claude/hook_server.py` (**:3002, localhost**) — the enforcement
  path. Untouched exposure-wise.
- `bridge/server/` (**:3003, Tailscale bind**) — the remote surface. New.
  Compromise of :3003 must never equal control of :3002's verdicts without
  a valid device token.

## 2. Phase 0 — Hold locally (no network exposure yet)

Everything here works with `curl localhost` before any phone exists.

### 0.1 Capture `tool_use_id`
`ClaudeAdapter.handle_hook_event` (`bridge/claude/claude_adapter.py`)
currently ignores `tool_use_id` (confirmed present in the 2.1.220 payload).
Read it into `details["tool_use_id"]`. It keys grants and resolution.

### 0.2 Pending-decision registry
New `bridge/decisions/registry.py` + SQLite table in the existing audit DB
(`bridge/audit/audit_logger.py` owns the connection; add a migration in
`_init_db` following the existing `ALTER TABLE` pattern):

```sql
CREATE TABLE IF NOT EXISTS pending_decisions (
  id TEXT PRIMARY KEY,          -- reuse the audit record id
  tool_use_id TEXT,
  session_id TEXT NOT NULL,
  window_name TEXT NOT NULL,
  created_at TEXT NOT NULL,
  state TEXT NOT NULL,          -- held | parked | answered | expired | crashed
  answer TEXT,                  -- allow | deny
  answered_at TEXT,
  answered_via TEXT,            -- terminal | pwa | recovered
  nonce TEXT                    -- session relay nonce (phase 4)
)
```

### 0.3 The hold, correctly threaded
**The critical concurrency rule**: `ClaudeAdapter` wraps evaluation in a
single `self._lock`. The hold MUST happen **outside** that lock —
evaluate + audit + journal under the lock, then wait on a per-decision
`threading.Event` after releasing it. Otherwise one held session freezes
every other session's hook evaluation on this machine.

Flow for `ESCALATE` (and soft-deny, which today maps to `ask`):
1. Under lock: evaluate, `audit.create_record`, insert `pending_decisions`
   row (state `held`) — I6.
2. Release lock. Notify escalation listeners (push, phase 3).
3. `event.wait(timeout=hold_budget)` — `hold_budget` from config
   (`kaptn.config.json`, new key `remote.hold_budget_seconds`, default
   very large; must stay under the registered hook timeout minus margin — I2).
4. Answered → return `allow`/`deny` with a reason naming who answered.
   Budget expiry → mark row `parked`, return the existing `ask` (Claude
   Code's local prompt — today's behavior becomes the degrade path).
5. `ThreadingHTTPServer` is thread-per-request, so concurrent holds are
   concurrent threads — verified fine at this scale.

Note an upgrade this buys: under `bypassPermissions` the adapter today
fails closed to a hard deny because `ask` would not prompt. A held
decision **works under bypassPermissions** — Kaptn returns the verdict
itself and never needs the prompt. Keep the fail-closed branch only for
the budget-expiry degrade.

### 0.4 Raise the two timeouts, deliberately
- `bridge/claude/hook_client.py`: `DEFAULT_TIMEOUT_SECONDS = 5.0` becomes
  hold-aware (budget + margin). Its fail-open (exit 0, no output) is
  **retained** — bridge down degrades to Claude Code's own prompt, which
  is the conservative posture ADR-0012 requires.
- `bridge/claude/claude_setup.py`: `DEFAULT_HOOK_TIMEOUT = 10` → 86400
  for the gating entry. The guard work (silent-ungating task) validates
  the margin between these two.

### 0.5 Local answer API (still :3002, localhost)
Extend `_HookHandler`: `GET /pending` (registry rows in state `held`),
`POST /answer {"id": ..., "decision": "allow"|"deny"}` → resolve row, set
Event. This gives `kaptn` CLI and the terminal a way to answer before any
PWA exists, and is the seam the remote server calls through.

### 0.6 Crash recovery bootstrap
On bridge startup: any `held` row older than the last server start →
state `crashed`. (Phase 4 turns answers to `crashed`/`parked` rows into
grants.)

**Phase 0 acceptance**: two concurrent headless sessions, one escalates
and holds, the other's tool calls flow un-delayed; `curl /answer`
releases the hold and the session continues; kill the bridge mid-hold →
session degrades to Claude Code's prompt (client fail-open), row lands
`crashed` on restart.

## 3. Phase 1 — Remote transport (Tailscale, no cloud)

### 1.1 Server: SSE + REST, stdlib-pure
Python stdlib has no WebSocket server. Rather than take the first
dependency, use **SSE (`text/event-stream`) + REST** — `http.server`
handles long-lived responses (thread per connection), and iOS Safari
supports `EventSource` in PWAs. WebSocket can come later behind the same
event bus if SSE proves limiting. Implement in `bridge/server/`
(currently an empty `__init__.py`):
- `GET /events` — SSE stream: pending-created, pending-answered,
  session-status, audit-appended
- `GET /pending`, `POST /answer` — proxy to the registry (same code path
  as 0.5; **never** proxy raw to :3002)
- `GET /catchup?since=<ts>` — replay from audit + registry for reconnects
  (the iOS ~30 s background disconnect answer, per DESIGN.md)

### 1.2 Bind + auth
Bind :3003 to the Tailscale interface IP only (config
`remote.bind_interface`, refuse 0.0.0.0 without an explicit override
flag). Tailscale is a network boundary, not identity (ADR-0012): add
device pairing — `kaptn pair` prints a QR (ASCII to terminal) containing
a one-time enrollment URL; the phone exchanges it for a long-lived device
token; every request carries `Authorization: Bearer`. Tokens hashed at
rest in the audit DB, revocable via `kaptn devices`.

**Phase 1 acceptance**: phone Safari over Tailscale lists pending and
answers one (401 without token); mid-hold answer from phone releases a
terminal session; catch-up replays events after airplane-mode toggle.

## 4. Phase 2 — PWA

Static app served by :3003 (no build pipeline if avoidable —
lit-html-free vanilla or a single-file preact; decision left to
implementation). Views, per ADR-0012 and DESIGN.md §2.3:
1. **Fleet list (home)** — sessions with status derived from audit
   recency + registry: `working` (records < 60 s), `holding on you`
   (held row), `idle`. This is ADR-0002's session story, minimum viable.
2. **Card detail** — command, path, risk, rule, session context;
   Approve / Deny.
3. **Audit log** — `get_recent` view.
Reconciliation: SSE `pending-answered` removes the card everywhere;
first answer wins (registry resolves races — `UPDATE ... WHERE state='held'`
returning rowcount decides the winner).

**Phase 2 acceptance**: add-to-home-screen; end-to-end phone approve;
race test (answer from both surfaces within 1 s — exactly one wins, both
UIs converge).

## 5. Phase 3 — Push + presence

### 3.1 Web Push
Requires HTTPS (iOS PWA push) → `tailscale cert` / `tailscale serve` for
the TLS endpoint, and VAPID + `pywebpush` — **the first real dependency;
make it an optional extra** (`pip install kaptn[push]`); without it,
:3003 works pull-only. Payload: `"approval needed"` + count. Nothing
else (I7).

### 3.2 Presence-aware routing (ADR-0012 decision 2)
Signals, cheapest first:
- HID idle: `ioreg -c IOHIDSystem` → `HIDIdleTime` (nanoseconds)
- Screen lock: `CGSessionCopyCurrentDictionary` (needs a helper; spike
  whether `python3 -c` with Quartz is available or shell out to
  `pmset -g assertions` heuristics)
- Recent local answer (`answered_via = terminal` in the last N min)
Routing: present → delay ping by `remote.grace_window_seconds`
(default 45), cancel if answered; away → ping immediately; risk ≥ 70 →
ping immediately regardless (config). Re-ping at 30 min / 4 h; quiet
hours; manual mute — all config keys under `remote.notify`.

**Phase 3 acceptance**: at-desk answer within grace → zero push; away →
push < 5 s after grace expiry; high-risk pings immediately; mute honored.

## 6. Phase 4 — Message injection + relay auth (ADR-0012 decision 4)

### 4.1 SessionStart nonce briefing
`claude_setup.py` today installs **only** the PreToolUse entry. Add a
SessionStart hook entry: emits the session policy plus
`[KAPTN-RELAY <nonce>]` briefing; the nonce (per session, random) is
stored on the registry keyed by `session_id`. I5: without this briefing,
stamped messages are challenged (measured).

### 4.2 Mid-turn delivery
Adapter change: on any PreToolUse evaluation, drain queued messages for
that `session_id` and attach as `additionalContext` (stamped) alongside
the permission decision. Measured: delivered; acted on once briefed.

### 4.3 Turn-boundary delivery
New **synchronous** Stop hook entry (same hook_client, `--event stop`):
if the queue is non-empty, respond `{"decision": "block", "reason":
"<stamped message>"}` — measured: delivered AND acted on. Empty queue →
no output (stop proceeds).

### 4.4 Idle delivery / rewake agent
Second Stop entry with `"asyncRewake": true`, `timeout` ≥ the long-poll
budget: backgrounds at idle, long-polls the registry for (a) queued
messages, (b) answers to `parked`/`crashed` decisions; on arrival prints
the stamped message to stderr and exits 2 → session wakes (measured:
~13 s to execution). Exits 0 at budget end; re-arms at the next Stop.
Two Stop entries coexist — Claude Code runs all matching hooks; the sync
one returns instantly.

### 4.5 Grants (recovery path)
Answering a `parked`/`crashed` card creates a one-shot grant
(tool + input hash + `session_id`, TTL `remote.grant_ttl_hours`,
default 24). Adapter checks grants **before** evaluation; match →
`allow` with provenance reason + consume (single `UPDATE` guards
double-spend). This also finally implements
[ESCALATION_OUTCOMES](ESCALATION_OUTCOMES.md) resolution stamping —
fold its `resolution` column work into the registry rather than building
the correlation heuristics it describes (holds make them unnecessary).

**Phase 4 acceptance**: nonce probe — briefed session acts on a stamped
message without challenge AND refuses an unstamped imitation; idle wake
end-to-end from a phone-queued message; crashed-hold answer → grant →
matching retry allowed exactly once.

## 7. Phase 5 — AgentChannel seam + CDP parity

Extract `AgentChannel` (new `bridge/channels/`): `pending()`,
`answer(id, decision)`, `send_message(session, text)`, `capabilities()`
(`authoritative`, `injection`, `interrupt`). `ClaudeAdapter` + registry
become `HookChannel` (authoritative, boundary-injection);
`WindsurfDriver` wraps as `CdpChannel` (observational, any-moment
injection). PWA renders the posture badge per ADR-0012's table. Do this
**after** the hook path works — extracting the interface from two
working implementations beats designing it from one.

## 8. Config surface (all new keys under `remote` in kaptn.config.json)

```
remote.enabled            false     master switch — nothing binds :3003 without it
remote.bind_interface     (unset)   Tailscale IP; refuses 0.0.0.0 unless forced
remote.hold_budget_seconds          hold before parking (default large; < hook timeout - margin)
remote.grace_window_seconds  45     presence delay before phone ping
remote.notify.*                     re-ping cadence, quiet hours, risk threshold
remote.grant_ttl_hours    24        recovery grant lifetime
```

## 9. Security checklist (gate for every phase)

- [ ] :3002 still binds 127.0.0.1 (grep-able assertion + test)
- [ ] :3003 refuses to start without `remote.enabled` + interface config
- [ ] Bearer required on every :3003 route incl. SSE; tokens revocable
- [ ] Push payload contains no command/path/code text
- [ ] Every remote answer and injected message lands in the audit log
      with `source=pwa` (`DecisionSource.PWA` already exists in
      `bridge/models.py`) and device identity
- [ ] Injected messages always stamped; nonce never logged to transcripts
      of other sessions
- [ ] Gating PreToolUse entry: sync, timeout 86400 (guard task enforces)

---

## Appendix A — Dry-run findings (2026-07-30)

Walked against the codebase at `main` (e2534c1). Gaps found and how the
guide absorbs them:

1. **Adapter lock would have serialized all sessions during a hold.**
   `ClaudeAdapter.handle_hook_event` does everything under `self._lock`.
   Guide 0.3 mandates hold-outside-lock. *(Would have been a ship-stopping
   bug if implemented naively.)*
2. **No stdlib WebSocket.** Original DESIGN.md assumed a WebSocket server;
   stdlib has none. Guide 1.1 switches v1 to SSE + REST (stdlib-pure),
   WebSocket deferred.
3. **`claude_setup.py` installs only PreToolUse.** SessionStart and both
   Stop entries (sync + asyncRewake) are new install-time work, and
   `hook_client.py` needs an `--event` mode to route non-PreToolUse
   events. Guide 4.1–4.4.
4. **`tool_use_id` is dropped today.** Present in the payload (measured)
   but never read. Guide 0.1.
5. **`EscalationHandler` has no answer path.** It fires listeners and
   accumulates `_pending` forever (`clear_pending` only). The registry
   (0.2) supersedes it as the source of truth; keep the listener
   mechanism as the push trigger, and drain `_pending` into the registry.
6. **Held threads die silently on bridge shutdown.** `ThreadingHTTPServer`
   uses daemon threads; `stop()` joins 5 s. Journal-before-hold (I6/0.6)
   plus client fail-open makes this safe — but only because 0.6 runs at
   startup; do not skip it.
7. **bypassPermissions interaction inverts.** Today would-be asks fail
   closed under bypass. A held decision needs no prompt, so holds work
   under bypass — but the **budget-expiry degrade** (`ask`) does not.
   Guide 0.3: expiry under bypass must fall back to hard deny (existing
   `fail_closed` branch), not `ask`.
8. **iOS push needs HTTPS.** Web Push in an iOS PWA requires a
   secure origin; plain `http://100.x.y.z:3003` gets pull-only. Guide 3.1
   routes through `tailscale cert`/`serve`. Without it, presence-aware
   *pull* still works; push does not.
9. **First dependency decision forced.** `pywebpush` (and VAPID key
   handling) cannot be stdlib'd realistically. Guide 3.1 makes push an
   optional extra so the core keeps the no-deps property.
10. **Rewake re-arm loop needs a state key change.** The probe hook fired
    once via a state file; production re-arms per Stop. The long-poll
    budget must be finite (else zombie pollers accumulate per session) —
    exit 0 and re-arm, per 4.4.
11. **Race on simultaneous answers** (terminal + phone): resolved at the
    registry with a conditional UPDATE, not in server code — guide §4
    (Phase 2 acceptance) requires the race test.
12. **Unverified externalities, unchanged from ADR**: 8 h holds
    (70 min measured), host sleep/wake mid-hold, interactive-session
    holds (pty harness exists: session scratchpad `rewake_probe.py`
    pattern), Quartz availability for screen-lock detection (3.2 marks
    it a spike).

Verdict: no contradiction found between ADR-0012 and the codebase; two
findings (1, 7) were genuine design traps the guide now pre-empts;
everything else is scoped work.

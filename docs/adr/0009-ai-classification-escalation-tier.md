# ADR-0009: AI classification escalation tier

- **Status:** Proposed
- **Date:** 2026-07-23
- **Deciders:** MicahAI
- **Supersedes / Superseded by:** —

## Context

The deterministic classifier (`kaptn/claude/tool_classifier.py`) is fast,
free, offline, auditable, and injection-proof — but it judges *syntax*,
not *intent*. Anything it can't positively recognize lands in `unknown`
and escalates to the user. Two costs follow:

1. **False prompts.** Benign-but-novel commands interrupt the user (the
   v1.10.1 quote-splitting bug was one class of this; a genuinely odd
   one-liner the enum has never seen is another).
2. **Missed intent.** An allowlist can't see that `curl … | sh`,
   base64-piped payloads, or a "rename" that is really a delete are
   dangerous *as a whole*, even when each token looks tame.

A small model (Haiku-class: sub-cent, few-hundred-ms) genuinely
understands command intent. The question is where it may sit in a
security gate whose input — the command text — is attacker-controllable.

## Decision

**TBD.** Leading option: a two-tier hybrid. Deterministic classifier
stays first and authoritative for everything it recognizes; only its
`unknown`/ambiguous residue falls through to an AI tier that classifies
intent — bounded by a deterministic hard floor the model can never
override. Off by default (opt-in config), cached, fail-safe to
deterministic behavior.

## Design (leading option)

- **Tier 1 — deterministic (always on).** Current classifier. Handles
  the ~95% instantly; also the only tier consulted when the AI tier is
  disabled, offline, unauthenticated, or times out. Fail safe, never
  fail open.
- **Hard floor (deterministic, non-overridable).** Deletes, secret-path
  access, `kaptn` self-reconfiguration, and rule `hard_deny` matches are
  decided *before* the AI tier and regardless of its verdict. This is
  the prompt-injection containment: text inside a command can talk to
  the model, but the model doesn't hold the pen on the dangerous floor.
- **Tier 2 — AI intent classification (opt-in).** Runs only on Tier-1
  `unknown`. The command is framed strictly as untrusted data; output is
  schema-constrained (category + one-line rationale, nothing else). The
  rationale is stored in the audit row and shown in the escalation
  prompt — AI verdicts are labeled as such (`source=ai`), never silently
  merged with rule decisions.
- **Cache by command hash.** Repeated commands (most of the firehose)
  never re-hit the model; cached verdicts make the common case
  deterministic-in-practice and nearly free.
- **Auth/provider paths** (config `ai_classifier.provider`):
  - `claude-cli` (default): shell out to `claude -p --model <small>`
    headless — rides the user's existing Claude Code login (subscription
    or API key), zero setup, ~1–3 s cold start. Must be invoked with
    tools disabled so the classifier call can neither act nor recurse
    into our own hook.
  - `api-key`: `ANTHROPIC_API_KEY` + stdlib `urllib` direct call —
    fastest, no CLI spawn; for users with Console keys.
  - `oauth-token`: `claude setup-token` long-lived token
    (`CLAUDE_CODE_OAUTH_TOKEN`) — the supported subscription-auth path
    for programmatic calls.
  - **Never** lift Claude Code's own stored OAuth token from the
    keychain — against usage terms, brittle, and a trust-boundary
    violation a governor cannot afford.
- **Config sketch** (`~/.kaptn/kaptn.config.json`):

  ```json
  "ai_classifier": {
    "enabled": false,
    "provider": "claude-cli",
    "model": "claude-haiku-4-5",
    "max_latency_ms": 4000,
    "cache": true
  }
  ```

  Model is Kaptn's choice (cheap/fast tier), not the session's — hooks
  don't receive the session model or credentials anyway.

## Options considered

1. **Hybrid escalation tier (leading).** AI judges only the residue,
   under a deterministic hard floor. Pro: kills most false prompts,
   catches composed-intent danger, keeps latency/cost on the novel tail,
   preserves offline/zero-config operation. Con: adds a network
   dependency and per-call billing when enabled; two code paths to test;
   verdicts on the residue are non-deterministic (mitigated by cache +
   audit rationale).
2. **AI classifies everything.** Pro: one path, maximal intent
   awareness. Con: latency on every tool call, cost scales with the
   firehose, whole gate becomes non-deterministic and injectable-in-
   principle, breaks stdlib-only/offline. Rejected.
3. **Deterministic only (status quo).** Pro: simplest, fully auditable.
   Con: permanent false-prompt tax on novel commands and permanent
   blindness to composed intent. Rejected as the end state; it remains
   the mandatory foundation and fallback.

## Consequences

- **Positive:** fewer spurious escalations; a real answer to "is this
  weird command actually dangerous?"; strengthens the product thesis
  (AI governing AI, with the trust boundary drawn honestly).
- **Negative / cost:** opt-in billing against the user's plan or key;
  `claude-cli` cold-start latency on cache misses; prompt-injection
  surface exists and must be contained by the hard floor + schema-
  constrained output + untrusted-data framing (and tested adversarially).
- **Neutral:** deterministic tier must stay high-quality regardless
  (v1.10.1's quote-aware splitting is a prerequisite of this design,
  not a competitor to it); AI verdict rationale becomes new audit
  content for the dashboard.

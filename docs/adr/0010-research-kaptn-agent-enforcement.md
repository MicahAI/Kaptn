# ADR-0010: Research — Kaptn agent enforcement surface

- **Status:** Research (idea scaffold — not a decision)
- **Date:** 2026-07-23
- **Deciders:** Wilson
- **Supersedes / Superseded by:** —

## Context

Kaptn v1.15.x proved the two-layer model on Claude Code: hard gates
(PreToolUse rule engine) plus advisory session policies (SessionStart
injection: NARRATE / PLAN GATE / CHECKPOINT), live-tested — a spawned
session presented a plan of attack and stopped for Accept/Deny.

But the governed surface is one platform, one session type:

- **Subagents** (Agent/Task spawns) inherit the tool-call gates but NOT
  the policy briefing — SessionStart never fires for them. They have the
  leash without the briefing.
- **Other agent platforms** (Devin, Cursor, Windsurf, Codex CLI, custom
  SDK agents) have no Kaptn presence at all. This repo's dual-backend
  history (Windsurf CDP) proves the core is adapter-shaped.
- Every platform integration we hand-build is a moving target; hook APIs
  differ and churn.

## Idea sketch

Grow the enforcement surface in three rings, cheapest first:

1. **Subagent briefing (small, near-term).** The PreToolUse hook already
   sees `Agent`/`Task` calls — inject the session policies into the
   subagent prompt on the way through. Governor briefs every agent it
   governs, automatically.
2. **Platform adapters (medium).** Port the Claude hook adapter pattern
   to 1–2 more platforms with real hook/extension points. Same engine,
   same audit DB, same dashboard; only the shim differs.
3. **MCP gateway (strategic).** A Kaptn MCP proxy: agents reach their
   tools *through* Kaptn, which classifies/gates/audits every call —
   platform-independent, hard enforcement at a chokepoint the whole
   industry is standardizing on. Governs any MCP-speaking agent with
   zero per-platform work.

## Open questions

- Subagent briefing: modify tool_input in PreToolUse (is it mutable in
  the hook response?) vs. wrap via permissionDecision feedback text.
- Gateway: transparent proxy of existing MCP servers vs. Kaptn-native
  tool registry; latency budget per call; how escalations surface in
  platforms with no prompt UI.
- Which second platform proves "adapter-shaped" best (Cursor? Codex)?
- Licensing tie-in: single-machine adapters stay in the free tier;
  gateway likely a paid/Fleet feature (see ADR-0011).

## Consequences (if pursued)

- Positive: Kaptn stops being "a Claude Code plugin" and becomes the
  governor for *agents*, plural — the actual product claim.
- Negative / cost: N adapters = N maintenance treadmills; the gateway
  adds a latency + availability dependency in the tool path.
- Neutral: forces the engine/adapter split to be formalized (good
  architecture pressure regardless).

# ADR-0011: Research — Kaptn Fleet (central team control plane)

- **Status:** Research (idea scaffold — not a decision)
- **Date:** 2026-07-23
- **Deciders:** Wilson
- **Supersedes / Superseded by:** —

## Context

Kaptn today is single-machine: local rules, local SQLite audit, local
dashboard. That's the right enforcement point (fast, offline-safe), but
a team of developers each running AI agents has questions no local
install can answer: what are *all* our agents doing, who reviewed what,
did policies actually change behavior, where is the risk concentrated?

The audit schema (decisions, categories, risk, escalation outcomes,
sessions, working sets) is already the right event shape for a fleet —
it just never leaves the laptop.

## Idea sketch

**Fleet = many local Kaptns + one control plane.**

- **Local stays authoritative for enforcement.** Decisions never wait on
  the network. A sync agent batches audit events upstream.
- **Central dashboard** = today's dashboard, org-wide: per-developer /
  per-AI rollups, deny & escalation rates, plan-gate compliance ("which
  sessions asked before big work"), riskiest sessions, bypass usage,
  delete attempts across the team.
- **Policy-as-code, pushed down.** Rules + session policies live in a
  central repo; every install pulls them. One edit gates every agent on
  the team.
- **Telemetry nobody else has:** "how often do our AIs attempt deletes,"
  "did the plan gate reduce silent bulk edits," per team, over time.
- **Audit/compliance export** for the org that needs to prove what its
  AI agents did (and didn't do).

## Business model (freemium — direction, not final)

- **Free: single client.** Local Kaptn — gates, policies, dashboard,
  audit — free for an individual machine. This is the top of funnel and
  the trust-builder; it must stay genuinely good.
- **Paid: Fleet (enterprise).** Central control plane, multi-user
  rollups, policy distribution, compliance export, SSO/roles.
  Per-seat or per-org.
- Repo posture: `MicahAI/Claude-Kaptn` flipped PRIVATE (2026-07-23)
  while licensing is decided; strategy/ADRs stay in this private repo
  regardless.

## Open questions

- Privacy tiers: ship decision metadata only by default; transcript-
  level detail (thinking, full inputs) opt-in per team policy. Where is
  the line, and who sets it?
- Tamper evidence, not DRM: a dev can disable a local hook — the
  server's job is noticing silence (heartbeats, expected-session gaps).
- Transport/store: start as simple as "Postgres + HTTPS batch POST"?
  Self-hosted vs. hosted-by-us (compliance buyers often want on-prem).
- Identity: map sessions → humans (SSO) vs. → machines; contractors?
- Does Fleet require the MCP gateway (ADR-0010 ring 3) for platforms
  without local hooks, or ship hooks-only first?
- Open-core licensing mechanics if the client re-opens later (BSL?
  AGPL core + commercial Fleet?).

## Consequences (if pursued)

- Positive: the defensible product — observability + governance for AI
  dev agents at team scale, riding data Kaptn already emits.
- Negative / cost: a real server product (auth, multi-tenancy, uptime,
  privacy posture) — a step-change in operational surface.
- Neutral: forces event-schema versioning and redaction discipline now,
  which the local product benefits from anyway.

# ADR-0007: OS-level enforcement

- **Status:** Proposed
- **Date:** 2026-07-23
- **Deciders:** MicahAI
- **Supersedes / Superseded by:** —

## Context

Kaptn's hooks and shell integration only see what opts in: Claude Code
tool calls and interactive top-level shell commands. Scripts, subprocess
trees, cron jobs, and other tools that exec directly are invisible. True
"nothing runs on this box without Kaptn seeing/gating it" requires
enforcement below the application layer.

## Decision

**TBD, and deliberately not soon.** This is a product of its own, not a
plugin feature. Recorded so the ambition is on the map without implying
it's near.

## Options considered

1. **macOS Endpoint Security framework.** Kernel-level exec/file events.
   Pro: comprehensive, tamper-resistant. Con: requires a signed system
   extension, entitlements from Apple, elevated trust, notarization — a
   major undertaking far outside the current stdlib-plugin model.
2. **exec shims / PATH interposition.** Wrap common binaries. Pro:
   lighter. Con: trivially bypassed (absolute paths, other shells),
   fragile, false sense of security.
3. **eBPF-style tracing (Linux).** Different OS, different lift.

## Consequences

- **Positive:** the only path to real, non-opt-in coverage; aligns with a
  security-product direction.
- **Negative / cost:** large engineering + trust/permission burden;
  changes Kaptn's identity from "trivially installable plugin" to
  "system security agent." Different distribution, support, and risk
  profile.
- **Neutral:** the audit/rule/risk core would be reused under a new
  capture layer.

## Open questions

- Is this Kaptn, or a separate product built on Kaptn's core?
- macOS-first (ESF) — what's the Linux/Windows story?
- Does the value justify the trust/permission cost for the target user?

## References

- ADR-0006 (the opt-in shell tier this would supersede for coverage)

# Architecture Decision Records

ADRs capture a decision, the context that forced it, and the consequences
we accept by making it — so future work (and future readers) understand
*why* Kaptn is shaped the way it is, not just *what* it does.

Each ADR is one file, numbered and immutable once **Accepted**. To change
a past decision, write a new ADR that supersedes it rather than editing
the old one.

## Status lifecycle

`Proposed` → `Accepted` → (later) `Superseded by ADR-NNNN` / `Deprecated`

The feature ADRs below are **Proposed** — scaffolds holding the thinking
so far. Fill in the Decision when we commit to building one.

## Index

| # | Title | Status |
|---|-------|--------|
| [0001](0001-files-changed-and-diffs.md) | Files changed + diffs view | Proposed |
| [0002](0002-session-story-and-activity.md) | Session story & live activity | Proposed |
| [0003](0003-sensitive-and-external-actions.md) | Sensitive & external actions | Proposed |
| [0004](0004-push-alerts.md) | Push alerts | Proposed |
| [0005](0005-config-driven-tool-allowlist.md) | Config-driven tool allowlist | Proposed |
| [0006](0006-terminal-command-gating.md) | Terminal command gating | Proposed |
| [0007](0007-os-level-enforcement.md) | OS-level enforcement | Proposed |
| [0008](0008-audit-search-scaling.md) | Audit search scaling (FTS) | Proposed |

New ADRs start from [`template.md`](template.md).

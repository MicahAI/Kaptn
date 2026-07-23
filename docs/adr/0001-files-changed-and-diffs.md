# ADR-0001: Files changed + diffs view

- **Status:** Proposed
- **Date:** 2026-07-23
- **Deciders:** MicahAI
- **Supersedes / Superseded by:** —

## Context

The Firehose shows every action, but a human asking "what did this agent
actually *do* to my code?" has to mentally reassemble it from dozens of
`Edit`/`Write` rows. Since v1.7.0 Kaptn stores the **full** tool input
(bounded 20k chars), so for `Write`/`Edit`/`MultiEdit` we already hold the
content and — for `Edit` — both `old_string` and `new_string`. The data
to show a real diff exists; nothing surfaces it.

## Decision

**TBD.** Leading option: a per-session "working set" view — files
created / edited / deleted, each expandable to the actual before→after
text — computed from the audit records, no git dependency.

## Options considered

1. **Reconstruct from audit `full` input (leading).** Group `file_write`/
   `file_delete` records by path per session; for `Edit` render
   old→new inline; for `Write` show content (created vs overwritten).
   Pro: works with data we already have, no git, works outside repos.
   Con: only captures changes Kaptn saw; not the on-disk final state;
   large files truncated at 20k.
2. **Shell out to `git diff` per file.** Pro: authoritative final diff.
   Con: only works inside a git repo, needs the working tree in a known
   state, races with concurrent sessions, misches non-repo edits.
3. **Snapshot files at hook time.** Copy each edited file's before/after
   into `~/.kaptn`. Pro: exact. Con: storage blowup, privacy surface,
   heavy for a daemonless per-call hook.

## Consequences

- **Positive:** the most literal answer to "what did it do"; diffs are
  the artifact reviewers actually want.
- **Negative / cost:** reconstruction ≠ ground truth (a later edit or a
  human change isn't reflected); truncation on huge writes; diff
  rendering in the dashboard is non-trivial UI.
- **Neutral:** pairs naturally with ADR-0002 (session story) — the story
  links to the diffs.

## Open questions

- Store a parsed `files_touched` index at write time, or compute on read?
- Redact secret-file contents (`.env`, keys) from stored diffs?
- Diff view in-dashboard vs. `kaptn diff <session>` CLI first?

## References

- `kaptn/claude/claude_adapter.py` (`_full_input`, 20k cap)
- `kaptn/dashboard/api.py` (`_details_fields`)

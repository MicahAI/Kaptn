# Configuration Reference

> Every key Kaptn reads, its real default, and the code that reads it.

**This is the factual reference.** [CONFIG.md](CONFIG.md) is the *design*
document and describes some behavior that was never built — where the two
disagree, this file wins. Verified against the code on 2026-07-30.

The governing rule: **a key that appears in `DEFAULT_CONFIG` is read by the
code.** Keys nothing reads have been removed rather than left to look
settable — a knob that silently does nothing is worse than an undocumented
one. If you add a key here, add the code that reads it in the same change.

Defaults live in `bridge/config/config_manager.py` (`DEFAULT_CONFIG`) and are
deep-merged under your `kaptn.config.json`, so an omitted key takes the
default and a partial config file is fine. A key set to `null` overrides the
default with `null` — that is meaningful for `logging.file`,
`autopilot.auto_reply_rules`, and `claude.answer_budget_seconds`.

---

## Top level

| Key | Default | Read by |
|---|---|---|
| `cdp_port` | `9222` | `main.py` (CDP discovery), `status_report.py`, `mcp/_bridge_worker.py` |
| `audit_db` | `"kaptn_audit.db"` | `main.py`, `standalone/runner.py`, `mcp/tools/tool_audit.py` |

A relative `audit_db` resolves against the config file's real directory, so
the CLI finds the same database from any working directory. `:memory:` is
honored for tests.

## `claude` — Claude Code hook governor

| Key | Default | Read by |
|---|---|---|
| `enabled` | `true` | `main.py` — whether the hook server starts |
| `hook_port` | `3002` | `main.py`, `claude/cli.py`, `status_report.py` |
| `launchd_label` | `"com.micahai.kaptn.claude"` | `main.py`, `status_report.py`, `lifecycle.py` |
| `answer_budget_seconds` | `5` | `claude/hook_guard.py` via `resolve_answer_budget` |

`answer_budget_seconds` is the longest the hook client may take to answer.
The registered PreToolUse timeout must clear a margin over it — a hook killed
mid-answer abstains, and abstaining fails open. `null` means an unbounded
hold (ADR-0012) and demands an effectively unbounded registered timeout.
See [CLAUDE_CODE.md](CLAUDE_CODE.md) and `bridge/claude/hook_guard.py`.

## `poll_intervals`

| Key | Default | Read by |
|---|---|---|
| `approvals` | `1.0` | `main.py` poll loop, `mcp/_bridge_worker.py` |

Only `approvals` exists. It doubles as a deliberate delay: raising it widens
the window to intervene manually before AutoPilot answers a dialog. Minimum
`0.5` when set via `kaptn_defaults_set`.

> `messages` and `status` were removed on 2026-07-30. They were shipped in
> the defaults and reported by `kaptn_defaults`, but no code ever read them.

## `autopilot`

| Key | Default | Read by |
|---|---|---|
| `enabled` | `true` | `main.py`, `standalone/runner.py` → `AutoPilotEngine` |
| `reset_on_manual_approve` | `true` | `main.py` — a manual approve clears that rule's limit counter |
| `default_watch_minutes` | `20` | `mcp/tools/tool_watch.py` — default duration for `kaptn_watch` |
| `auto_reply_rules` | `null` | `main.py` — `null` means the built-in `AutoReplyEngine` rules |
| `auto_reply_cooldown_seconds` | `10.0` | `main.py` → `AutoReplyEngine` |
| `auto_reply_max_consecutive` | `5` | `main.py` → `AutoReplyEngine` |
| `rules` | see below | `main.py`, `standalone/runner.py` → `RuleEvaluator` |
| `loop_detection` | see below | `main.py`, `standalone/runner.py` → `LoopDetector` |

Auto-reply is Windsurf/CDP-only; it has no effect in Claude Code hook mode.

### `autopilot.rules[]`

Evaluated in order, first match wins. Read by
`bridge/autopilot/rule_evaluator.py`.

| Field | Required | Notes |
|---|---|---|
| `id` | yes | Also the key for limit counters |
| `category` | yes | `file_read`, `file_write`, `file_delete`, `command_safe`, `command_unsafe`, `search`, `tool_call`, `unknown` |
| `action` | yes | `approve`, `deny`, `escalate` |
| `hard_deny` | no | Deny rules in Claude hook mode: `true` hard-blocks; default `false` surfaces an overridable prompt |
| `limits.max_per_session` | no | Counters are scoped per Claude session id / per CDP window name |
| `limits.max_per_minute` | no | |
| `limits.max_consecutive` | no | |
| `conditions.path_patterns` | no | |
| `conditions.exclude_patterns` | no | |
| `conditions.command_patterns` | no | Matched against the real command string |
| `conditions.tool_names` | no | |

Claude Code needs a `tool_call` rule to cover MCP and agent tools; without
one they escalate as `no_matching_rule`.

### `autopilot.loop_detection`

| Key | Default | Notes |
|---|---|---|
| `enabled` | `true` | `false` disables loop reporting; history is still tracked |
| `same_action_threshold` | `3` | Identical consecutive actions before flagging |
| `oscillation_threshold` | `3` | A→B→A→B alternations before flagging |
| `history_size` | `20` | Recent actions tracked |

> `enabled` was wired up on 2026-07-30. Before that it was shipped in the
> defaults and printed by `kaptn status`, but `LoopDetector` never received
> it — setting it `false` did nothing.

## `logging`

| Key | Default | Notes |
|---|---|---|
| `level` | `"INFO"` | `--log-level` on the CLI overrides it |
| `format` | `"console"` | `"json"` for structured stdout |
| `file` | `null` | Path for an additional file handler (always JSON) |
| `per_module` | `{}` | `{"bridge.cdp": "DEBUG"}` — module name → level |

Applied by `setup_logging_from_config` at the long-running entry points
(`kaptn start`, `kaptn claude serve`, `kaptn mcp start`). Short-lived
commands (`status`, `log`, `install`) pin their own level and ignore this
section deliberately.

> The whole block was inert before 2026-07-30: `setup_logging()` had exactly
> these four parameters, but no call site passed them from config.

---

## Removed keys

Removed on 2026-07-30 because nothing read them. Leaving them in place
implied they were settable.

| Key | Why it existed |
|---|---|
| `mode` | DESIGN.md §3 transport modes (`local`/`relay`/`cloud`) — the remote transport was never built (ADR-0012) |
| `bridge_port` | The WebSocket server in `bridge/server/`, still an empty stub |
| `ide` | Driver selection; drivers are chosen in code, not config |
| `poll_intervals.messages` | — |
| `poll_intervals.status` | — |

They are ignored if present in your config file — the deep merge simply
carries them through unread. Delete them.

## Not implemented

Described in [CONFIG.md](CONFIG.md) §5 but with no implementation anywhere:
per-window overrides (`windows`, `autopilot_profile`), the `permissive` /
`standard` / `strict` / `off` profiles, and per-mode overrides
(`mode_overrides`). Setting any of them has no effect.

## Runtime changes

`kaptn_defaults` reports the live config; `kaptn_defaults_set` modifies and
persists a subset (approval delay, `reset_on_manual_approve`, loop threshold,
per-rule action / `max_per_session` / `command_patterns`). See
[MCPServer.md](../MCPServer.md). Temporary MCP rules (`kaptn_watch`,
`kaptn_approve_category`) are in-memory and outrank static rules.

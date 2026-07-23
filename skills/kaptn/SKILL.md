---
name: kaptn
description: Understand and control Kaptn, the tool-approval AutoPilot governing this session. Use when a permission prompt mentions "Kaptn", when tool calls are being auto-approved/denied unexpectedly, when a session hits an approval cap (limit_exceeded), or when the user asks about approval rules, usage, or the audit trail.
---

# Kaptn — tool-approval AutoPilot

Every tool call in this session passes through Kaptn's PreToolUse hook,
which auto-approves, denies, or escalates it based on rules in
`~/.kaptn/kaptn.config.json`. Permission prompts whose reason mentions
"Kaptn" come from those rules, not from Claude Code itself.

## Controlling it

Run these with Bash (`$CLAUDE_PLUGIN_ROOT` is this plugin's directory;
the scripts are stdlib-only Python):

- `"$CLAUDE_PLUGIN_ROOT/scripts/kaptn-ctl" status` — rules, live per-session
  usage vs caps, audit totals
- `"$CLAUDE_PLUGIN_ROOT/scripts/kaptn-ctl" log -n 20` — recent decisions
- `"$CLAUDE_PLUGIN_ROOT/scripts/kaptn-ctl" reset` — clear limits/loop
  pauses (state-changing; if the session is capped this escalates to the
  user — that is intentional, suggest it rather than retrying)

If `kaptn` is on PATH (daemon-mode installs), `kaptn status` / `kaptn
reset` / `kaptn log` work too.

## Reading the prompts

- `limit_exceeded:max_per_session (N/N)` — this session used up its
  allowance for that rule. Tell the user; suggest a reset or a higher cap.
- `no_matching_rule` — the tool's category has no rule; recurring ones
  are fixed by adding a rule for that category to the config.
- `loop_detected` — the same action repeated enough times to trip the
  anti-runaway brake; the window pauses until reset.

## Config

`~/.kaptn/kaptn.config.json` — rules match categories (`file_read`,
`file_write`, `file_delete`, `command_safe`, `command_unsafe`, `search`,
`tool_call`, `unknown`) to actions (`approve` / `deny` / `escalate`),
with optional `limits` (`max_per_session`, `max_per_minute`,
`max_consecutive`) and `conditions` (path/command patterns). Limits are
per Claude session. Config changes take effect on the next tool call —
no restart needed in plugin mode.

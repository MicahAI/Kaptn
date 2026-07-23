# Claude Code Adapter

Kaptn supports Claude Code as a second approval source alongside the CDP
IDE drivers. Same rules, same limits, same loop detection, same audit DB —
different transport.

## How it differs from the CDP drivers

| | CDP drivers (Windsurf) | Claude adapter |
|---|---|---|
| Direction | Poll the DOM, click buttons | Claude pushes each tool call, waits for verdict |
| Data | Scraped button/context text | Structured tool name + full input |
| Classification | Keyword guessing | Deterministic (exact command/path) |
| Fragility | Breaks when the IDE UI changes | Stable hook contract |

## Architecture

```
Claude Code ──PreToolUse hook──► hook_client ──HTTP──► hook_server (127.0.0.1:3002)
                                                            │
                                                       ClaudeAdapter
                                                            │
                                              tool_classifier → ApprovalRequest
                                                            │
                                          AutoPilotEngine (shared rules/limits/loops)
                                                            │
                                                  audit DB + decision
                                                            │
Claude Code ◄── allow / deny / ask ◄────────────────────────┘
```

- **allow** — the tool call runs without prompting.
- **deny** — the tool call is blocked; the reason is shown to Claude.
- **ask** (escalate) — falls through to Claude Code's normal permission
  prompt. This is also the fail-open path: if the Kaptn server is down or
  times out, the hook client exits silently and Claude Code behaves as if
  Kaptn weren't installed. Kaptn can only ever *reduce* prompts, never
  silently expand what runs.

## Classification

`bridge/claude/tool_classifier.py` maps tool calls onto the existing
categories:

- `Read`/`NotebookRead` → `file_read`; `Write`/`Edit`/`MultiEdit`/`NotebookEdit` → `file_write`
- `Glob`/`Grep`/`WebSearch`/`WebFetch` → `search`
- `mcp__*` and agent tools (`Task`, `Skill`, …) → `tool_call`
- `Bash` commands are parsed per pipeline segment: `rm`/`rmdir`/`git clean`/
  `find -delete` etc. → `file_delete`; an allowlist (`ls`, `cat`, `git status`,
  …) → `command_safe`; everything else → `command_unsafe`. The most
  dangerous segment wins; `sudo` is never safe.
- Unrecognized tools → `unknown` (escalates under the default rules).

Rule `conditions` work as before: `path_patterns` match the real file path,
`command_patterns` match the real command string.

## Usage

```bash
# Register the PreToolUse hook in ~/.claude/settings.json (once)
kaptn claude install            # or --project <dir> for one project

# Run the decision server (either form)
kaptn claude serve              # Claude Code only, no CDP needed
kaptn start                     # CDP bridge + Claude hook server together

kaptn stop                      # stop everything (launchd agent + manual instances)
kaptn reset                     # clear rule limits / loop history / pauses on the running server
kaptn claude status             # is the hook server up?
kaptn claude uninstall          # remove the hook entry
kaptn log                       # audit trail (shared with CDP decisions)
```

## CLI from anywhere

The `kaptn` CLI resolves its config so it works from any directory:
`./kaptn.config.json` if present, else `$KAPTN_CONFIG`, else
`~/.kaptn/kaptn.config.json` (symlink this to your real config). A
relative `audit_db` resolves against the config file's real location, so
`kaptn log`/`kaptn status` always find the right database. Put the CLI on
PATH (e.g. `ln -s <kaptn>/.venv/bin/kaptn /opt/homebrew/bin/kaptn`) and
sessions themselves can run it — read-only subcommands (`status`, `help`,
`log`, `claude status`) classify as `command_safe`, so even a capped
session can self-diagnose. To make sessions Kaptn-aware, add a short
section to `~/.claude/CLAUDE.md` describing the commands.

## Limits are per session

Rule limits (`max_per_session`) are scoped per Claude session id — every
new Claude Code conversation gets a fresh allowance, and sessions never
drain each other's caps (CDP windows are scoped per window name the same
way). When a session does hit its cap, decisions escalate to normal
permission prompts; `kaptn reset` clears all counters for another batch.
Time-based caps are available via `max_per_minute` on any rule.

## launchd (start at login)

A user LaunchAgent (label `com.micahai.kaptn.claude`, configurable via
`claude.launchd_label`) can run `kaptn claude serve` at login with
KeepAlive. `kaptn stop` boots the agent out first — otherwise KeepAlive
would resurrect the process — then terminates any manual instances. The
agent returns at next login, or immediately via `launchctl bootstrap`.

Config lives under the `claude` key in `kaptn.config.json`:

```json
"claude": { "enabled": true, "hook_port": 3002 }
```

Audit records from Claude sessions use `mode="claude"`, window name
`claude:<project-dir>`, and the Claude session id as `tab_id`.

Note: rules need a `tool_call` category entry to cover MCP and agent
tools — without one they escalate as `no_matching_rule`.

## Known gaps

- `reset_on_manual_approve` has no Claude equivalent yet — the hook can't
  observe the user's answer to an escalated prompt. A PostToolUse hook
  could close this loop later.
- Auto-reply (conversational stalls) is Windsurf-only; Claude Code's Stop
  hooks would be the analogous mechanism.

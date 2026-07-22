# Kaptn MCP Server

> Expose AutoPilot as an MCP server so AI agents and users can dynamically control approval behavior through standard MCP tool calls.

---

## 1. Overview

The Kaptn MCP Server turns AutoPilot into a **conversational API**. Instead of static rules in `kaptn.config.json`, AI agents can request approval scopes on the fly — time-boxed, category-scoped, and with built-in alerting.

**Architecture: Subprocess Worker Pattern**

The MCP server (stdio transport) and the bridge (CDP connection) run as **separate OS processes**. They communicate via atomic JSON files — no shared memory, no blocking.

```
┌───────────────────────────────────────────────────┐
│  MCP Server Process (stdio transport)             │
│  ─ Tool handlers (kaptn_watch, kaptn_stop, etc.)   │
│  ─ ConfigManager (direct file access)              │
│  ─ AuditLogger (direct DB access)                  │
└───────────────────┬───────────┬───────────────────┘
             writes │           │ reads
       commands.json │           │ progress.json
             │      │           │      │
┌───────────────────┴───────────┴───────────────────┐
│  Bridge Worker Process (subprocess)                │
│  ─ CDP discovery + connection                      │
│  ─ Poll loop (approvals, messages, status)          │
│  ─ Graceful reconnect on CDP failure                │
│  ─ Reads commands.json each poll cycle               │
│  ─ Writes progress.json with status + windows        │
└───────────────────────────────────────────────────┘
                        │
                  CDP :9222
                        │
                   ┌────┴────┐
                   │   IDE    │
                   └─────────┘
```

**Flow:**
```
User (natural language) → AI Agent → MCP tool call → MCP Server → commands.json → Bridge Worker → IDE
```

**Example interaction:**
> User: "Kaptn, watch this window and auto-approve everything for 20 minutes. Alert me if you get stuck."
>
> Cascade calls: `kaptn_watch(window="Kaptn", minutes=20, alert_on_stuck=true)`
>
> Kaptn: creates a temporary rule set with a 20-minute TTL and enables stuck-detection alerts.

---

## 2. MCP Tools

### 2.1 `kaptn_watch`

Start monitoring a window with a time limit and optional category filter.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `window` | string | yes | Window name to monitor |
| `minutes` | int | no | Duration in minutes (max 480 = 8 hours). Defaults to `autopilot.default_watch_minutes` from config (default: 20). |
| `categories` | string[] | no | Categories to approve (default: all). Values: `file_read`, `file_write`, `file_delete`, `command_safe`, `command_unsafe`, `search`, `tool_call` |
| `alert_on_stuck` | bool | no | Alert user if loop detected or AutoPilot pauses (default: true) |

**Returns:** `{ session_id, window, expires_at, categories, status: "watching" }`

**Behavior:**
- Creates a temporary rule set with TTL
- Overrides static rules for the specified window
- When TTL expires, reverts to static rules and logs the expiry
- If `alert_on_stuck` is true, escalation events trigger a notification

### 2.2 `kaptn_approve_category`

Blanket approve a specific category for a duration.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `category` | string | yes | Category to approve |
| `minutes` | int | yes | Duration in minutes |
| `window` | string | no | Limit to a specific window (default: all windows) |
| `max_count` | int | no | Max approvals before auto-expiring (default: unlimited) |

**Returns:** `{ rule_id, category, expires_at, max_count, status: "active" }`

### 2.3 `kaptn_connect`

Connect (or reconnect) to the IDE by spawning the bridge subprocess.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `config` | string | no | Path to kaptn.config.json (uses default if omitted) |
| `log_level` | string | no | Bridge subprocess log level (default: INFO) |

**Returns:** `{ status: "started"|"already_running", pid, windows }` or `{ error }` if CDP unavailable.

**Behavior:**
- If bridge is already running, returns current status from progress file
- Otherwise spawns `_bridge_worker.py` as a detached subprocess (`start_new_session=True`)
- Bridge subprocess survives MCP server restarts
- Writes initial progress to `progress.json` immediately

### 2.4 `kaptn_stop`

Stop auto-approving a window, cancel a specific rule, or disconnect the bridge entirely.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `window` | string | no | Window to stop watching |
| `rule_id` | string | no | Specific temporary rule to cancel |
| `all` | bool | no | Stop all temporary rules (default: false) |
| `disconnect` | bool | no | Kill the bridge subprocess entirely (default: false) |

**Returns:** `{ status: "stopping" }` for rule stops, `{ status: "disconnected" }` for disconnect

### 2.5 `kaptn_status`

Get current bridge and AutoPilot state. Reads from the bridge subprocess progress file.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `window` | string | no | Filter to a specific window |

**Returns:**
```json
{
  "bridge": "running",
  "pid": 12345,
  "cdp_port": 9222,
  "windows": ["Kaptn", "TelemetryMCPV2"],
  "temp_rule_count": 2,
  "last_update_seconds_ago": 1.5
}
```

If the bridge is not running: `{ bridge: "not_running", message: "Use kaptn_connect..." }`
If progress is stale (>10s): includes a `warning` field
```

### 2.6 `kaptn_audit`

View recent approval decisions.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `limit` | int | no | Max records to return (default: 10) |
| `window` | string | no | Filter by window |
| `tab_id` | string | no | Filter by conversation tab |
| `category` | string | no | Filter by category |
| `decision` | string | no | Filter by decision: `approve`, `deny`, `escalate` |

**Returns:** Array of audit records with timestamp, window, category, action, decision, rule matched.

### 2.7 `kaptn_alert`

Configure alerting behavior.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `on_stuck` | bool | no | Alert when loop detected (default: true) |
| `on_limit` | bool | no | Alert when a limit is reached |
| `on_escalation` | bool | no | Alert when AutoPilot can't decide |
| `on_expiry` | bool | no | Alert when a watch session expires |
| `method` | string | no | Alert method: `log`, `notification`, `chat_inject` (default: `log`) |

**Returns:** `{ alerts_configured: {...} }`

### 2.8 `kaptn_resume`

Resume AutoPilot after it paused due to loop detection or escalation.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `window` | string | no | Resume a specific window |
| `all` | bool | no | Resume all paused windows |

**Returns:** `{ resumed: [...windows] }`

### 2.9 `kaptn_defaults`

View current AutoPilot configuration: rules, poll intervals, loop detection settings.

| Parameter | Type | Required | Description |
|---|---|---|---|
| *(none)* | | | Returns full config snapshot |

**Returns:**
```json
{
  "rules": [ { "id": "...", "category": "...", "action": "...", "limits": {}, "conditions": {} } ],
  "poll_intervals": { "approvals_seconds": 1.0, "messages_seconds": 2.0, "status_seconds": 5.0 },
  "autopilot_enabled": true,
  "default_watch_minutes": 20,
  "reset_on_manual_approve": true,
  "loop_detection": { "same_action_threshold": 3 },
  "config_file": "/path/to/kaptn.config.json"
}
```

### 2.10 `kaptn_defaults_set`

Modify AutoPilot configuration and persist to `kaptn.config.json`. See [features/CONFIG.md](features/CONFIG.md) Section 6 for full details.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `approval_delay_seconds` | float | no | Set approval poll interval (min 0.5) — controls auto-approve delay |
| `default_watch_minutes` | int | no | Default duration for `kaptn_watch` when minutes not specified (1-480) |
| `reset_on_manual_approve` | bool | no | Toggle manual-click limit reset |
| `loop_same_action_threshold` | int | no | Loop detection sensitivity (min 2) |
| `rule_id` | string | no | Target a specific rule for modification |
| `action` | string | no | New action for the rule: `approve`, `deny`, `escalate` |
| `max_per_session` | int | no | Set session limit on a rule (0 = remove limit) |
| `command_patterns` | string[] | no | Set command allowlist on a rule ([] = remove) |

**Returns:** `{ status: "updated", changes: [...], persisted: true, note: "Restart bridge..." }`

**Behavior:**
- Validates all inputs before applying (valid actions, threshold ranges, rule existence)
- Persists to `kaptn.config.json` on disk
- Bridge subprocess picks up config changes on next restart (`kaptn_stop disconnect=true` then `kaptn_connect`)

---

## 3. Temporary Rules

Temporary rules are the core mechanism. They layer on top of static rules from `kaptn.config.json`.

### 3.1 Rule Lifecycle

```
Created (via MCP tool) → Active → Expired (TTL) or Cancelled (via kaptn_stop)
                              ↓
                         Exhausted (max_count reached)
```

### 3.2 Precedence

1. **Temporary rules** (newest first) — checked before static rules
2. **Static rules** (from config) — fallback
3. **Default action** — escalate if nothing matches

### 3.3 Storage

- In-memory with TTL tracking (fast lookup)
- Persisted to audit DB for restart recovery (seeded on startup like fingerprints)
- Expired rules cleaned up on next poll cycle

### 3.4 Safety Constraints

| Constraint | Value | Rationale |
|---|---|---|
| Max TTL | 8 hours | Prevents runaway approval windows |
| Max concurrent watches | 10 | Prevents resource exhaustion |
| Max approvals per temp rule | Configurable, default unlimited | Rate limiting |
| Categories excluded by default | `file_delete` | Destructive actions require explicit opt-in |
| Loop detection | Always active | Cannot be disabled via MCP |

---

## 4. Architecture

### 4.1 Subprocess Worker Pattern

The MCP server and bridge run as **separate OS processes** to avoid blocking the MCP stdio transport with CDP I/O. Communication happens via two atomic JSON files:

| File | Direction | Contents |
|---|---|---|
| `bridge_progress.json` | Bridge → MCP | Running state, PID, CDP port, windows, errors, temp rules |
| `bridge_commands.json` | MCP → Bridge | Temp rule CRUD, resume/stop commands |

Files are located in `~/.kaptn/` and use atomic writes (`tempfile.mkstemp` + `os.replace`) to prevent partial reads.

```
┌─────────────────────────────────────────┐
│  MCP Server Process                     │
│  ─ Tool handlers (read/write JSON)       │
│  ─ ConfigManager (direct file I/O)        │
│  ─ AuditLogger (direct DB I/O)            │
└──────────────────┬──────────┬───────────┘
              writes │          │ reads
        commands.json │          │ progress.json
┌──────────────────┴──────────┴───────────┐
│  Bridge Worker (subprocess)              │
│  ─ CDP discovery + connect                │
│  ─ Poll loop + reconnect                  │
│  ─ AutoPilot (rules, limits, loops)        │
└───────────────────┬─────────────────────┘
                    CDP :9222
                 ┌────┴────┐
                 │   IDE    │
                 └─────────┘
```

### 4.2 Why Subprocess?

- **No blocking**: FastMCP runs its own `anyio` event loop for stdio. In-process async tasks risk blocking the transport.
- **Isolation**: Bridge crash doesn't take down the MCP server. MCP server restart doesn't kill the bridge (`start_new_session=True`).
- **Simplicity**: No shared memory, no locks. JSON files are the only interface.

### 4.3 Transport

- **stdio** — for local Windsurf/VS Code MCP integration (Cascade calls Kaptn directly)
- **HTTP/SSE** — planned for remote access (PWA, phone, cloud relay mode)

### 4.4 Modules

| Module | File | Responsibility |
|---|---|---|
| `mcp_server.py` | `bridge/mcp/mcp_server.py` | Server orchestration, tool registration, auto-connect |
| `_bridge_worker.py` | `bridge/mcp/_bridge_worker.py` | Subprocess: CDP connect, poll loop, reconnect |
| `_progress.py` | `bridge/mcp/_progress.py` | Atomic JSON read/write for IPC |
| `_state.py` | `bridge/mcp/_state.py` | Shared MCP server state (FastMCP instance, config) |
| `temp_rule_manager.py` | `bridge/autopilot/temp_rule_manager.py` | CRUD for temporary rules with TTL |
| `tools/*.py` | `bridge/mcp/tools/` | Individual MCP tool handlers |

---

## 5. Use Cases

### 5.1 "Auto-approve for 20 minutes"

```
User: "Kaptn, approve everything for the next 20 minutes"
→ kaptn_watch(window="Kaptn", minutes=20)
→ Creates temp rules for all categories, 20min TTL
→ After 20min: rules expire, reverts to static config, logs expiry
```

### 5.2 "Only approve file operations"

```
User: "Only auto-approve file reads and writes, skip everything else"
→ kaptn_approve_category("file_read", minutes=60)
→ kaptn_approve_category("file_write", minutes=60)
→ Commands still go through static rules (or escalate)
```

### 5.3 "Alert me if stuck"

```
User: "Go ahead but tell me if something goes wrong"
→ kaptn_watch(window="Kaptn", minutes=30, alert_on_stuck=true)
→ kaptn_alert(on_stuck=true, method="chat_inject")
→ If loop detected: Kaptn injects a message into Cascade chat
```

### 5.4 AI Agent Self-Management

```
Cascade (internally): "I need to run 5 npm commands for this task"
→ kaptn_approve_category("command_unsafe", minutes=5, max_count=5)
→ Auto-approves up to 5 commands, then expires
→ Cascade continues without user intervention
```

---

## 6. CLI Integration

The MCP server complements existing CLI commands:

```bash
kaptn mcp start              # Start MCP server + auto-connect bridge subprocess
kaptn mcp start --no-connect # Start MCP server only (connect later via kaptn_connect)
kaptn mcp start -l DEBUG     # Start with debug logging
```

The bridge subprocess is managed entirely through MCP tools:
- `kaptn_connect` — spawn bridge subprocess
- `kaptn_status` — check bridge health
- `kaptn_stop disconnect=true` — kill bridge subprocess

---

## 7. Security Considerations

- **TTL is mandatory** — no indefinite approval windows
- **`file_delete` excluded by default** — must be explicitly included in categories
- **Loop detection cannot be disabled** — even via MCP
- **All temporary rules are audited** — creation, activation, expiry, cancellation
- **Max TTL enforced server-side** — MCP client cannot override the 8-hour cap
- **Rate limiting** — max tool calls per minute to prevent abuse

---

## 8. Implementation Status

| Component | Status | Notes |
|---|---|---|
| `TempRuleManager` | ✅ Done | CRUD with TTL, integrated into `RuleEvaluator` |
| MCP server scaffold | ✅ Done | stdio transport, FastMCP, auto-connect |
| `_bridge_worker.py` | ✅ Done | Subprocess with CDP connect, poll, reconnect |
| `_progress.py` | ✅ Done | Atomic JSON IPC helpers |
| `kaptn_connect` | ✅ Done | Spawns bridge subprocess |
| `kaptn_watch` | ✅ Done | Writes commands to bridge via JSON |
| `kaptn_stop` | ✅ Done | Rule stop + disconnect (kill subprocess) |
| `kaptn_status` | ✅ Done | Reads from progress file |
| `kaptn_audit` | ✅ Done | Direct AuditLogger access |
| `kaptn_approve_category` | ✅ Done | Writes commands to bridge via JSON |
| `kaptn_resume` | ✅ Done | Writes commands to bridge via JSON |
| `kaptn_defaults` | ✅ Done | Direct ConfigManager access |
| `kaptn_defaults_set` | ✅ Done | Direct ConfigManager write + persist |
| `kaptn_alert` | ⏳ Planned | Alert routing to chat/notification |
| Unit tests | ✅ Done | 273 tests passing |
| Integration test | ✅ Done | TempRules → RuleEvaluator precedence |

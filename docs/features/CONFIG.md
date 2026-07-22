# Configuration — Feature Design

> Global defaults, per-window overrides, runtime modification via MCP, and persistence.

**Parent**: [DESIGN.md](../DESIGN.md) Section 10
**Related**: [AUTOPILOT.md](AUTOPILOT.md) (rules, limits, loop detection), [MCPServer.md](../MCPServer.md) (MCP tools)

---

## 1. Overview

Kaptn's behavior is driven by a single config file — `kaptn.config.json` — that lives at the project root. This file defines global defaults for everything: connection settings, poll intervals, AutoPilot rules, loop detection thresholds, and logging.

Configuration applies in layers:

```
kaptn.config.json (global defaults)
    ↓
Per-window overrides (different rules per workspace)
    ↓
Per-mode overrides (different rules for Plan vs Execute)
    ↓
MCP runtime changes (kaptn_defaults_set — persisted to config)
    ↓
Temporary MCP rules (kaptn_watch, kaptn_approve_category — in-memory, TTL-based)
```

Each layer narrows or overrides the one above. Static config is the foundation; MCP tools modify it at runtime.

---

## 2. Config File Structure

### 2.1 Full Schema

```json
{
  "mode": "local",
  "cdp_port": 9222,
  "bridge_port": 3001,
  "ide": "windsurf",
  "audit_db": "kaptn_audit.db",

  "poll_intervals": {
    "messages": 2.0,
    "approvals": 1.0,
    "status": 5.0
  },

  "autopilot": {
    "enabled": true,
    "reset_on_manual_approve": true,
    "rules": [ ... ],
    "loop_detection": {
      "enabled": true,
      "same_action_threshold": 3,
      "oscillation_threshold": 3,
      "history_size": 20
    }
  },

  "logging": {
    "level": "INFO",
    "format": "console",
    "file": null,
    "per_module": {}
  }
}
```

### 2.2 Section Breakdown

| Section | Purpose | Details |
|---|---|---|
| `mode` | Deployment mode | `local`, `direct`, `cloud` |
| `cdp_port` | Chrome DevTools Protocol port | Default `9222` |
| `bridge_port` | Bridge API/WebSocket port | Default `3001` |
| `ide` | Target IDE | `windsurf`, `vscode`, `cursor` |
| `audit_db` | Audit log database path | SQLite file |
| `poll_intervals` | How often the bridge checks for changes | See Section 3 |
| `autopilot` | AutoPilot rules, limits, loop detection | See Section 4 |
| `logging` | Log level, format, per-module overrides | Standard Python logging |

---

## 3. Poll Intervals

Poll intervals control how frequently the bridge checks the IDE DOM for different types of changes.

| Interval | Default | Purpose |
|---|---|---|
| `approvals` | 1.0s | Check for new approval dialogs. Most time-sensitive. |
| `messages` | 2.0s | Check for new AI messages in the chat panel. |
| `status` | 5.0s | Check IDE status (generating, idle, waiting). |

### 3.1 Approval Delay

The `approvals` interval doubles as a **delay mechanism**. Increasing it delays how quickly AutoPilot responds to approval dialogs. This is useful when you want AutoPilot active but with a brief window to manually intervene before auto-approval kicks in.

```
approvals: 1.0  → auto-approve within 1 second (default)
approvals: 3.0  → 3-second delay before auto-approve
approvals: 5.0  → 5-second window to manually intervene
```

Minimum value: `0.5` seconds. Can be changed at runtime via `kaptn_defaults_set`.

---

## 4. AutoPilot Defaults

### 4.1 Rules

Rules define what AutoPilot does with each type of approval. Evaluated in order — first match wins. See [AUTOPILOT.md](AUTOPILOT.md) Section 3 for full rule schema.

**Default rules in `kaptn.config.json`:**

| Rule ID | Category | Action | Limits |
|---|---|---|---|
| `allow-file-reads` | `file_read` | approve | — |
| `allow-file-writes` | `file_write` | approve | 50/session |
| `block-file-deletes` | `file_delete` | deny | — |
| `allow-safe-commands` | `command_safe` | approve | 100/session |
| `allow-unsafe-commands` | `command_unsafe` | approve | 20/session |
| `allow-search` | `search` | approve | — |
| `escalate-unknown` | `unknown` | escalate | — |

Each rule supports:
- **`action`**: `approve`, `deny`, or `escalate`
- **`limits`**: `max_per_session`, `max_per_minute`, `max_consecutive`
- **`conditions`**: `path_patterns`, `exclude_patterns`, `command_patterns`, `tool_names`

### 4.2 Loop Detection

Prevents the AI from getting stuck repeating the same action.

| Setting | Default | Description |
|---|---|---|
| `same_action_threshold` | 3 | Identical actions before flagging a loop |
| `oscillation_threshold` | 3 | A→B→A→B alternations before flagging |
| `history_size` | 20 | Number of recent actions to track |

### 4.3 Other Settings

| Setting | Default | Description |
|---|---|---|
| `reset_on_manual_approve` | `true` | When a user manually clicks approve on an escalated item, reset that rule's limit counter. This prevents a single limit-hit from permanently blocking a category. |

---

## 5. Per-Window Overrides

Global defaults apply to all IDE windows. Per-window overrides let you assign different profiles or rules per workspace.

```json
{
  "windows": {
    "default": {
      "autopilot_profile": "standard"
    },
    "overrides": {
      "Kaptn": {
        "autopilot_profile": "permissive"
      },
      "production-api": {
        "autopilot_profile": "strict"
      }
    }
  }
}
```

### 5.1 Override Cascade

```
Global defaults  →  Window override  →  Mode override
```

A workspace called `production-api` might use the `strict` profile (approve only reads and searches), while `Kaptn` uses `permissive` (approve almost everything).

### 5.2 Profiles

Pre-defined rule sets. See [AUTOPILOT.md](AUTOPILOT.md) Section 7 for full profile definitions.

| Profile | Philosophy |
|---|---|
| `permissive` | Approve almost everything. Personal projects. |
| `standard` | Approve common operations, escalate unusual ones. |
| `strict` | Approve only reads and searches. Everything else manual. |
| `off` | AutoPilot disabled. All approvals manual. |

### 5.3 Per-Mode Overrides

Within a window, rules can vary by AI mode (Plan vs Execute):

```json
{
  "mode_overrides": {
    "plan": { "autopilot_profile": "strict" },
    "execute": { "autopilot_profile": "standard" }
  }
}
```

---

## 6. Runtime Modification via MCP

The MCP server exposes two tools for viewing and modifying configuration at runtime. Changes apply immediately (hot-reload) and persist to `kaptn.config.json`.

### 6.1 `kaptn_defaults` — View Current Config

Returns a snapshot of the current configuration:

```json
{
  "rules": [ ... ],
  "poll_intervals": {
    "approvals_seconds": 1.0,
    "messages_seconds": 2.0,
    "status_seconds": 5.0
  },
  "autopilot_enabled": true,
  "reset_on_manual_approve": true,
  "loop_detection": {
    "same_action_threshold": 3
  },
  "config_file": "/path/to/kaptn.config.json"
}
```

Use this to inspect the current state before making changes.

### 6.2 `kaptn_defaults_set` — Modify Config

Modify one or more settings in a single call. All changes are validated before applying.

| Parameter | Type | Description |
|---|---|---|
| `approval_delay_seconds` | float | Set poll interval for approvals (min 0.5) |
| `reset_on_manual_approve` | bool | Toggle manual-click limit reset |
| `loop_same_action_threshold` | int | Loop detection sensitivity (min 2) |
| `rule_id` | string | Target a specific rule for modification |
| `action` | string | New action for the rule (`approve`, `deny`, `escalate`) |
| `max_per_session` | int | Set session limit (0 = remove limit) |
| `command_patterns` | string[] | Set command allowlist for a rule ([] = remove) |

**Returns:**
```json
{
  "status": "updated",
  "changes": [
    "approval_delay_seconds: 1.0 → 3.0",
    "rule allow-unsafe-commands: action escalate → approve"
  ],
  "persisted": true
}
```

### 6.3 Examples

**"Auto-approve with a 3-second delay"** — gives you a window to manually intervene:
```
kaptn_defaults_set(approval_delay_seconds=3.0)
```

**"Always auto-approve echo and sleep commands"** — add a command allowlist:
```
kaptn_defaults_set(rule_id="allow-unsafe-commands", command_patterns=["echo *", "sleep *", "ls *"])
```

**"Make loop detection less sensitive"** — increase threshold:
```
kaptn_defaults_set(loop_same_action_threshold=5)
```

**"Stop auto-approving unsafe commands"** — change a rule action:
```
kaptn_defaults_set(rule_id="allow-unsafe-commands", action="escalate")
```

**"Remove the session limit on file writes"** — set limit to 0:
```
kaptn_defaults_set(rule_id="allow-file-writes", max_per_session=0)
```

---

## 7. Persistence

### 7.1 How It Works

When `kaptn_defaults_set` modifies a setting:

1. **Validate** — check inputs (valid actions, threshold ranges, rule existence)
2. **Apply** — update the in-memory config and runtime objects (hot-reload)
3. **Persist** — write the full config dict back to `kaptn.config.json`

The `ConfigManager` handles file I/O. If no config file path is available, changes still apply to the running session but are not persisted (logged as a warning).

### 7.2 Hot-Reload

Changes take effect immediately without restarting the bridge:

- **Rules** — the `RuleEvaluator.rules` list is replaced in place
- **Poll intervals** — the bridge reads the config dict on each poll cycle
- **Loop detection** — the `LoopDetector.same_action_threshold` attribute is updated directly
- **Reset flag** — the `KaptnBridge._reset_on_manual` flag is updated directly

### 7.3 Config File Format

The file is written as pretty-printed JSON with 2-space indentation. The full config dict is written — not a partial patch — so the file always represents the complete state.

---

## 8. Static vs Dynamic Configuration

| Aspect | Static (config file) | Dynamic (MCP tools) |
|---|---|---|
| **When applied** | On bridge startup | At runtime, immediate |
| **Persistence** | Always on disk | Written to disk via `kaptn_defaults_set` |
| **Scope** | Global + per-window | Global (affects all windows) |
| **Temporary rules** | Not supported | Via `kaptn_watch`, `kaptn_approve_category` (in-memory, TTL) |
| **Use case** | Baseline behavior | Tune behavior during a session |

### 8.1 Precedence (Full Stack)

From highest to lowest priority:

1. **Temporary MCP rules** (`kaptn_watch`, `kaptn_approve_category`) — in-memory, expire on TTL
2. **Static rules** (from config) — persist across restarts
3. **Default action** — escalate if nothing matches

`kaptn_defaults_set` modifies the static rules layer. Temporary rules always take precedence over static rules. See [MCPServer.md](../MCPServer.md) Section 3.2.

---

## 9. Implementation

### 9.1 Key Classes

| Class | File | Role |
|---|---|---|
| `ConfigManager` | `bridge/config/config_manager.py` | Load, validate, save config |
| `RuleEvaluator` | `bridge/autopilot/rule_evaluator.py` | Evaluate rules against requests |
| `LoopDetector` | `bridge/autopilot/loop_detector.py` | Track action history, detect loops |
| `TempRuleManager` | `bridge/autopilot/temp_rule_manager.py` | CRUD for temporary MCP rules |

### 9.2 ConfigManager

```python
class ConfigManager:
    def __init__(self, config_path: str)
    def load(self) -> dict           # Read and parse config file
    def save(self, config: dict)     # Write config dict to disk
    @property
    def config_path(self) -> str     # Path to the config file
```

The MCP server holds a reference to the `ConfigManager` so it can persist changes made via `kaptn_defaults_set`.

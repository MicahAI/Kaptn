# AutoPilot — Feature Design

> Automatically approve AI tool calls based on configurable rules, limits, and context.

**Parent**: [DESIGN.md](../DESIGN.md) Section 5.1
**Priority**: v1 — first feature built
**Depends on**: CDP connection, IDE driver, approval monitor

---

## 1. What is AutoPilot?

AutoPilot watches for approval dialogs in the IDE's AI assistant panel and automatically clicks approve or deny based on user-defined rules. It runs on the bridge — no phone or PWA required.

### Why it matters

AI coding assistants constantly pause for approval: "Run this command?", "Edit this file?", "Search the web?". Each pause breaks flow. AutoPilot removes the friction — define what's allowed, and the AI keeps working.

### Key behaviors

- **Rule-based**: Approve/deny based on action type, file path patterns, command patterns
- **Limit-aware**: "Approve up to 10 file edits, then ask me" or "Approve up to $X in credits"
- **Loop detection**: If the AI repeats the same action 3+ times, pause and escalate
- **Escalation**: When a rule doesn't match or a limit is hit, escalate to the user (PWA push or just wait)
- **Mode-aware**: Different rules for Plan mode vs Execute mode
- **Audited**: Every decision logged with timestamp, action, rule matched, outcome

---

## 2. Approval Categories

Each AI tool call falls into a category. AutoPilot rules are defined per category.

### 2.1 Categories

| Category | Description | Risk | Examples |
|---|---|---|---|
| `file_read` | Reading file contents | Low | "Read file X" |
| `file_write` | Creating or editing files | Medium | "Edit file X", "Create file Y" |
| `file_delete` | Deleting files | High | "Delete file X" |
| `command_safe` | Commands marked safe by IDE | Low | `ls`, `cat`, `git status` |
| `command_unsafe` | Commands not marked safe | Medium-High | `npm install`, `rm`, `docker` |
| `search` | Searching codebase or web | Low | "Search for X", "Read URL" |
| `tool_call` | MCP tool invocations | Varies | Tool-specific |
| `unknown` | Unrecognized approval type | High | Fallback — always escalate |

### 2.2 Detection

AutoPilot detects the category by inspecting the approval dialog's DOM content:

- **Text patterns**: "Run command", "Edit file", "Create file", "Delete", "Search"
- **Context clues**: File paths, command text, tool names visible in the dialog
- **Button labels**: "Allow", "Run", "Accept", "Deny", "Cancel"

The IDE driver is responsible for parsing the approval dialog and returning a structured `ApprovalRequest`:

```python
@dataclass
class ApprovalRequest:
    category: str           # "file_write", "command_unsafe", etc.
    action: str             # The specific action text
    details: dict           # File path, command, tool name, etc.
    timestamp: datetime
    window_name: str        # Which workspace window
    mode: str               # "plan", "execute", "unknown"
```

---

## 3. Rules Engine

### 3.1 Rule Structure

Each rule matches a category and defines conditions and limits.

```json
{
  "rules": [
    {
      "id": "allow-file-writes",
      "category": "file_write",
      "action": "approve",
      "conditions": {
        "path_patterns": ["**/*.py", "**/*.ts", "**/*.md"],
        "exclude_patterns": ["**/node_modules/**", "**/.env*"]
      },
      "limits": {
        "max_per_session": 50,
        "max_per_minute": 10
      }
    },
    {
      "id": "allow-safe-commands",
      "category": "command_safe",
      "action": "approve",
      "limits": {
        "max_per_session": 100
      }
    },
    {
      "id": "block-deletions",
      "category": "file_delete",
      "action": "deny"
    },
    {
      "id": "escalate-unsafe-commands",
      "category": "command_unsafe",
      "action": "escalate",
      "conditions": {
        "command_patterns": ["rm *", "sudo *", "docker rm *"]
      }
    }
  ]
}
```

### 3.2 Rule Evaluation Order

1. Check rules in order (first match wins)
2. If a rule matches and limits are not exceeded → execute the action
3. If a rule matches but limits are exceeded → escalate
4. If no rule matches → escalate (safe default)
5. If category is `unknown` → always escalate

### 3.3 Actions

| Action | Behavior |
|---|---|
| `approve` | Click the approve button |
| `deny` | Click the deny button |
| `escalate` | Do nothing — wait for manual approval (PWA notification or user at desk) |
| `approve_n` | Approve the next N occurrences, then escalate |

### 3.4 Conditions

| Condition | Applies to | Description |
|---|---|---|
| `path_patterns` | `file_*` | Glob patterns for allowed file paths |
| `exclude_patterns` | `file_*` | Glob patterns for denied file paths |
| `command_patterns` | `command_*` | Glob patterns for command text |
| `tool_names` | `tool_call` | List of allowed MCP tool names |

---

## 4. Limits

Limits prevent runaway automation. When a limit is hit, AutoPilot escalates instead of approving.

### 4.1 Limit Types

| Limit | Description |
|---|---|
| `max_per_session` | Max approvals of this type per session (resets on bridge restart) |
| `max_per_minute` | Rate limit — max approvals per rolling 60-second window |
| `max_total_cost` | Credit/cost ceiling (for future billing integration) |
| `max_consecutive` | Max consecutive approvals of same action before pause |

### 4.2 Limit Behavior

When a limit is hit:
1. Log a WARNING with the limit details
2. Switch the rule's action to `escalate`
3. Send a push notification (if PWA connected): "AutoPilot paused — file edit limit reached (50/50)"
4. Wait for manual approval or limit reset

### 4.3 Limit Reset

- `max_per_session`: Resets on bridge restart or manual reset via CLI/PWA
- `max_per_minute`: Rolling window, auto-resets
- `max_consecutive`: Resets when a different action type occurs
- Manual reset: `kaptn autopilot reset-limits` or PWA button

---

## 5. Loop Detection

AI assistants sometimes get stuck in loops — repeating the same action, hitting the same error, or oscillating between two states.

### 5.1 Detection Strategy

Track the last N approval requests. Flag a loop when:

- **Same action repeated**: Identical action text 3+ times in a row
- **Same error pattern**: Approval followed by the same error 2+ times
- **Oscillation**: Alternating between two actions 3+ times (A→B→A→B→A)

### 5.2 Loop Response

When a loop is detected:

1. Log a WARNING with the loop pattern
2. Deny the current action (break the loop)
3. Send escalation to user: "Loop detected — Cascade is repeating: [action]. Denied."
4. Pause AutoPilot for this window until user manually resumes

### 5.3 Configuration

```json
{
  "loop_detection": {
    "enabled": true,
    "same_action_threshold": 3,
    "oscillation_threshold": 3,
    "history_size": 20,
    "pause_on_loop": true
  }
}
```

---

## 6. Escalation

When AutoPilot can't (or shouldn't) make a decision, it escalates.

### 6.1 Escalation Triggers

- No matching rule
- Limit exceeded
- Loop detected
- Category is `unknown`
- AutoPilot is paused or disabled

### 6.2 Escalation Behavior

| PWA Connected | Behavior |
|---|---|
| Yes | Send WebSocket event + push notification. Show approval card in PWA. |
| No | Do nothing — leave the approval dialog open. User handles it at the desk. |

### 6.3 Escalation Event

```python
@dataclass
class EscalationEvent:
    request: ApprovalRequest
    reason: str             # "no_matching_rule", "limit_exceeded", "loop_detected"
    rule_id: str | None     # Which rule triggered escalation (if any)
    limit_details: dict     # Current count vs limit
    timestamp: datetime
```

---

## 7. Profiles

Pre-defined rule sets for common scenarios. Users can switch profiles per workspace or per mode.

### 7.1 Built-in Profiles

**`permissive`** — Approve almost everything. For personal projects and experimentation.
```
file_read:     approve (no limit)
file_write:    approve (max 100/session)
file_delete:   escalate
command_safe:  approve (no limit)
command_unsafe: approve (max 20/session)
search:        approve (no limit)
unknown:       escalate
```

**`standard`** — Approve common operations. Escalate anything unusual.
```
file_read:     approve (no limit)
file_write:    approve (max 50/session, exclude .env*)
file_delete:   deny
command_safe:  approve (max 50/session)
command_unsafe: escalate
search:        approve (no limit)
unknown:       escalate
```

**`strict`** — Approve only reads and searches. Everything else requires manual approval.
```
file_read:     approve (no limit)
file_write:    escalate
file_delete:   deny
command_safe:  escalate
command_unsafe: deny
search:        approve (no limit)
unknown:       deny
```

**`off`** — AutoPilot disabled. All approvals require manual action.

### 7.2 Custom Profiles

Users can create custom profiles in the config file and assign them per workspace or per mode.

---

## 8. Mode-Aware Rules

Cascade has different modes (Plan, Execute, etc.). AutoPilot should behave differently depending on the mode.

### 8.1 Mode Detection

The bridge detects the current mode from the Cascade panel UI. Mode indicators in the DOM will be mapped during Phase 1 development.

### 8.2 Per-Mode Configuration

```json
{
  "windows": {
    "overrides": {
      "my-project": {
        "mode_overrides": {
          "plan": {
            "autopilot_profile": "strict"
          },
          "execute": {
            "autopilot_profile": "standard"
          }
        }
      }
    }
  }
}
```

---

## 9. Audit Integration

Every AutoPilot decision is logged to the audit system.

### 9.1 Audit Record

```python
@dataclass
class AuditRecord:
    id: str                 # UUID
    timestamp: datetime
    window_name: str
    mode: str
    request: ApprovalRequest
    decision: str           # "approved", "denied", "escalated"
    source: str             # "autopilot", "manual", "pwa"
    rule_id: str | None     # Which rule matched
    rule_action: str | None # What the rule said to do
    limit_status: dict      # Current counts at time of decision
    loop_detected: bool
```

### 9.2 Audit Queries

The audit log supports queries for:
- All decisions for a window/session
- Decisions by category
- Decisions by outcome (approved/denied/escalated)
- Loop detection events
- Limit exceeded events

---

## 10. CLI Interface

### 10.1 Commands

```bash
kaptn autopilot status          # Show current state, active profile, limits
kaptn autopilot enable          # Enable AutoPilot
kaptn autopilot disable         # Disable AutoPilot
kaptn autopilot profile <name>  # Switch to a profile
kaptn autopilot reset-limits    # Reset all limit counters
kaptn autopilot rules           # List all active rules
kaptn autopilot log             # Show recent audit log
kaptn autopilot log --loops     # Show only loop detection events
```

### 10.2 Example Session

```
$ kaptn start
[INFO] Connected to Windsurf on localhost:9222
[INFO] Found 2 windows: Kaptn, production-api
[INFO] AutoPilot: enabled (profile: standard)
[INFO] Listening for approvals...

[INFO] [Kaptn] file_write: bridge/cdp/cdp_connection.py → APPROVED (rule: allow-file-writes, 1/50)
[INFO] [Kaptn] command_safe: pytest tests/ → APPROVED (rule: allow-safe-commands, 1/100)
[INFO] [Kaptn] command_unsafe: npm install ws → ESCALATED (rule: escalate-unsafe-commands)
[WARN] [Kaptn] Loop detected: "Edit bridge/main.py" repeated 3 times → DENIED, AutoPilot paused
```

---

## 11. Implementation Plan

### Classes

| Class | File | Responsibility |
|---|---|---|
| `AutoPilotEngine` | `auto_pilot_engine.py` | Orchestrates rule evaluation, limits, loop detection |
| `RuleEvaluator` | `rule_evaluator.py` | Matches approval requests against rules |
| `LoopDetector` | `loop_detector.py` | Tracks action history, detects loops |
| `EscalationHandler` | `escalation_handler.py` | Routes escalations to PWA or logs |
| `ApprovalRequest` | (in models) | Dataclass for parsed approval data |
| `AuditRecord` | (in models) | Dataclass for audit entries |

### Dependencies

```
ApprovalMonitor → detects approval dialog in DOM
    ↓
IDE Driver → parses dialog into ApprovalRequest
    ↓
AutoPilotEngine → evaluates request
    ├── RuleEvaluator → matches rules
    ├── LoopDetector → checks for loops
    └── EscalationHandler → routes escalations
    ↓
AuditLogger → records decision
    ↓
IDE Driver → clicks approve/deny button (if not escalated)
```

---

## 12. Auto-Answer (Conversational Stall Detection)

AutoPilot handles approval **buttons** (Run/Skip). But the AI also stalls on conversational **questions** — "Should I proceed?", "Want me to continue?" — where there's no button to click.

**Auto-Answer** extends AutoPilot to detect these stalls and inject pre-configured replies. It uses the same firewall model: allow-rules at the top, block-all default at the bottom.

**See**: [AUTO_ANSWER.md](AUTO_ANSWER.md) for full design — patterns, safety rails, audit integration, and default rules.

---

## 13. Open Items

1. **Approval button DOM mapping**: Need to trigger approvals in Cascade and map the exact selectors. Blocked until Phase 1 development starts.
2. **Mode detection DOM mapping**: How does Cascade's mode (Plan/Execute) appear in the DOM?
3. **Credit/cost tracking**: Future feature — track API credit usage per approval for cost-aware limits.
4. **Model switching**: Future — automatically switch AI models based on task type (e.g., use cheaper model for simple file reads).
5. **Windsurf native auto-run**: Windsurf has a built-in auto-run system (Off/Allowlist/Auto/Turbo) for terminal commands. Kaptn could coordinate with it as a two-layer system — Windsurf handles commands natively, Kaptn handles everything else. See [AUTORUN.md](AUTORUN.md) for details.

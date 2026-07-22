# Auto-Answer — Feature Design

> Automatically respond to conversational stalls when the AI assistant asks routine questions during AutoPilot sessions.

**Parent**: [DESIGN.md](../DESIGN.md) Section 5.1 (AutoPilot)
**Priority**: v1 — extends AutoPilot
**Depends on**: AutoPilot, MutationObserver message capture, WindsurfDriver message injection

---

## 1. What is Auto-Answer?

When Cascade finishes generating and asks a question like "Should I proceed?" or "Do you want me to continue?", the session stalls — Cascade is idle, waiting for user input. AutoPilot handles approval buttons, but it doesn't handle conversational questions.

Auto-Answer fills this gap. It watches for idle stalls where the last CASCADE message matches a known prompt pattern, then injects a pre-configured reply.

### Why it matters

During unattended AutoPilot sessions, a single "Should I proceed?" question can block the entire workflow indefinitely. The user isn't at the desk — that's the whole point of AutoPilot. Auto-Answer keeps the session moving.

### Firewall model

Rules are evaluated **top-to-bottom, first match wins** — like a network firewall:

| Priority | Pattern | Reply | Description |
|----------|---------|-------|-------------|
| 1 (allow) | "Should I proceed" | "yes" | Common Cascade question |
| 2 (allow) | "Shall I continue" | "yes, continue" | Variation |
| 3 (allow) | "Ready to commit" | "yes" | Post-work question |
| 4 (allow) | "Want me to" | "yes" | Generic offer pattern |
| ... | *(user-configurable)* | ... | |
| **default** | everything else | **block** | Don't auto-answer unknown questions |

The default is always **block** — Auto-Answer only responds to explicitly allowed patterns. Unknown questions are left for the user.

---

## 2. Detection

Auto-Answer uses the MutationObserver message stream (same one that feeds `messages.log`) to detect conversational stalls.

### 2.1 Stall conditions (ALL must be true)

1. **Last observed message** is role `assistant` (CASCADE finished generating)
2. **Cascade status** is `idle` (not generating, not waiting for approval)
3. **No approval dialog** is visible (AutoPilot handles those)
4. **Message text** matches an allow-pattern (firewall match)
5. **Cooldown** has elapsed since last auto-answer (prevents rapid-fire)

### 2.2 Pattern matching

Patterns match against the **end** of the CASCADE message (the question part), case-insensitive. This avoids false matches on content earlier in the message.

```python
# Match: "...all tests pass. Should I proceed?"
# Match: "...ready. Want me to continue?"
# No match: "I proceeded with the refactor" (pattern is in past tense, mid-sentence)
```

Matching strategies:
- **Substring at end**: Last N characters of message contain the pattern
- **Regex**: For more complex patterns (optional, per-rule)

---

## 3. Rules

### 3.1 Rule structure

```json
{
  "autopilot": {
    "auto_reply_rules": [
      {
        "id": "proceed-yes",
        "pattern": "should I proceed",
        "reply": "yes",
        "match": "end",
        "enabled": true
      },
      {
        "id": "continue-yes",
        "pattern": "shall I continue|want me to continue|do you want me to",
        "reply": "yes, continue",
        "match": "end",
        "enabled": true
      },
      {
        "id": "commit-yes",
        "pattern": "ready to commit|should I commit",
        "reply": "yes",
        "match": "end",
        "enabled": true
      },
      {
        "id": "review-yes",
        "pattern": "want to review|should I review",
        "reply": "yes",
        "match": "end",
        "enabled": true
      }
    ]
  }
}
```

### 3.2 Rule fields

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | Unique rule identifier |
| `pattern` | string | Case-insensitive pattern to match. Pipe `\|` for alternatives. |
| `reply` | string | Text to inject into Cascade's chat input |
| `match` | string | `"end"` (match tail of message) or `"anywhere"` (match anywhere) |
| `enabled` | bool | Toggle individual rules on/off |

### 3.3 Evaluation order

1. Iterate rules in order (first match wins)
2. Skip disabled rules (`enabled: false`)
3. If a rule matches → inject reply, log to audit, reset cooldown
4. If no rule matches → block (do nothing, leave for user)

---

## 4. Safety Rails

Auto-Answer has strict safety mechanisms to prevent runaway automation.

### 4.1 Cooldown

A minimum interval between auto-answers prevents rapid-fire replies that could flood the conversation.

```json
{
  "autopilot": {
    "auto_reply_cooldown_seconds": 10
  }
}
```

### 4.2 Consecutive limit

Maximum number of consecutive auto-answers before pausing. If the AI keeps asking questions, something may be wrong.

```json
{
  "autopilot": {
    "auto_reply_max_consecutive": 5
  }
}
```

When the limit is hit:
1. Log a WARNING
2. Pause auto-reply for this window
3. Escalate to user (same as AutoPilot escalation)

### 4.3 Window scope

Auto-Answer only fires on windows with an active `kaptn_watch` session or where AutoPilot is enabled. It never fires on unwatched windows.

### 4.4 Idle verification

Before injecting a reply, Auto-Answer double-checks that Cascade is still idle. If Cascade started generating between detection and injection, the reply is suppressed.

---

## 5. Audit Integration

Every auto-answer is logged to the audit system with a distinct source.

```
Audit: AUTO_REPLY 'yes' (rule=proceed-yes, pattern='should I proceed', window='Kaptn')
```

### 5.1 Audit fields

| Field | Value |
|-------|-------|
| `category` | `auto_reply` |
| `action` | The injected reply text |
| `decision` | `approve` (always — block means no action) |
| `rule_id` | The matching rule's ID |
| `source` | `autopilot` |

### 5.2 Messages log

Auto-answers also appear in `messages.log` as USER messages (since the reply is injected as user input):

```
[2026-03-09 22:15:13.748] [Kaptn] CASCADE: All tests pass. Should I proceed?
[2026-03-09 22:15:24.006] [Kaptn] USER: yes
```

---

## 6. Relationship to AutoPilot

Auto-Answer is an **extension of AutoPilot**, not a replacement:

| Concern | AutoPilot | Auto-Answer |
|---------|-----------|-------------|
| **What it handles** | Approval buttons (Run/Skip) | Conversational questions |
| **Detection** | DOM button scanning | Observer message stream |
| **Action** | Click approve/deny | Inject text reply |
| **Rules** | Category + conditions + limits | Pattern + reply |
| **Default** | Escalate | Block (do nothing) |

Both share:
- Audit logging
- Loop/limit safeguards
- Window scoping via `kaptn_watch`
- Escalation when limits are hit

---

## 7. Implementation Plan

### Classes

| Class | File | Responsibility |
|-------|------|----------------|
| `AutoReplyRule` | `bridge/autopilot/auto_reply_rule.py` | Dataclass for a single rule |
| `AutoReplyEngine` | `bridge/autopilot/auto_reply_engine.py` | Evaluates rules against messages, manages cooldown/limits |

### Integration points

1. **Bridge poll loop** (`_bridge_worker.py`): After `_check_messages`, call `auto_reply_engine.check()`
2. **Observer drain** (`_check_messages`): Pass last assistant message to auto-reply engine
3. **WindsurfDriver.inject_message**: Already exists — used to send the reply
4. **AuditLogger**: Log auto-reply decisions
5. **Config**: `autopilot.auto_reply_rules` in `kaptn.config.json`

### MCP tools (future)

- `kaptn_defaults` — show current auto-reply rules
- `kaptn_defaults_set` — enable/disable rules, adjust cooldown

---

## 8. Default Rules

Ships with sensible defaults that cover common Cascade conversational patterns:

| ID | Pattern | Reply |
|----|---------|-------|
| `proceed-yes` | `should I proceed` | `yes` |
| `continue-yes` | `shall I continue\|want me to continue\|do you want me to` | `yes, continue` |
| `commit-yes` | `ready to commit\|should I commit` | `yes` |
| `review-yes` | `want to review\|want me to review` | `yes` |
| `discuss-yes` | `want to discuss\|shall we discuss` | `no, just implement it` |
| `update-docs-yes` | `update the documentation\|update docs` | `yes` |
| `update-tests-yes` | `update.*tests\|add.*tests` | `yes` |

All enabled by default. Users can disable or customize via config.

---

## 9. Open Items

1. **Pattern refinement**: The default patterns need real-world testing to avoid false positives. We should log matches for a few sessions before enabling auto-injection.
2. **Regex support**: Should patterns support full regex? Start with simple substring matching, add regex as an opt-in `match: "regex"` type.
3. **Per-window rules**: Different projects may need different auto-reply rules. Leverage existing per-window override system from CONFIG.md.
4. **MCP tool integration**: Add `kaptn_auto_reply` tool for AI agents to query/modify auto-reply rules at runtime.

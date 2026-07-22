# Time-Based Event Tracking

> Add time awareness to Kaptn's detection, deduplication, loop detection, and audit systems.

**Parent**: [DESIGN.md](../DESIGN.md)
**Related**: [AUTOPILOT.md](AUTOPILOT.md), [MCPServer.md](../MCPServer.md)
**Status**: Design — implementation decisions pending

---

## 1. Problem Statement

Kaptn currently deduplicates approvals using content-based fingerprints (tab UUID + type + action text). This is blind to time — it cannot distinguish between:

- A **stale approval** still sitting in the DOM from 30 seconds ago (should skip)
- A **new identical approval** that just appeared (should process)
- A **burst of approvals** fired in rapid succession (all new, should process each)

Without time awareness, Kaptn either re-processes stale approvals or misses legitimate new ones that happen to share a fingerprint with a previous approval.

---

## 2. Goals

1. **Know when something changed** — distinguish new DOM events from stale state
2. **Session lifecycle** — track when Kaptn starts/stops watching, for audit and metrics
3. **Time-aware deduplication** — use elapsed time as a signal alongside fingerprints
4. **Metrics foundation** — enable response time, throughput, and pattern analysis
5. **Smarter loop detection** — consider time gaps between repeated actions

---

## 3. Approach Options

### 3.1 Timestamp Tracking (Lightweight)

Track when Kaptn last acted on each window. Use elapsed time to inform dedup decisions.

**Data:**
- `last_action_time[window]` — when we last clicked approve/deny
- `last_detection_time[window]` — when we last saw an approval in the DOM

**Logic:**
| Same fingerprint? | Time since last action | Behavior |
|---|---|---|
| Yes | < N seconds | Skip — DOM hasn't refreshed yet |
| Yes | > N seconds | Possible new identical request — re-evaluate |
| No | Any | New approval — process immediately |

**Pros:** Simple, no new infrastructure
**Cons:** Still polling-based, threshold tuning required

### 3.2 DOM Mutation Observer (Event-Driven)

Inject a JavaScript `MutationObserver` via CDP that watches the Cascade panel for DOM changes. Only scan when something actually changed.

**Concept:**
```javascript
new MutationObserver((mutations) => {
    window.__kaptn_dom_changed = Date.now();
}).observe(cascadePanel, { childList: true, subtree: true });
```

Poll loop checks `__kaptn_dom_changed` instead of re-scanning the full DOM every cycle.

**Pros:** True "just happened" signal, lower CPU, no false stale detections
**Cons:** More complex setup, observer may fire on non-approval changes (scroll, animations)

### 3.3 CDP Event Subscription (Native)

Use CDP's built-in DOM events (`DOM.childNodeInserted`, `DOM.attributeModified`) to get notified of changes without polling.

**Pros:** Native protocol, no JS injection
**Cons:** Verbose events, need filtering, more complex CDP integration

### 3.4 Hybrid (Recommended)

Combine timestamp tracking with mutation observer:
- Mutation observer provides the "something changed" signal
- Timestamp tracking provides the "how long ago" context
- Polling remains as a fallback heartbeat (lower frequency when idle)

---

## 4. Session Tracking

### 4.1 Session Lifecycle

| Event | Trigger | Data |
|---|---|---|
| `session_start` | Bridge starts polling a window | window, tab_id, timestamp, config snapshot |
| `session_end` | Bridge stops (Ctrl+C, crash, window closed) | window, tab_id, timestamp, reason, stats |
| `session_pause` | AutoPilot paused (loop, limit) | window, reason, timestamp |
| `session_resume` | AutoPilot resumed | window, timestamp |

### 4.2 Storage

Option A: New `sessions` table in audit DB
```sql
CREATE TABLE sessions (
    id TEXT PRIMARY KEY,
    window_name TEXT NOT NULL,
    tab_id TEXT,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    end_reason TEXT,
    approvals_count INTEGER DEFAULT 0,
    denials_count INTEGER DEFAULT 0,
    escalations_count INTEGER DEFAULT 0
);
```

Option B: Session events as audit records with `category = 'session'`

### 4.3 Graceful Shutdown

Register signal handlers (SIGINT, SIGTERM) to write `session_end` records before exit. For crashes, use a heartbeat — if `last_heartbeat` is stale on next startup, mark the previous session as `end_reason = 'crash'`.

---

## 5. Metrics

Time-based tracking enables useful metrics:

### 5.1 Response Time
- Time from approval appearing to Kaptn clicking approve/deny
- Measures AutoPilot responsiveness

### 5.2 Throughput
- Approvals processed per minute/hour/session
- Burst detection: N approvals within M seconds

### 5.3 Idle Time
- Time between approvals — how active is the AI assistant?
- Long idle periods may indicate the AI is thinking, stuck, or user is away

### 5.4 Loop Timing
- Time gap between repeated actions
- Same action 3x in 5 seconds = burst (probably fine)
- Same action 3x over 2 minutes = possible loop

### 5.5 Session Duration
- How long Kaptn runs per session
- Uptime tracking for reliability

---

## 6. Impact on Existing Systems

### 6.1 Deduplication
- Currently: fingerprint-only
- Enhanced: fingerprint + time delta

### 6.2 Loop Detection
- Currently: action key repetition count
- Enhanced: action key + time window (rapid burst vs slow loop)

### 6.3 Audit Log
- Currently: per-decision records
- Enhanced: session records + per-decision records + timing metadata

### 6.4 Poll Loop
- Currently: fixed interval, always scans DOM
- Enhanced: event-driven scan on DOM change, idle mode when nothing happening

---

## 7. Implementation Decisions

> Decisions will be recorded here as they are made.

| # | Decision | Date | Notes |
|---|---|---|---|
| | | | |

---

## 8. Open Questions

1. What is the right time threshold for "same fingerprint, probably new"? 5s? 10s? Configurable?
2. Should the MutationObserver filter to only approval-relevant DOM subtrees?
3. How granular should session tracking be — per window, per tab, or per conversation?
4. Should metrics be exposed via CLI (`kaptn stats`) or only via audit DB queries?
5. How does time-aware detection interact with the MCP Server's time-boxed watches?

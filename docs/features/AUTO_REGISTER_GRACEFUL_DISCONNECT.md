# Auto-Register & Graceful Disconnect — Feature Design

> Automatically configure Windsurf for CDP access on first connect, and cleanly remove all injected JS when Kaptn disconnects or crashes.

**Parent**: [DESIGN.md](../DESIGN.md) Section 4 (CDP Bridge)
**Priority**: v1 — core reliability
**Depends on**: CDP Bridge, WindsurfDriver, MutationObserver

---

## 1. Problem

Two pain points affect the initial setup and ongoing reliability of Kaptn:

1. **Manual CDP setup**: Users must manually launch Windsurf with `--remote-debugging-port=9222` or know to edit `~/.windsurf/argv.json`. If they forget, `kaptn_connect` fails with a cryptic "CDP not available" error.

2. **Zombie JS after disconnect**: When Kaptn crashes, is killed, or the bridge subprocess dies, the MutationObserver and scroll-to-bottom behavior injected into the Windsurf DOM remain active indefinitely — burning CPU, firing into a dead message buffer, and scrolling the panel without reason.

---

## 2. Auto-Register

### 2.1 What it does

When `kaptn_connect` detects that CDP is unreachable, it automatically:

1. Checks if `~/.windsurf/argv.json` exists and contains `"remote-debugging-port"`
2. If missing, **patches the file in-place** to add the key (or creates it from scratch)
3. Returns a clear message: *"CDP remote debugging has been enabled. Please restart Windsurf."*

### 2.2 The argv.json file

Windsurf (like all Electron/VS Code apps) reads `argv.json` on startup for persistent CLI arguments. Location is platform-specific:

| Platform | Path |
|----------|------|
| macOS | `~/.windsurf/argv.json` |
| Windows | `%APPDATA%\Windsurf\argv.json` |
| Linux | `~/.windsurf/argv.json` |

The file uses **JSONC** format (JSON with `//` line comments). Kaptn's parser strips comments before parsing and patches the raw text in-place to preserve existing comments and formatting.

### 2.3 Patch strategy

```
Before:
{
    "enable-crash-reporter": true,
    "crash-reporter-id": "33317d9c-..."
}

After:
{
    "enable-crash-reporter": true,
    "crash-reporter-id": "33317d9c-...",

    // Enable CDP for Kaptn autopilot
    "remote-debugging-port": "9222"
}
```

- Finds the last `}` in the file
- Inserts a comma after the previous entry if needed
- Adds the `remote-debugging-port` key with a comment
- Preserves all existing content, comments, and formatting

### 2.4 Flow

```
kaptn_connect
    │
    ├─ Bridge spawns → CDP reachable? ─── YES → normal connect
    │
    └─ CDP not available
         │
         ├─ argv.json has port? ─── YES → "Port configured but Windsurf needs restart"
         │
         └─ argv.json missing port
              │
              ├─ File exists → patch in-place → "Restart Windsurf"
              └─ File missing → create new    → "Restart Windsurf"
```

### 2.5 Implementation

| File | Purpose |
|------|---------|
| `bridge/setup/windsurf_setup.py` | `check_cdp_configured()`, `configure_cdp()`, JSONC parser |
| `bridge/mcp/tools/tool_connect.py` | Calls setup on CDP failure, returns guidance |

---

## 3. Graceful Disconnect (Heartbeat Self-Cleanup)

### 3.1 What it does

Every piece of JS that Kaptn injects into the Windsurf DOM includes a **heartbeat timer** that self-destructs if the bridge stops communicating.

### 3.2 Heartbeat protocol

```
Bridge (Python)                    Windsurf DOM (JS)
    │                                    │
    ├─ poll loop (~1s) ────────────────► window.__kaptnHeartbeat = Date.now()
    │                                    │
    │                                    ├─ setInterval(check, 60s)
    │                                    │   ├─ heartbeat < 5 min old? → OK, reset pending
    │                                    │   ├─ heartbeat > 5 min old? → set __kaptnCleanupPending
    │                                    │   └─ pending > 5 min ago?   → CLEANUP
    │                                    │
    ├─ poll loop (~1s) ────────────────► window.__kaptnHeartbeat = Date.now()
    │                                    │   (pending cancelled — bridge is alive)
    │                                    │
    ✕ bridge dies                        │
                                         ├─ 60s check: heartbeat 5+ min stale → pending
                                         ├─ 60s check: still stale, grace period active
                                         ├─ ...
                                         └─ 60s check: pending 5+ min old → CLEANUP
```

### 3.3 Timing

| Phase | Duration | Purpose |
|-------|----------|---------|
| **Heartbeat ping** | Every ~1s | Bridge sets `window.__kaptnHeartbeat = Date.now()` |
| **Stale check** | Every 60s | JS compares `Date.now() - __kaptnHeartbeat` |
| **Stale threshold** | 5 minutes | Heartbeat must be >5 min old to be "stale" |
| **Grace period** | 5 minutes | After first stale detection, waits 5 more min |
| **Total worst case** | ~11 min | 5 min stale + 5 min grace + up to 1 min check interval |

### 3.4 What gets cleaned up

On self-destruct, the JS removes:

| Global | Purpose |
|--------|---------|
| `window.__kaptnObserver` | MutationObserver — `disconnect()` called first |
| `window.__kaptnMessages` | Message buffer array |
| `window.__kaptnConversationId` | Current conversation tab ID |
| `window.__kaptnHeartbeat` | Heartbeat timestamp |
| `window.__kaptnCleanupPending` | Grace period start time |
| `window.__kaptnCleanupTimer` | The cleanup `setInterval` itself — `clearInterval()` called |

After cleanup, the Windsurf DOM is exactly as it was before Kaptn connected.

### 3.5 Laptop sleep / resume

JS `setInterval` timers are **suspended** during macOS sleep. On wake:

1. The cleanup timer fires and sees a stale heartbeat (hours old)
2. It sets `__kaptnCleanupPending` (starts 5-min grace period)
3. The bridge poll loop **also resumes** and sends a heartbeat within ~1s
4. Next cleanup check sees a fresh heartbeat → cancels pending cleanup

The 5-minute grace period ensures the bridge always wins the race after wake.

### 3.6 Implementation

| File | Purpose |
|------|---------|
| `bridge/drivers/windsurf_driver.py` | Cleanup timer in observer JS, `send_heartbeat()`, `get_observer_status()`, `trigger_cleanup_check()` |
| `bridge/mcp/_bridge_worker.py` | Calls `driver.send_heartbeat()` each poll cycle |

---

## 4. Testing

### 4.1 Auto-Register tests (12 tests)

| Test | What it verifies |
|------|------------------|
| JSONC parser strips comments | `_read_jsonc()` handles `//` line comments |
| JSONC preserves raw text | Raw text returned for in-place patching |
| Check configured — port present | `check_cdp_configured()` detects existing port |
| Check configured — port missing | Returns `configured: False` |
| Check configured — file missing | Returns `file_exists: False` |
| Check configured — with comments | Parses real JSONC format |
| Configure — already configured | Returns `already_configured`, no file change |
| Configure — patches existing | Inserts key before closing brace |
| Configure — creates new file | Creates parent dirs + minimal argv.json |
| Configure — custom port | Writes specified port number |
| Configure — real Windsurf format | Tests against actual `argv.json` format with all comments |

### 4.2 Heartbeat cleanup tests (13 tests)

| Test | What it verifies |
|------|------------------|
| `send_heartbeat` sends correct JS | Evaluates `__kaptnHeartbeat = Date.now()` |
| `send_heartbeat` returns false on failure | Handles None from evaluator |
| `get_observer_status` returns dict | Installed state, age, globals |
| `get_observer_status` defaults on failure | Graceful fallback |
| `get_observer_status` no observer | Empty globals |
| `trigger_cleanup_check` — fresh | `action: "fresh"` when heartbeat is recent |
| `trigger_cleanup_check` — stale pending | `action: "stale_pending"` on first stale |
| `trigger_cleanup_check` — grace waiting | `action: "grace_waiting"` during grace |
| `trigger_cleanup_check` — cleaned | `action: "cleaned"` after grace expires |
| `trigger_cleanup_check` — error | Handles evaluator failure |
| `trigger_cleanup_check` — custom thresholds | Verifies `stale_ms`/`grace_ms` injected into JS |
| Observer JS has heartbeat init | Verifies `__kaptnHeartbeat = Date.now()` in install JS |
| Observer JS clears previous timer | Verifies `clearInterval` on reinstall |

### 4.3 Integration test (manual, requires live Windsurf)

A commented-out integration test in `test_heartbeat_cleanup.py` can be run against a live CDP connection to verify the full lifecycle: install → heartbeat → trigger cleanup → verify globals removed.

---

## 5. Design Decisions

| # | Decision | Rationale |
|---|----------|-----------|
| 1 | Patch argv.json in-place, don't rewrite | Preserves user's comments, formatting, and other settings. Minimal diff. |
| 2 | JSONC parser strips `//` comments | `argv.json` uses JSONC format. Python's `json` module can't parse comments natively. Regex strip is good enough for line comments. |
| 3 | 5-min stale + 5-min grace | Long enough that sleep/resume never triggers false cleanup. Short enough that zombie JS dies within ~11 min. |
| 4 | Heartbeat on every poll cycle (~1s) | Cheap operation (single JS assignment). Ensures the heartbeat is always fresh as long as the bridge is running. |
| 5 | Grace period resets on fresh heartbeat | Prevents false cleanup after sleep/resume or momentary network hiccups. |
| 6 | Cleanup deletes all `__kaptn*` globals | Leaves zero footprint in the DOM after disconnect. Windsurf is exactly as before Kaptn connected. |
| 7 | `trigger_cleanup_check(stale_ms, grace_ms)` for testing | Allows unit tests to verify the full cleanup lifecycle without waiting 10+ minutes. Custom thresholds injected into the JS. |
| 8 | Auto-configure on connect failure, not proactively | Only touches argv.json when the user explicitly tries to connect. No surprise file modifications. |

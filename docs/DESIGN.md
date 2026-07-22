# Kaptn — Design Document

> Remote command and control for AI coding assistants. Start local, scale to cloud.

**Status**: Design
**Research**: See [KaptnResearch.md](../KaptnResearch.md) for investigation notes, protocol analysis, and DOM selector mapping.

---

## 1. What is Kaptn?

Kaptn is a bridge between AI-powered IDEs and the outside world. It connects to an IDE via Chrome DevTools Protocol (CDP), reads AI assistant conversations in real-time, and enables remote interaction — read responses, send messages, approve tool calls, or let AutoPilot handle everything automatically.

This lets the coder — the captain — code on the go and make decisions on the fly. Stay connected without being tethered to a desk, the same way a business owner uses phone calls and text messages to stay connected with their operations.

### Vision

Today: run `kaptn start` on your Mac and Cascade auto-approves file edits while you step away.

Tomorrow: a server in the cloud runs any IDE, Kaptn manages the AI assistant, and you control it all from your phone or desktop — anywhere, any IDE, any OS.

### Core Capabilities

| Capability | Description |
|---|---|
| **AutoPilot** | Auto-approve tool calls based on rules, limits, and context. Detect loops. Escalate. |
| **Auto-Answer** | Detect conversational stalls ("Should I proceed?") and inject pre-configured replies. Firewall model — allow known patterns, block everything else. |
| **Auto-Register & Graceful Disconnect** | Auto-configure CDP in Windsurf's `argv.json` on first connect. Self-cleanup heartbeat removes all injected JS when Kaptn disconnects. |
| **Remote Chat** | Read AI responses and send messages from your phone |
| **Approval Control** | Approve/deny tool calls remotely when AutoPilot doesn't cover them |
| **Push Notifications** | Get notified when the AI needs your attention |
| **Audit Log** | Full record of every decision — auto or manual — with timestamps and rule matches |
| **AutoCommit** | Automatically commit changes based on rules, with a dedicated commit log |
| **AutoRollBack** | Use the audit log and commit log to roll back mistakes made by AutoPilot |
| **Multi-Window** | Manage multiple IDE windows with per-workspace and per-mode configuration |
| **MCP Server** | Expose AutoPilot as an MCP server — AI agents can request time-boxed, category-scoped approvals |

---

## 2. Architecture

### 2.1 Components

```
┌──────────────────────────────────────────────────────┐
│  Host (Mac / Windows / Linux)                        │
│                                                      │
│  IDE ◄───CDP:9222───► Kaptn Bridge (Python)          │
│  (AI Assistant)        ├── AutoPilot engine           │
│                        ├── Window manager             │
│                        ├── WebSocket server            │
│                        ├── REST API                    │
│                        ├── Push service                │
│                        ├── Selector validator          │
│                        └── Audit logger                │
└──────────────────────────────────────────────────────┘
                         │
               (Mode 1, 2, or 3)
                         │
┌──────────────────────────────────────────────────────┐
│  Client (iPhone / Android / Desktop browser)         │
│                                                      │
│  Kaptn PWA (home screen app)                         │
│  ├── Chat view (real-time conversation)              │
│  ├── AutoPilot controls (on/off, rules, limits)      │
│  ├── Approval cards (approve/deny tool calls)        │
│  ├── Audit log viewer                                │
│  ├── Window selector (multi-workspace)               │
│  └── Push notification handler                       │
└──────────────────────────────────────────────────────┘
```

### 2.2 Bridge (Python)

The bridge runs on the host machine alongside the IDE. It is the only component that talks to the IDE — everything else goes through the bridge.

**Responsibilities:**
- **CDP connection**: Connect to IDE on `localhost:9222`, auto-reconnect on disconnect
- **Window manager**: Discover and manage multiple IDE windows via CDP targets, select by workspace name
- **DOM polling**: Read AI chat panel every ~2 seconds for messages, tool calls, approvals
- **Message injection**: Type messages into the chat input and submit
- **AutoPilot**: Evaluate approvals against rules, apply limits, detect loops, escalate
- **Selector validation**: Verify DOM selectors on startup, attempt auto-recovery on failure
- **WebSocket server**: Stream events to connected PWA clients
- **REST API**: Catch-up endpoint, push subscription, config management
- **Audit log**: Persist every decision with timestamp, action, rule, source

### 2.3 PWA (React, Vite, TailwindCSS)

Installable web app for phone home screen. Connects to the bridge via WebSocket.

**Views:**
- **Chat**: Real-time message stream with markdown rendering and code blocks
- **Approvals**: Cards for pending tool calls with approve/deny buttons
- **AutoPilot**: Toggle on/off, view/edit rules, see real-time auto-approval activity
- **Audit Log**: Scrollable history of all decisions
- **AutoCommit**: Toggle on/off, view/edit commit rules, see real-time commit activity, browse the CommitLog
- **AutoRollBack**: Use the AuditLog and CommitLog to roll back changes when AutoPilot makes a mistake
- **Settings**: Connection config, push toggle, deployment mode, window selection

### 2.4 Reconnection

The PWA-to-bridge connection will drop when the phone backgrounds the app (~30s on iOS). This is the most critical UX challenge.

**Strategy:**
- Push notification wakes the user — tap opens the app
- On open, WebSocket reconnects immediately
- Bridge serves a catch-up REST endpoint with all missed events since last seen timestamp
- UI merges catch-up data seamlessly — no "loading" state, just appears
- Connection status indicator always visible

---

## 3. Deployment Modes

All three modes use the same bridge and PWA code. The only difference is how the client reaches the bridge.

### Mode 1: Local

```
Host: Bridge on localhost:3001
Client: Same machine browser
```

- **Use case**: Development, testing, AutoPilot-only (no phone needed)
- **Security**: No network exposure
- **Requirement**: Physical access to the host

### Mode 2: Direct (Tailscale)

```
Host: Bridge on Tailscale IP:3001
Client: Tailscale VPN → direct connection to host
```

- **Use case**: Primary personal mode — full remote access from anywhere
- **Security**: WireGuard encrypted tunnel, peer-to-peer, zero data leaves your devices
- **Requirement**: Tailscale on host + phone (free for personal use)
- **Push**: Apple/Google APNs — payload contains only "approval needed", no code or conversation data. You open the app and it reconnects to the bridge seamlessly with context to continue where you left off

### Mode 3: Cloud Relay (E2E Encrypted)

```
Host: Bridge → E2E encrypted WebSocket → Cloud relay
Client: PWA → E2E encrypted WebSocket → Cloud relay
```

- **Use case**: No VPN, stable public URL, team/shared access
- **Security**: All messages E2E encrypted (NaCl/libsodium). Relay is a dumb pipe — sees only ciphertext.
- **Key exchange**: QR code on host screen → scan with phone to establish shared secret
- **Requirement**: Deploy a relay service (Cloudflare Worker, Azure Container App, or similar)

### Mode Comparison

| | Local | Direct (Tailscale) | Cloud Relay |
|---|---|---|---|
| **Network** | localhost | WireGuard P2P | HTTPS via relay |
| **Data exposure** | Zero | Zero | Zero (E2E encrypted) |
| **Works from anywhere** | No | Yes | Yes |
| **Requires VPN** | No | Yes (Tailscale) | No |
| **Requires cloud infra** | No | No | Yes (1 relay) |
| **Latency** | <1ms | 10-50ms | 50-200ms |
| **Best for** | Dev/testing | Daily personal use | Team/shared |

---

## 4. Platform Support

### 4.1 Operating Systems

| OS | Priority | Status | Notes |
|---|---|---|---|
| **macOS** | Primary | v1 | Development and daily use |
| **Windows** | Primary | v1 | Same CDP approach, different launch command |
| **Linux** | Required | v2 | Cloud server target — headless IDE + Kaptn as a service |
| **iOS** | Primary | v1 | PWA on iPhone home screen |
| **Android** | Required | v2 | PWA on Android home screen |

**Long-term vision**: Multiple deployment modes — from installing locally on any OS, to a cloud instance on Windows or Linux, to fully automated. Kaptn runs on a server in the cloud alongside a headless IDE instance. Users access it from any device via the PWA — a full AI coding service. 

### 4.2 IDE Support

| IDE | Priority | Status | Notes |
|---|---|---|---|
| **Windsurf** | Primary | v1 | Electron-based, CDP confirmed working |
| **VS Code** | Required | v2 | Electron-based, same CDP approach |
| **Cursor** | Required | v2 | Electron-based, LazyGravity has prior art |
| **WebStorm / IntelliJ** | Planned | v3 | JetBrains — needs different driver (not CDP) |

The bridge uses a **pluggable driver system**. Each IDE gets its own driver class that implements a standard interface:

```python
class IDEDriver(ABC):
    name: str                    # "windsurf", "vscode", "cursor"
    process_name: str            # OS process name to discover
    launch_commands: dict        # Per-OS launch commands with CDP flag
    
    def get_selectors(self) -> dict       # DOM selectors for this IDE
    def extract_messages(self, html)      # Parse messages from DOM
    def detect_approval(self, dom)        # Find approval dialogs
    def inject_message(self, text)        # Type and submit a message
    def click_approve(self, element)      # Click approve button
    def click_deny(self, element)         # Click deny button
```

### 4.3 IDE Launch Commands

| OS | Windsurf | VS Code |
|---|---|---|
| **macOS** | `open -a Windsurf --args --remote-debugging-port=9222` | `open -a "Visual Studio Code" --args --remote-debugging-port=9222` |
| **Windows** | `windsurf.exe --remote-debugging-port=9222` | `code.exe --remote-debugging-port=9222` |
| **Linux** | `windsurf --remote-debugging-port=9222` | `code --remote-debugging-port=9222` |

**Decision**: Kaptn should modify the IDE's desktop shortcut/alias to include the CDP flag automatically so the user doesn't have to remember it.

### 4.4 Auto-Register & Graceful Disconnect

Auto-configure CDP in the IDE's `argv.json` on first connect. When the bridge disconnects or crashes, a heartbeat-based self-cleanup timer removes all injected JS from the DOM — leaving zero footprint.

**See**: [features/AUTO_REGISTER_GRACEFUL_DISCONNECT.md](features/AUTO_REGISTER_GRACEFUL_DISCONNECT.md)

---

## 5. Features

### 5.1 AutoPilot (v1 Priority)

Auto-approve AI tool calls based on configurable rules with limits, loop detection, and escalation.

**See**: [features/AUTOPILOT.md](features/AUTOPILOT.md)

### 5.1.1 Auto-Answer (v1 — AutoPilot extension)

Detect conversational stalls and inject pre-configured replies using a firewall model: allow-rules match known question patterns ("Should I proceed?", "Want me to continue?"), default blocks everything else.

**See**: [features/AUTO_ANSWER.md](features/AUTO_ANSWER.md)

### 5.2 Remote Chat (v1)

Read AI conversation and send messages from the PWA.

- Real-time message streaming via WebSocket
- Markdown rendering with syntax-highlighted code blocks
- Message input with send
- Connection status indicator
- Catch-up on missed messages when reconnecting

### 5.3 Remote Approval (v1)

Approve/deny tool calls from the PWA when AutoPilot doesn't handle them.

- Approval cards with context (command text, file path, action type)
- Approve/deny buttons with single tap
- Push notification when approval is needed
- Timeout handling (AI waits until you respond)

### 5.4 Audit Log (v1)

Full record of every approval decision.

- Timestamp, action type, details, decision, source (AutoPilot rule / manual / PWA)
- Stored locally on host (SQLite)
- Viewable and searchable from PWA
- Exportable (JSON, CSV)

### 5.5 Multi-Window Management (v1)

Manage multiple IDE windows from a single bridge.

- CDP returns multiple targets — one per window
- Select by workspace name (extracted from window title)
- Global config applies to all windows
- Per-workspace overrides (different AutoPilot rules per project)
- Per-mode overrides (different rules for Plan mode vs Execute mode)

### 5.6 Selector Validation & Recovery (v1)

IDE updates may break DOM selectors.

- On startup, validate all selectors against the live DOM
- Clear error messages when a selector fails
- Attempt auto-recovery: search for similar elements by structure/attributes
- For public release: AI-powered selector re-mapping (requires subscription)

### 5.7 AutoCommit (v2)

Automatically commit changes made by AutoPilot based on configurable rules.

- Commit after every N approved file edits, or after a task completes
- Configurable commit message templates (include rule ID, action summary)
- Dedicated **CommitLog** — separate from the audit log, tracks git commits made by Kaptn
- Toggle on/off per workspace
- Rules for when to commit: after file edits, after test passes, on schedule
- CLI: `kaptn autocommit status`, `kaptn autocommit log`

### 5.8 AutoRollBack (v2)

Roll back changes when AutoPilot makes a mistake, using the audit log and commit log.

- Browse the CommitLog to find the commit to revert
- One-tap rollback from PWA or CLI
- Uses `git revert` (safe) rather than `git reset` (destructive)
- Cross-references AuditLog entries with CommitLog entries so you can see exactly which AutoPilot decisions led to each commit
- CLI: `kaptn rollback list`, `kaptn rollback <commit-id>`

### 5.9 Configuration & Defaults (v1)

Global defaults, per-window overrides, runtime modification via MCP, and persistence. All behavior flows from `kaptn.config.json` — poll intervals, AutoPilot rules, loop detection, logging. MCP tools can view and modify these at runtime with immediate hot-reload and disk persistence.

**See**: [features/CONFIG.md](features/CONFIG.md)

### 5.10 MCP Server (v2)

Expose Kaptn as an MCP server so AI agents (and users via natural language) can dynamically control AutoPilot. Time-boxed approval windows, category scoping, and alert contracts — all through standard MCP tool calls. See [MCPServer.md](MCPServer.md) for full design.

### 5.11 Future Features (v2+)

| Feature | Description |
|---|---|
| **File Explorer** | Browse workspace files from PWA |
| **Terminal View** | Read terminal output in real-time |
| **Git Status** | See changed files, diffs |
| **Session Switcher** | Switch between AI conversations |
| **Model Switching** | Switch AI models based on task type |
| **Cloud Relay** | Mode 3 — E2E encrypted relay |
| **Team Mode** | Multiple users, shared relay, access controls |
| **Headless Mode** | Run IDE + Kaptn on a server as a service |
| **Time-Based Event Tracking** | Time-aware detection, session lifecycle, metrics, and event-driven architecture. See [TimeBasedEventTracking.md](features/TimeBasedEventTracking.md) |

---

## 6. CDP Integration

### 6.1 Connection

The IDE must be launched with CDP enabled on a fixed port:

```bash
# macOS
open -a Windsurf --args --remote-debugging-port=9222
```

The bridge discovers renderer targets via `GET http://localhost:9222/json` and connects to the correct target's `webSocketDebuggerUrl` based on workspace name.

### 6.2 DOM Selectors (Windsurf)

Mapped from live CDP inspection (2026-03-07). Full details in [KaptnResearch.md](../KaptnResearch.md) Section 6.3.

| Element | Selector | Notes |
|---|---|---|
| Panel root | `#windsurf.cascadePanel` | class `chat-client-root` |
| Chat container | `#chat` | |
| Active tab | `[id^="cascade-tab-"]` | ID includes conversation UUID |
| Scroll area | `.cascade-scrollbar` | |
| Message container | `.cascade-scrollbar .pb-20 > .flex.flex-col.px-4` | All messages |
| Chat input | `[contenteditable=true]` with class `min-h-[2rem]` | NOT a textarea |
| Submit button | `.panel-border.panel-bg.shadow-menu > button[type=submit]` | SVG icon |
| AI responses | `[class*="prose"][class*="prose-sm"]` | Rendered markdown |
| User messages | Child contains `.flex.w-full.flex-row.transition-opacity` | |
| Tool call blocks | Child contains `.flex.flex-col.gap-1.5` | Commands, edits, todos |
| Feedback dividers | `.mark-js-ignore` | Skip these |
| Approval buttons | TBD — dynamically rendered | Map during Phase 1 |
| Stop button | TBD — appears during generation | Map during Phase 1 |

### 6.3 Polling Strategy

- **Messages**: Every 2 seconds. Compare against last known count.
- **Approvals**: Every 1 second (time-sensitive). Scan for new buttons in tool call blocks.
- **Status**: Every 5 seconds. Generating, idle, or waiting for input.

---

## 7. Tech Stack

| Component | Technology |
|---|---|
| **Bridge** | Python 3.12+, `asyncio`, `websockets` |
| **CDP Client** | `websockets` (raw CDP protocol over WebSocket) |
| **AutoPilot** | Python rules engine, JSON config |
| **Audit Log** | SQLite via `sqlite3` (stdlib) |
| **WebSocket Server** | `websockets` (for PWA clients) |
| **REST API** | `aiohttp` or `FastAPI` |
| **CLI** | `click` or `typer` |
| **Logging** | Python `logging` with structured JSON output, configurable levels |
| **Testing** | `pytest`, `pytest-asyncio`, `pytest-cov` |
| **PWA** | React, Vite, TailwindCSS |
| **Push** | Web Push API (VAPID), `pywebpush` |
| **E2E Encryption** | `PyNaCl` (libsodium) — Mode 3 only |

---

## 8. Coding Standards

### 8.1 General Rules

- **Language**: Python 3.12+ for bridge, TypeScript/React for PWA
- **Max file size**: 500 lines. If a file exceeds this, refactor into smaller modules.
- **Class files**: Each class lives in its own file, named after the class (e.g., `AutoPilotEngine` → `auto_pilot_engine.py`)
- **Imports**: Always at the top of the file. No inline imports.
- **Unit tests**: Every module has corresponding tests. No exceptions.
- **Logging**: Every class uses structured logging. Log level configurable per module.
- **Security**: No secrets in code. No hardcoded credentials. All network communication encrypted.
- **Documentation**: Docstrings on every public class and method. README per package.

### 8.2 File Organization

- **Orchestration files**: Thin entry points that compose smaller modules. Keep logic in dedicated classes.
- **README hierarchy**: Main README covers overview and quickstart. Each package has its own README for details.
- **Feature docs**: Each feature has its own design doc in `docs/features/`. Referenced from this document.
- **Human + AI readable**: Short files, clear names, explicit structure. Optimized for both human scanning and AI context windows.

### 8.3 Logging

```python
import logging

logger = logging.getLogger(__name__)

# Levels used consistently:
# DEBUG   — CDP raw messages, DOM query results, rule evaluation details
# INFO    — Approval decisions, connection events, config changes
# WARNING — Selector validation failures, reconnection attempts
# ERROR   — CDP disconnects, unrecoverable failures
# CRITICAL — Security violations, data integrity issues
```

Structured JSON log output for machine parsing. Human-readable console output for development.

---

## 9. Project Structure

```
Kaptn/
├── README.md                           # Overview, quickstart, links to docs
├── KaptnResearch.md                    # Research & investigation notes
├── pyproject.toml                      # Python project config (dependencies, scripts)
│
├── docs/
│   ├── DESIGN.md                       # This document
│   ├── README.md                       # Docs index
│   └── features/
│       ├── AUTOPILOT.md                # AutoPilot feature design
│       └── ... (future feature docs)
│
├── bridge/                             # Python bridge package
│   ├── README.md                       # Bridge overview, usage, config
│   ├── __init__.py
│   ├── main.py                         # CLI entry point (thin orchestrator)
│   │
│   ├── cdp/                            # CDP connection layer
│   │   ├── __init__.py
│   │   ├── cdp_connection.py           # class CdpConnection
│   │   ├── cdp_discovery.py            # class CdpDiscovery
│   │   └── cdp_evaluator.py            # class CdpEvaluator
│   │
│   ├── drivers/                        # IDE-specific drivers
│   │   ├── __init__.py
│   │   ├── ide_driver.py               # class IDEDriver (ABC)
│   │   └── windsurf_driver.py          # class WindsurfDriver
│   │
│   ├── autopilot/                      # AutoPilot engine
│   │   ├── __init__.py
│   │   ├── auto_pilot_engine.py        # class AutoPilotEngine
│   │   ├── rule_evaluator.py           # class RuleEvaluator
│   │   ├── loop_detector.py            # class LoopDetector
│   │   ├── escalation_handler.py       # class EscalationHandler
│   │   ├── auto_reply_rule.py          # class AutoReplyRule
│   │   └── auto_reply_engine.py        # class AutoReplyEngine
│   │
│   ├── setup/                          # IDE setup and configuration
│   │   ├── __init__.py
│   │   └── windsurf_setup.py           # CDP auto-config for argv.json
│   │
│   ├── monitors/                       # DOM polling monitors
│   │   ├── __init__.py
│   │   ├── message_monitor.py          # class MessageMonitor
│   │   ├── approval_monitor.py         # class ApprovalMonitor
│   │   └── status_monitor.py           # class StatusMonitor
│   │
│   ├── server/                         # WebSocket + REST for PWA
│   │   ├── __init__.py
│   │   ├── websocket_server.py         # class WebSocketServer
│   │   ├── rest_api.py                 # class RestApi
│   │   └── push_service.py             # class PushService
│   │
│   ├── audit/                          # Audit log
│   │   ├── __init__.py
│   │   └── audit_logger.py             # class AuditLogger
│   │
│   ├── config/                         # Configuration management
│   │   ├── __init__.py
│   │   ├── config_manager.py           # class ConfigManager
│   │   └── config_schema.py            # Pydantic models for config validation
│   │
│   ├── mcp/                            # MCP server (subprocess architecture)
│   │   ├── __init__.py
│   │   ├── mcp_server.py              # Server orchestration, tool registration
│   │   ├── _bridge_worker.py          # Bridge subprocess (CDP + poll loop)
│   │   ├── _progress.py              # Atomic JSON IPC (progress + commands)
│   │   ├── _state.py                 # Shared MCP server state
│   │   └── tools/                     # MCP tool handlers
│   │       ├── tool_connect.py        # kaptn_connect (spawn subprocess)
│   │       ├── tool_watch.py          # kaptn_watch
│   │       ├── tool_approve_category.py # kaptn_approve_category
│   │       ├── tool_stop.py           # kaptn_stop + disconnect
│   │       ├── tool_status.py         # kaptn_status (read progress)
│   │       ├── tool_audit.py          # kaptn_audit
│   │       ├── tool_resume.py         # kaptn_resume
│   │       ├── tool_defaults.py       # kaptn_defaults
│   │       └── tool_defaults_set.py   # kaptn_defaults_set
│   │
│   ├── selectors/                      # Selector validation & recovery
│   │   ├── __init__.py
│   │   ├── selector_validator.py       # class SelectorValidator
│   │   └── selector_recovery.py        # class SelectorRecovery
│   │
│   └── window/                         # Multi-window management
│       ├── __init__.py
│       └── window_manager.py           # class WindowManager
│
├── pwa/                                # React PWA (Phase 2)
│   ├── README.md
│   ├── public/
│   │   ├── manifest.json
│   │   ├── sw.js
│   │   └── icons/
│   ├── src/
│   │   ├── components/                 # One component per file
│   │   ├── hooks/
│   │   ├── App.tsx
│   │   └── main.tsx
│   ├── package.json
│   └── vite.config.ts
│
├── tests/                              # All tests
│   ├── __init__.py
│   ├── conftest.py                     # Shared fixtures
│   ├── bridge/
│   │   ├── cdp/
│   │   │   ├── test_cdp_connection.py
│   │   │   ├── test_cdp_discovery.py
│   │   │   └── test_cdp_evaluator.py
│   │   ├── drivers/
│   │   │   └── test_windsurf_driver.py
│   │   ├── autopilot/
│   │   │   ├── test_auto_pilot_engine.py
│   │   │   ├── test_rule_evaluator.py
│   │   │   └── test_loop_detector.py
│   │   ├── monitors/
│   │   │   ├── test_message_monitor.py
│   │   │   └── test_approval_monitor.py
│   │   ├── audit/
│   │   │   └── test_audit_logger.py
│   │   └── window/
│   │       └── test_window_manager.py
│   └── pwa/                            # Frontend tests (Phase 2)
│
└── kaptn.config.json                   # User config (AutoPilot rules, settings)
```

---

## 10. Configuration

All behavior flows from a single config file — `kaptn.config.json` — at the project root. It defines connection settings, poll intervals, AutoPilot rules, loop detection, and logging.

**See**: [features/CONFIG.md](features/CONFIG.md) for full schema, per-window overrides, runtime modification via MCP, and persistence.

### 10.1 Configuration Layers

```
kaptn.config.json (global defaults)
    → Per-window overrides (different rules per workspace)
    → Per-mode overrides (Plan vs Execute)
    → MCP runtime changes (kaptn_defaults_set — persisted)
    → Temporary MCP rules (kaptn_watch — in-memory, TTL-based)
```

### 10.2 Key Sections

| Section | Purpose | Details |
|---|---|---|
| `poll_intervals` | How often bridge polls IDE DOM | approvals: 1s, messages: 2s, status: 5s |
| `autopilot.rules` | Rule-based approval behavior | See [AUTOPILOT.md](features/AUTOPILOT.md) |
| `autopilot.loop_detection` | Loop detection thresholds | same_action: 3, oscillation: 3, history: 20 |
| `windows.overrides` | Per-workspace profiles | Different rules per project |
| `logging` | Log level and format | Per-module overrides supported |

### 10.3 Runtime Modification

MCP tools can view (`kaptn_defaults`) and modify (`kaptn_defaults_set`) configuration at runtime. Changes apply immediately via hot-reload and persist to the config file. See [features/CONFIG.md](features/CONFIG.md) Section 6.

---

## 11. Build Order

### Phase 1: Bridge + AutoPilot (standalone CLI)

**Goal**: Cascade runs hands-free. No phone needed.

1. Project scaffold (Python, venv, pytest, logging)
2. CDP connection + discovery + multi-window
3. Windsurf driver — selectors, message extraction, approval detection
4. Selector validation on startup
5. AutoPilot rules engine + loop detection
6. Audit log (SQLite)
7. CLI: `kaptn start`, `kaptn status`, `kaptn log`

**Deliverable**: Run `kaptn start` and Cascade auto-approves while you're away. Full audit trail.

### Phase 2: PWA + Remote Chat

**Goal**: Read and respond from your phone.

1. WebSocket server on bridge
2. PWA chat view with real-time rendering
3. Remote approval cards
4. AutoPilot controls from PWA
5. PWA manifest + service worker

**Deliverable**: Install Kaptn on your iPhone home screen. See Cascade live. Approve remotely.

### Phase 3: Push + Tailscale (Mode 2)

**Goal**: Get notified anywhere.

1. Web Push (VAPID keys, `pywebpush`)
2. Push on approval-needed events
3. Tailscale connection guide + handling
4. Reconnection with catch-up

**Deliverable**: Push notification → tap → approve from coffee shop.

### Phase 4: Cloud Relay (Mode 3)

**Goal**: No VPN required.

1. Relay service (Cloudflare Worker or Azure Container App)
2. E2E encryption (NaCl, QR key exchange)
3. Relay protocol (WebSocket forwarder, ciphertext only)

**Deliverable**: Access Kaptn from any network.

---

## 12. Security

### Principles

- **Zero trust on relay**: In Mode 3, the relay never sees plaintext. E2E encryption is mandatory.
- **No secrets in code**: All credentials via config files or environment variables.
- **Minimal push payloads**: Push notifications contain only "action needed" — no code, no conversation text.
- **Audit everything**: Every approval decision is logged with full context.
- **Selector recovery AI is opt-in**: Requires explicit subscription for public release. Never sends code to external services without consent.

### Network Security by Mode

| Mode | Encryption | Data Exposure |
|---|---|---|
| Local | N/A (localhost) | Zero |
| Direct | WireGuard (Tailscale) | Zero |
| Cloud Relay | NaCl E2E + TLS transport | Zero (relay sees ciphertext) |

---

## 13. Design Decisions Log

Decisions made during design, with rationale. See [KaptnResearch.md](../KaptnResearch.md) for the full research conversation.

| # | Decision | Rationale |
|---|---|---|
| 1 | CDP over direct API | Windsurf's gRPC API is proprietary, undocumented, tied to IDE session. CDP is standard. |
| 2 | Python over Node.js | Cross-platform consistency, better async, easier packaging for CLI tool, team preference. |
| 3 | PWA over native iOS | 90% native feel (push, home icon, offline). No App Store, no Xcode. Supports Android too. |
| 4 | Tailscale for Mode 2 | Free, zero-config VPN. WireGuard encryption. No relay needed. |
| 5 | AutoPilot as v1 priority | Immediate value — hands-free Cascade. No phone or PWA needed. |
| 6 | Pluggable IDE drivers | Windsurf first, but architecture supports VS Code, Cursor, JetBrains later. |
| 7 | Multi-window from start | Users often have multiple workspaces. Per-workspace config is essential. |
| 8 | Selector auto-recovery | IDE updates will break selectors. Graceful degradation + recovery is critical. |
| 9 | 2s polling interval | Fast enough for real-time feel, low CPU impact. 1s for approvals (time-sensitive). |
| 10 | Modify IDE shortcut for CDP | User shouldn't have to remember `--remote-debugging-port`. Make it automatic. |
| 11 | AutoCommit + AutoRollBack | Safety net for AutoPilot — automatic git commits enable easy rollback when automation makes mistakes. |
| 12 | MCP Server for AutoPilot | AI agents can request time-boxed approval scopes via standard MCP tools. Dynamic rules > static config. |
| 13 | Subprocess worker for MCP bridge | FastMCP owns the anyio event loop for stdio. In-process async tasks block the transport. Subprocess + atomic JSON IPC gives isolation, crash resilience, and simplicity. |
| 14 | Auto-Answer for conversational stalls | AutoPilot handles buttons but AI also stalls on questions ("Should I proceed?"). Firewall model — allow known patterns, block-all default — keeps sessions moving without risk. |
| 15 | Auto-Register CDP via argv.json | Users shouldn't have to know about `--remote-debugging-port`. Kaptn patches `~/.windsurf/argv.json` on first failed connect — one restart and it works forever. |
| 16 | Heartbeat self-cleanup for injected JS | When Kaptn crashes, MutationObserver and scroll-to-bottom persist as zombies. Heartbeat (1s ping) + stale check (60s) + 5min threshold + 5min grace = automatic cleanup, zero DOM footprint after disconnect. |
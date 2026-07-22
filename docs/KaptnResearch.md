# Kaptn — Design Document

> A remote bridge for controlling Windsurf's Cascade AI assistant from your iPhone.

**Date**: March 7, 2026
**Status**: Design Phase

---

## 1. Problem Statement

Windsurf's Cascade is a powerful AI coding assistant, but it's locked inside the desktop IDE. There's no mobile client, no public API, and no official way to interact with Cascade sessions remotely. The goal is to build a tool that lets you **read Cascade conversations, send messages, and approve/deny actions from your iPhone** — in real time, on the go.

this allows the coder / captain to code on the go and make decisions on the fly. Staying connected with out being tethered to a desk. IE how business owners uses Phone calls and text messages to stay connected with their operations.

---

## 2. Investigation: How Windsurf Works Internally

### 2.1 Windsurf Architecture

Windsurf is an **Electron-based VS Code fork** by Codeium. Key findings:

- **Binary**: `/Applications/Windsurf.app/Contents/MacOS/Electron`
- **CLI alias**: `surf`
- **Data folder**: `~/.windsurf` (extensions), `~/.codeium/windsurf` (Cascade data)
- **Extension**: Bundled at `/Applications/Windsurf.app/Contents/Resources/app/extensions/windsurf/`
  - Single 9MB bundled file: `dist/extension.js`
  - Activates on `*` (all events)

### 2.2 Network Protocol

Windsurf uses **gRPC-web over HTTPS** to communicate with Codeium's backend:

| Endpoint | Purpose |
|---|---|
| `server.self-serve.windsurf.com` | Main API server (live traffic) |
| `server.codeium.com` | API server (hardcoded in extension) |
| `inference.codeium.com` | AI inference |
| `register.windsurf.com` | Authentication/registration |

The extension uses CSRF tokens for session security.

### 2.3 Protobuf Message Types

Found in the bundled extension — the full conversation protocol:

**Chat messages:**
- `exa.chat_pb.ChatMessage` — individual messages
- `exa.chat_pb.Conversation` — conversation container
- `exa.chat_pb.ChatMessageAction` — tool call actions
- `exa.chat_pb.ChatMessageActionEdit` — file edit actions
- `exa.chat_pb.ChatMessageActionSearch` — search actions
- `exa.chat_pb.ChatMessagePrompt` — user prompts
- `exa.chat_pb.ChatMessageStatus` — message status tracking
- `exa.chat_pb.ChatMessageError` — error messages

**Streaming (real-time):**
- `StreamCascadeReactiveUpdates` — live conversation updates
- `StreamCascadePanelReactiveUpdates` — panel state changes
- `StreamCascadeSummariesReactiveUpdates` — conversation summaries
- `StreamUserTrajectoryReactiveUpdates` — user activity tracking
- `StreamReactiveUpdatesRequest/Response` — generic streaming

**Session management:**
- `GetChatMessageRequest/Response` — fetch messages
- `RecordChatPanelSessionRequest/Response` — session recording
- `RecordChatFeedbackRequest/Response` — feedback
- `GetConversationTagsRequest/Response` — conversation metadata

**Cascade plugins/MCP:**
- `exa.cascade_plugins_pb.CascadePluginCommand`
- `exa.cascade_plugins_pb.GetMcpClientInfosRequest/Response`
- `exa.auto_cascade_common_pb.SessionInfo`

### 2.4 Local Data Storage

Cascade conversations are cached locally as **protobuf binary files**:

```
~/.codeium/windsurf/cascade/
├── 16193888-78c9-45e7-8e5f-65cd7664d230.pb
├── 680fd9ad-20b3-4085-ba44-db71be4ac67d.pb
├── ... (one .pb file per conversation)
```

Other local data:
- `~/.codeium/windsurf/user_settings.pb` — user preferences
- `~/.codeium/windsurf/installation_id` — unique install ID
- `~/.codeium/windsurf/mcp_config.json` — MCP server configuration
- `~/.codeium/windsurf/codemaps/` — code map cache

### 2.5 Extension Commands (Cascade-specific)

```
windsurf.cascade.acceptCascadeStep     — approve a tool call
windsurf.cascade.rejectCascadeStep     — deny a tool call
windsurf.cascade.pressMicrophone       — voice input
windsurf.cascade.openAgentPicker       — switch agent
windsurf.cascade.toggleModelSelector   — switch model
windsurf.cascade.switchToNextModel     — cycle models
windsurf.cascade.toggleWorktree        — toggle worktree
windsurf.triggerCascade                — open Cascade panel
windsurf.addCurrentFileToChat          — add file to context
```

### 2.6 Proposed API Extensions (in extension)

```
windsurfAuth    — authentication provider
windsurfAcp     — unknown (possibly "agent control protocol"?)
windsurfEditorNudge — editor nudge system
```

---

## 3. Approaches Considered

### 3.1 Direct API Integration ❌

**Approach**: Call Codeium's gRPC-web API directly from a mobile client.

**Why not**:
- Protocol is proprietary and undocumented
- Auth is tied to the IDE's session (CSRF tokens, installation ID)
- Codeium could change the API at any time
- Likely violates ToS

### 3.2 File System Watching ❌

**Approach**: Monitor `~/.codeium/windsurf/cascade/*.pb` files for changes.

**Why not**:
- Not real-time (polling-based)
- Protobuf schema is undocumented (would need to reverse-engineer)
- Read-only (can't send messages back)
- User explicitly rejected this approach

### 3.3 VS Code Extension + Internal Events ❌

**Approach**: Build a Windsurf extension that hooks into Cascade's internal message bus.

**Why not**:
- Windsurf doesn't expose Cascade messages to third-party extensions
- The `windsurfAcp` proposed API is internal and undocumented
- Cascade's chat is a sealed webview, not a standard VS Code chat participant
- Would break on every Windsurf update

### 3.4 gRPC-web MITM Proxy ⚠️

**Approach**: Use `windsurf.setServiceUrl` to redirect Windsurf to a local proxy that mirrors traffic.

**Pros**:
- Full access to all conversation data
- Could intercept and inject messages

**Cons**:
- Intercepts ALL Windsurf traffic (auth, telemetry, etc.)
- Codeium could add cert pinning
- Complex to maintain
- Security risk (proxy sees all data including auth tokens)

### 3.5 Chrome DevTools Protocol (CDP) ✅ — CHOSEN APPROACH

**Approach**: Launch Windsurf with `--remote-debugging-port=9222`, use CDP to read/write the Cascade chat panel DOM.

**Pros**:
- Real-time access to conversation UI
- Bidirectional (read responses, inject messages, click buttons)
- Well-documented protocol (Chrome DevTools Protocol)
- Non-invasive (doesn't modify Windsurf's traffic)
- Already proven by LazyGravity project (see section 4)

**Cons**:
- DOM selectors can break on Windsurf UI updates (manageable)
- Requires launching Windsurf with a special flag
- 2-second polling interval for DOM changes (LazyGravity's approach)

---

## 4. Prior Art: LazyGravity

**Repo**: [tokyoweb3/LazyGravity](https://github.com/tokyoweb3/LazyGravity)

LazyGravity is an open-source project that does exactly what we need — but for the "Antigravity" AI IDE. It bridges an AI IDE to Discord using CDP. Key architecture:

### 4.1 How LazyGravity Works

1. **CdpService** — discovers the IDE process, connects via CDP WebSocket
2. **ResponseMonitor** — polls the IDE's DOM every 2 seconds to extract AI responses
3. **ApprovalDetector** — detects approval buttons (allow/deny) in the DOM
4. **PlanningDetector** — detects planning mode dialogs
5. **ErrorPopupDetector** — catches error popups
6. **UserMessageDetector** — mirrors messages typed directly in the IDE
7. **Discord Bot** — forwards everything to Discord with interactive buttons

### 4.2 LazyGravity's RFC for Multi-IDE Support (Issue #39)

LazyGravity has an open RFC to support Cursor, Windsurf, and other AI IDEs via a pluggable driver system:

```typescript
interface IDEDriver {
  name: string
  processName: string        // e.g., "Windsurf"
  launchCommand: string      // e.g., "open -a Windsurf --args --remote-debugging-port=9222"
  selectors: {
    chatInput: string        // Textbox for prompt input
    sidePanel: string        // Agent/assistant panel container
    renderedMarkdown: string // Rendered response blocks
    stopButton: string       // Cancel/stop generation button
    notifyContainer: string  // Approval/planning dialog
    codeBlock: string        // Code block elements
  }
  extractResponse(html: string): ResponseSegment[]
  detectApproval(dom: Document): ApprovalState | null
  detectPlanning(dom: Document): PlanInfo | null
}
```

### 4.3 What Kaptn Takes from LazyGravity

- The CDP connection approach and DOM polling pattern
- The driver interface concept for IDE-specific selectors
- Approval detection and interactive button patterns
- **NOT** the Discord output layer — we're building a PWA instead

---

## 5. Chosen Architecture: CDP Bridge + PWA over Tailscale

### 5.1 Overview

```
┌──────────────────────────────────────────────────┐
│  Mac (your dev machine)                          │
│                                                  │
│  Windsurf IDE ◄──CDP:9222──► Kaptn Bridge        │
│  (Cascade)                   (Node.js)           │
│                              ├── WebSocket :3001  │
│                              └── REST API :3001   │
└────────────────────┬─────────────────────────────┘
                     │ Tailscale (WireGuard VPN)
                     │ Encrypted, peer-to-peer
┌────────────────────┴─────────────────────────────┐
│  iPhone                                          │
│                                                  │
│  Kaptn PWA (home screen app)                     │
│  ├── WebSocket client (real-time chat)           │
│  ├── Push notifications (approvals)              │
│  ├── Markdown/code rendering                     │
│  └── Approve/deny buttons                        │
└──────────────────────────────────────────────────┘
```

### 5.2 Security Model

- **Zero cloud**: All data stays on your network. Tailscale creates a direct encrypted tunnel.
- **No relay server**: Tailscale uses WireGuard — peer-to-peer when possible, DERP relay (encrypted) otherwise.
- **No data exposure**: The bridge runs on localhost, only reachable via Tailscale IP.
- **Push notifications**: The only cloud touchpoint — Apple's APNs. The push payload contains only "approval needed" (no code/conversation data).

### 5.3 Alternative Security Models (if needed later)

| Model | How it works | Trade-off |
|---|---|---|
| **Tailscale only** ✅ | Direct WireGuard tunnel | Requires Tailscale on phone (free) |
| **E2E encrypted cloud relay** | NaCl-encrypted WebSocket through Cloudflare Worker | Works without VPN, relay sees only ciphertext |
| **Local network only** | Same WiFi, mDNS discovery | Only works at home/office |

---

## 6. Component Design

### 6.1 Kaptn Bridge (Node.js, TypeScript)

Runs on the Mac alongside Windsurf. Responsibilities:

**CDP Connection:**
- Discover Windsurf's CDP endpoint on port 9222
- Establish WebSocket connection to `ws://localhost:9222`
- Auto-reconnect on disconnect

**DOM Interaction (Windsurf driver):**
- Poll Cascade chat panel DOM every ~2 seconds
- Extract new messages (AI responses, user messages)
- Detect approval/deny button states
- Detect planning mode, errors, tool calls
- Inject user messages by simulating typing into chat input
- Click approve/deny buttons programmatically

**WebSocket Server (for PWA):**
- Real-time bidirectional communication
- Events: `message`, `approval_required`, `tool_call`, `error`, `status`
- Commands: `send_message`, `approve`, `deny`, `stop`

**Push Notification Service:**
- Web Push API (VAPID keys)
- Sends push when approval is needed and PWA is backgrounded
- Minimal payload (no sensitive data in push)

### 6.2 Kaptn PWA (React + Vite)

Installable web app for iPhone home screen. Features:

**Chat View (v1 — core):**
- Real-time message stream (WebSocket)
- Markdown rendering with syntax-highlighted code blocks
- Approve/deny buttons for tool calls
- Message input for sending prompts to Cascade
- Connection status indicator
- Auto-reconnect on WebSocket drop

**PWA Capabilities:**
- `manifest.json` — app name, icon, theme color, `display: standalone`
- Service worker — push notification handling, offline fallback page
- Add-to-home-screen prompt

**Future (v2+):**
- File explorer tree view (via Cascade or CDP DOM)
- Terminal output view
- Git status / changed files view
- Conversation history / session switcher

### 6.3 Windsurf DOM Selectors (TBD)

These need to be mapped by inspecting Windsurf's Cascade panel with CDP enabled. Expected selectors based on VS Code's structure and LazyGravity's pattern:

```typescript
// MAPPED — from CDP inspection on 2026-03-07
const windsurfSelectors = {
  // Top-level containers
  cascadePanel: '#windsurf\\.cascadePanel',          // Root: class "chat-client-root vscode-dark"
  chatContainer: '#chat',                             // Inner chat wrapper
  activeTab: '[id^="cascade-tab-"]',                  // Active conversation tab (ID includes UUID)
  scrollArea: '.cascade-scrollbar',                   // Scrollable message area
  messageContainer: '.cascade-scrollbar .pb-20 > .flex.flex-col.px-4',  // All messages live here

  // Chat input
  chatInput: '[contenteditable=true].min-h-\\[2rem\\]',  // contenteditable div (NOT textarea)
  inputWrapper: '.panel-border.panel-bg.shadow-menu',    // Outer input chrome
  submitButton: '.panel-border.panel-bg.shadow-menu > button[type=submit]',  // SVG icon button

  // Message types (children of messageContainer, distinguished by structure)
  // User messages:  cls="" → child has "flex w-full flex-row transition-opacity duration-300 opacity-100"
  // AI responses:   cls="" → contains div matching [class*=prose][class*=prose-sm]  (hasProse)
  // Tool calls:     cls="" → child has "flex flex-col gap-1.5 no-fadeIn" or "flex flex-col gap-1.5"
  // Feedback rows:  cls="mark-js-ignore" → text "Feedback submitted"

  renderedMarkdown: '[class*="prose"][class*="prose-sm"]',  // AI response prose blocks
  codeBlock: 'pre, code',                                    // Code blocks inside prose
  userMessage: '.flex.w-full.flex-row.transition-opacity',   // User message row
  toolCallBlock: '.flex.flex-col.gap-1\\.5.no-fadeIn',       // Tool call/action blocks
  feedbackRow: '.mark-js-ignore',                            // Feedback dividers (skip these)

  // Approval buttons (appear inside tool call blocks when Cascade awaits approval)
  // These are dynamically rendered — not present when no approval is pending
  // Need to detect by polling for buttons with text like "Allow", "Deny", "Run"
  approvalContainer: 'TBD — appears inside tool call blocks when command needs approval',
  approveButton: 'TBD — button with "Allow"/"Run" text inside approval container',
  denyButton: 'TBD — button with "Deny"/"Cancel" text inside approval container',

  // Misc
  showMoreButton: 'button',  // At top of messageContainer, text "Show More"
  stopButton: 'TBD — appears during generation',
}
```

**Note**: Approval and stop button selectors are marked TBD — they only appear dynamically when Cascade is waiting for input or generating. Will be mapped during runtime testing.

---

## 7. PWA on iOS — Capabilities & Limitations

### What works (iOS 17.4+)

| Feature | Status | Notes |
|---|---|---|
| Home screen icon | ✅ | Full app icon, splash screen, no browser chrome |
| Push notifications | ✅ | Web Push API, supported since iOS 16.4 |
| WebSocket | ✅ | Real-time streaming works perfectly |
| Offline fallback | ✅ | Service worker caching |
| Full-screen mode | ✅ | `display: standalone` — looks native |
| Badge count | ✅ | Badging API |
| Local storage | ✅ | IndexedDB, localStorage |
| Markdown rendering | ✅ | Full CSS control |

### Limitations vs native

| Feature | Limitation |
|---|---|
| Background WebSocket | Disconnects when app backgrounded (~30s) |
| Push reliability | Slightly less reliable than native APNs |
| Background execution | No long-running background tasks |
| Bluetooth/NFC | Not available |

**Mitigation for background disconnect**: Push notifications alert user → tap opens app → WebSocket reconnects instantly. Missed messages are fetched via REST catch-up endpoint on reconnect.

---

## 8. Launch Steps

### Step 1: Enable CDP on Windsurf

```bash
# Close Windsurf, then relaunch with CDP
open -a Windsurf --args --remote-debugging-port=9222

# Verify CDP is working
curl http://localhost:9222/json/version
```

### Step 2: Map DOM Selectors

Open Chrome DevTools against Windsurf's renderer:
```bash
# List CDP targets
curl http://localhost:9222/json

# Connect to the Cascade panel target and inspect DOM
# Use Runtime.evaluate to query selectors
```

### Step 3: Build & Run Bridge

```bash
cd /Users/wilson/windsurfer/Kaptn/bridge
npm install
npm run dev   # Starts CDP bridge + WebSocket server on :3001
```

### Step 4: Build & Run PWA

```bash
cd /Users/wilson/windsurfer/Kaptn/pwa
npm install
npm run dev   # Starts Vite dev server on :5173
```

### Step 5: Connect from iPhone

1. Install Tailscale on Mac + iPhone
2. Open `http://<tailscale-ip>:5173` on iPhone Safari
3. Tap "Add to Home Screen"
4. Open Kaptn from home screen — full-screen PWA

---

## 9. Project Structure

```
Kaptn/
├── bridge/                    # Node.js CDP bridge
│   ├── src/
│   │   ├── cdp/
│   │   │   ├── connection.ts  # CDP WebSocket connection
│   │   │   ├── discovery.ts   # Find Windsurf CDP endpoint
│   │   │   └── evaluator.ts   # DOM query helpers
│   │   ├── drivers/
│   │   │   ├── types.ts       # IDEDriver interface
│   │   │   └── windsurf.ts    # Windsurf-specific selectors & logic
│   │   ├── monitors/
│   │   │   ├── response.ts    # Poll for new AI responses
│   │   │   ├── approval.ts    # Detect approval dialogs
│   │   │   └── status.ts      # Connection/generation status
│   │   ├── server/
│   │   │   ├── websocket.ts   # WebSocket server for PWA
│   │   │   ├── rest.ts        # REST API (catch-up, push subscribe)
│   │   │   └── push.ts        # Web Push notification service
│   │   └── index.ts           # Entry point
│   ├── package.json
│   └── tsconfig.json
├── pwa/                       # React PWA (Vite)
│   ├── public/
│   │   ├── manifest.json      # PWA manifest
│   │   ├── sw.js              # Service worker
│   │   └── icons/             # App icons (various sizes)
│   ├── src/
│   │   ├── components/
│   │   │   ├── ChatView.tsx   # Main conversation view
│   │   │   ├── Message.tsx    # Single message (markdown + code)
│   │   │   ├── ApprovalCard.tsx # Approve/deny tool call
│   │   │   ├── InputBar.tsx   # Message input
│   │   │   └── StatusBar.tsx  # Connection status
│   │   ├── hooks/
│   │   │   ├── useWebSocket.ts
│   │   │   └── usePushNotifications.ts
│   │   ├── App.tsx
│   │   └── main.tsx
│   ├── index.html
│   ├── package.json
│   ├── vite.config.ts
│   └── tailwind.config.js
├── ConversationStarter.md     # This document
└── README.md
```

---

## 10. Effort Estimates

| Component | Effort | Depends on |
|---|---|---|
| Map Windsurf DOM selectors | 0.5 day | CDP restart |
| CDP bridge (connect, poll, inject) | 2 days | Selectors |
| WebSocket server | 0.5 day | Bridge |
| PWA chat UI | 1-2 days | WebSocket |
| Push notifications | 0.5 day | PWA |
| PWA manifest + service worker | 0.5 day | PWA |
| Tailscale setup + testing | 0.5 day | All |
| **Total v1** | **~5-7 days** | |

### Future (v2+)

| Feature | Effort |
|---|---|
| File explorer view | 2-3 days |
| Terminal output view | 1-2 days |
| Diff viewer | 1 week |
| Multiple Windsurf window support | 1-2 days |
| Conversation history/session switcher | 1 day |
| E2E encrypted cloud relay option | 2-3 days |

---

## 11. Alternatives Not Chosen (but available later)

### Discord via LazyGravity Fork

Fork LazyGravity, add a Windsurf driver, use Discord mobile app.
- **Pro**: Discord bot, notifications, buttons all built
- **Con**: Discord's formatting is limited for code, locked to Discord's UX
- **Effort**: 2-3 days
- **When**: If PWA approach has issues, this is the fast fallback

### Microsoft Teams Bot

Build a Teams bot that receives messages from the CDP bridge.
- **Pro**: Already on your phone, enterprise-friendly
- **Con**: Teams Bot Framework is heavyweight, slow message delivery
- **Effort**: 1-2 weeks
- **When**: If you need team-wide access (not just personal)

### Native iOS App (Swift)

Build a full native app with SwiftUI.
- **Pro**: Best UX, full background execution, native push
- **Con**: Requires Xcode, Apple Developer account ($99/yr), App Store review
- **Effort**: 3-4 weeks
- **When**: If PWA limitations become blockers (unlikely for this use case)

---

## 12. Open Questions

1. **Windsurf auto-launch**: Can we make Windsurf always start with `--remote-debugging-port=9222`? Possibly via a shell alias or macOS launch agent.

2. **DOM stability**: How often does Windsurf change its Cascade panel DOM structure? Need to monitor across updates.

3. **Multiple windows**: If multiple Windsurf windows are open, how does CDP handle multiple targets?

4. **Session persistence**: When Windsurf restarts, do we need to re-authenticate the CDP connection or does it auto-resume?

5. **Concurrent access**: Can the bridge read the DOM while you're also using Windsurf normally? (Likely yes — CDP is read-only by default, and injecting is just simulated input.)

6. **Rate limiting**: Does polling DOM every 2 seconds cause any performance impact on Windsurf?

---

## 13. Next Steps — Start Here

### Step 1: Launch Windsurf with CDP enabled

Close Windsurf, then run in Terminal:

```bash
open -a Windsurf --args --remote-debugging-port=9222
```

Verify CDP is working:

```bash
curl http://localhost:9222/json/version
```

### Step 2: Open this file in Cascade

Point a new Cascade session to this file so it has full context:

```
Read /Users/wilson/windsurfer/Kaptn/ConversationStarter.md
```

Then ask Cascade to:

1. **Inspect the Cascade chat panel DOM** via CDP to map the CSS selectors (Section 6.3)
2. **Scaffold the Kaptn project** (Section 9) — bridge + PWA
3. **Build the CDP bridge** with the mapped selectors
4. **Build the PWA** chat UI

### Step 3: Map DOM selectors

With CDP active, list the available targets:

```bash
curl http://localhost:9222/json
```

Find the Windsurf renderer target and connect to its `webSocketDebuggerUrl`. Then use `Runtime.evaluate` to inspect the Cascade panel DOM and fill in the selectors from Section 6.3.

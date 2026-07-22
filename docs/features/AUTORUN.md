# AutoRun — Windsurf Native Auto-Run Integration

> Leverage Windsurf's built-in auto-run capabilities alongside Kaptn's AutoPilot for a two-layer approval system.

**Parent**: [DESIGN.md](../DESIGN.md)
**Related**: [AUTOPILOT.md](AUTOPILOT.md), [MCPServer.md](../MCPServer.md)
**Status**: Research — not yet implemented

---

## 1. Discovery

Windsurf Cascade has a built-in **Configure Auto-Run** dropdown on command approval dialogs with four modes:

| Mode | Behavior |
|---|---|
| **Off** | Every command needs manual approval (default) |
| **Allowlist** | Only commands matching the allowlist auto-run |
| **Auto** | Windsurf decides what's safe to auto-run |
| **Turbo** | Everything auto-runs, no approval needed |

Additionally, there is a per-command **Allowlist** with three options per entry:
- **Prefix** — match commands starting with this text
- **Allow** — always auto-run this command
- **Deny** — never auto-run this command

### 1.1 Scope

Windsurf's auto-run applies to **terminal commands only**. It does not cover:
- File reads/writes/deletes
- MCP tool calls
- Search operations
- Unknown/custom tool invocations

### 1.2 Storage

The auto-run settings are **not** stored in any of the standard locations:
- Not in `~/Library/Application Support/Windsurf/User/settings.json`
- Not in workspace `state.vscdb` databases
- Not in `localStorage`

Likely stored in Windsurf's internal IndexedDB or in-memory extension state. Further investigation needed.

---

## 2. Two-Layer Architecture

When implemented, Kaptn can work alongside Windsurf's native auto-run:

```
Layer 1: Windsurf Auto-Run (native, fast, commands only)
    ↓ (if not auto-run)
Layer 2: Kaptn AutoPilot (all categories, rules, audit, loops)
    ↓ (if escalated)
Layer 3: User (manual approval via desk or PWA)
```

### 2.1 Benefits

- **Speed**: Windsurf handles known-safe commands natively — no CDP round-trip
- **Coverage**: Kaptn handles everything Windsurf doesn't (file ops, tools, etc.)
- **Audit**: Kaptn still logs all decisions, including what Windsurf auto-ran
- **Safety**: Kaptn's loop detection and limits still apply as a backstop

### 2.2 Coordination

Kaptn could programmatically control Windsurf's auto-run mode via CDP:

1. **Read** the current auto-run mode from the dropdown DOM
2. **Set** it when Kaptn starts a watch session (e.g., switch to Allowlist or Auto)
3. **Revert** it when the session expires or Kaptn stops

This avoids Kaptn having to click Run/Skip for every command — Windsurf handles it natively.

---

## 3. Potential CDP Integration

### 3.1 Detect Current Mode

Query the auto-run dropdown state via DOM inspection to determine which mode is active.

### 3.2 Change Mode

Click the dropdown and select a mode programmatically. This would require:
- Finding the dropdown trigger button
- Clicking to open the menu
- Selecting the desired mode
- Verifying the mode changed

### 3.3 Manage Allowlist

Add/remove entries from the allowlist by:
- Opening the allowlist settings (gear icon)
- Adding command prefixes
- Setting allow/deny per entry

---

## 4. Open Questions

1. **Where exactly are auto-run settings stored?** — Need to find the IndexedDB or internal state location
2. **Can we read/write settings directly?** — File-based config would be simpler than DOM manipulation
3. **Does auto-run fire events we can listen to?** — If Windsurf emits CDP events when auto-running, Kaptn could log them without polling
4. **Per-window or global?** — Does the auto-run mode apply per workspace window or globally?
5. **Does Auto mode have a public safety heuristic?** — Understanding what Windsurf considers "safe" would help Kaptn complement it

---

## 5. Implementation Priority

Low priority for now — Kaptn's CDP-based approval clicking works. This becomes valuable when:
- Performance matters (many rapid commands)
- Kaptn MCP Server is built (dynamic mode switching)
- Users want minimal CDP interaction for stealth operation

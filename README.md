# Kaptn

Remote command and control for AI coding assistants. Monitor, approve, and automate AI tool calls from anywhere.

## What is Kaptn?

Kaptn connects to your AI-powered IDE (Windsurf, VS Code, Cursor) via Chrome DevTools Protocol — and to Claude Code via its native hook system — and lets you:

- **AutoPilot** — Automatically approve/deny AI tool calls based on rules, limits, and loop detection
- **Remote Monitor** — Watch AI conversations and status from your phone or another device
- **Audit Log** — Every approval decision recorded with full context

Both backends share one rule engine, one config, and one audit DB. See
[docs/features/CLAUDE_CODE.md](docs/features/CLAUDE_CODE.md) for the Claude adapter:

```bash
kaptn claude install   # register the PreToolUse hook (once)
kaptn claude serve     # run the decision server (no CDP needed)
```

## Quick Start

### Prerequisites

- Python 3.12+
- An AI IDE with CDP support (Windsurf, VS Code, Cursor)

### Install

```bash
git clone <repo-url> && cd Kaptn
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

### Launch your IDE with CDP

```bash
# macOS
open -a Windsurf --args --remote-debugging-port=9222

# Windows
windsurf.exe --remote-debugging-port=9222

# Linux
windsurf --remote-debugging-port=9222
```

### Run Kaptn

```bash
# Check connection
kaptn status

# Start the bridge with AutoPilot
kaptn start

# View audit log
kaptn log
```

### MCP Server (AI Agent Integration)

```bash
# Start MCP server (auto-connects bridge subprocess)
kaptn mcp start

# Start without auto-connect
kaptn mcp start --no-connect
```

The MCP server runs as a stdio transport. The bridge runs as a **separate subprocess** that connects to the IDE via CDP. Tools communicate via atomic JSON files — no shared memory, no blocking.

See [MCP Server docs](docs/features/MCPServer.md) for full tool reference.

## Project Structure

```
Kaptn/
├── bridge/                 # Python bridge (core)
│   ├── cdp/                # CDP connection, discovery, JS evaluation
│   ├── drivers/            # IDE-specific drivers (Windsurf, VS Code, etc.)
│   ├── autopilot/          # Rule engine, loop detection, escalation
│   ├── monitors/           # DOM polling for messages, approvals, status
│   ├── audit/              # SQLite audit logger
│   ├── config/             # Configuration management
│   ├── mcp/                # MCP server (subprocess architecture)
│   │   ├── mcp_server.py   # Server orchestration + tool registration
│   │   ├── _bridge_worker.py # Bridge subprocess (CDP connect + poll)
│   │   ├── _progress.py    # Atomic JSON IPC (progress + commands)
│   │   ├── _state.py       # Shared MCP state
│   │   └── tools/          # MCP tool handlers
│   ├── selectors/          # Selector validation and recovery
│   ├── server/             # WebSocket + REST API for PWA
│   ├── window/             # Multi-window management
│   ├── models.py           # Shared data models
│   ├── logging_config.py   # Structured logging setup
│   └── main.py             # CLI entry point
├── docs/
│   ├── DESIGN.md           # Architecture and design decisions
│   └── features/
│       ├── AUTOPILOT.md    # AutoPilot feature spec
│       └── MCPServer.md    # MCP server design
├── tests/                  # Unit tests (pytest)
├── pyproject.toml          # Python project config
└── README.md
```

## Configuration

Kaptn uses `kaptn.config.json` (auto-generated on first run). Key settings:

| Setting | Default | Description |
|---|---|---|
| `cdp_port` | `9222` | CDP debug port |
| `bridge_port` | `3001` | Bridge server port |
| `autopilot.enabled` | `true` | Enable/disable AutoPilot |
| `autopilot.rules` | (standard profile) | Approval rules |

See [DESIGN.md](docs/DESIGN.md) for full configuration reference.

## Deployment Modes

1. **Local** — Bridge + IDE on the same machine
2. **LAN / Tailscale** — Bridge on one machine, control from another (no cloud)
3. **Cloud Relay** — E2E encrypted relay for full remote access

## Docs

- **[Design Document](docs/DESIGN.md)** — Architecture, tech stack, coding standards
- **[AutoPilot](docs/features/AUTOPILOT.md)** — Rules engine, limits, loop detection
- **[MCP Server](docs/features/MCPServer.md)** — AI agent integration, subprocess architecture
- **[Research Notes](KaptnResearch.md)** — CDP exploration and DOM mapping

## Development

```bash
# Run tests
source .venv/bin/activate
pytest tests/ -v

# Run with debug logging
kaptn start --log-level DEBUG

# Lint
ruff check bridge/ tests/
```

## License

Private — not yet open source.

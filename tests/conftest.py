"""Shared test fixtures for Kaptn tests."""

import pytest


@pytest.fixture
def sample_cdp_targets():
    """Sample CDP target list as returned by /json endpoint."""
    return [
        {
            "description": "",
            "id": "B9C21A83B68ED9FFE126C5BC883C940F",
            "title": "Kaptn — Mine",
            "type": "page",
            "url": "vscode-file://vscode-app/workbench.html",
            "webSocketDebuggerUrl": "ws://localhost:9222/devtools/page/B9C21A83B68ED9FFE126C5BC883C940F",
        },
        {
            "description": "",
            "id": "25DB73899AB63AD18A92F57BC517CE1A",
            "title": "TelemetryMCPV2 — Mine — README.md",
            "type": "page",
            "url": "vscode-file://vscode-app/workbench.html",
            "webSocketDebuggerUrl": "ws://localhost:9222/devtools/page/25DB73899AB63AD18A92F57BC517CE1A",
        },
        {
            "description": "",
            "id": "1D2C8EB2D9F06A16EF580AC2537C6039",
            "title": "",
            "type": "worker",
            "url": "",
            "webSocketDebuggerUrl": "ws://localhost:9222/devtools/page/1D2C8EB2D9F06A16EF580AC2537C6039",
        },
    ]


@pytest.fixture
def sample_cdp_version():
    """Sample CDP version response."""
    return {
        "Browser": "Chrome/142.0.7444.235",
        "Protocol-Version": "1.3",
        "User-Agent": "Windsurf/1.108.2 Chrome/142.0.7444.235 Electron/39.2.7",
        "webSocketDebuggerUrl": "ws://localhost:9222/devtools/browser/abc123",
    }

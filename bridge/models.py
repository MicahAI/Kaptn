"""Shared data models for the Kaptn bridge."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class ApprovalCategory(str, Enum):
    """Categories of AI tool call approvals."""

    FILE_READ = "file_read"
    FILE_WRITE = "file_write"
    FILE_DELETE = "file_delete"
    COMMAND_SAFE = "command_safe"
    COMMAND_UNSAFE = "command_unsafe"
    SEARCH = "search"
    TOOL_CALL = "tool_call"
    AUTO_REPLY = "auto_reply"
    UNKNOWN = "unknown"


class ApprovalAction(str, Enum):
    """Actions AutoPilot can take on an approval request."""

    APPROVE = "approve"
    DENY = "deny"
    ESCALATE = "escalate"


class DecisionSource(str, Enum):
    """Who made the approval decision."""

    AUTOPILOT = "autopilot"
    MANUAL = "manual"
    PWA = "pwa"


@dataclass
class CdpTarget:
    """A CDP debug target representing an IDE window."""

    id: str
    title: str
    target_type: str
    url: str
    websocket_url: str

    @property
    def workspace_name(self) -> str:
        """Extract workspace name from the window title.

        Windsurf titles follow the pattern: 'WorkspaceName — User — FileName'
        """
        if not self.title:
            return ""
        parts = self.title.split(" — ")
        return parts[0].strip() if parts else self.title.strip()

    @classmethod
    def from_json(cls, data: dict) -> "CdpTarget":
        """Create a CdpTarget from the CDP /json endpoint response."""
        return cls(
            id=data.get("id", ""),
            title=data.get("title", ""),
            target_type=data.get("type", ""),
            url=data.get("url", ""),
            websocket_url=data.get("webSocketDebuggerUrl", ""),
        )


@dataclass
class ApprovalRequest:
    """A parsed approval dialog from the IDE."""

    category: ApprovalCategory
    action: str
    details: dict = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)
    window_name: str = ""
    mode: str = "unknown"


@dataclass
class AuditRecord:
    """A record of an approval decision."""

    id: str
    timestamp: datetime
    window_name: str
    tab_id: str
    mode: str
    request: ApprovalRequest
    decision: ApprovalAction
    source: DecisionSource
    rule_id: str | None = None
    rule_action: str | None = None
    limit_status: dict = field(default_factory=dict)
    loop_detected: bool = False


@dataclass
class EscalationEvent:
    """An event triggered when AutoPilot escalates to the user."""

    request: ApprovalRequest
    reason: str
    rule_id: str | None = None
    limit_details: dict = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class CascadeMessage:
    """A parsed message from the Cascade chat panel."""

    index: int
    role: str  # "user", "assistant", "tool_call", "feedback"
    text: str
    has_prose: bool = False
    has_code: bool = False
    timestamp: datetime = field(default_factory=datetime.now)

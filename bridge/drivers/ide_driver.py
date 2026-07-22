"""Abstract base class for IDE-specific drivers.

Each supported IDE implements this interface to provide
DOM selectors, message parsing, and action execution.
"""

import logging
from abc import ABC, abstractmethod

from bridge.cdp.cdp_evaluator import CdpEvaluator
from bridge.models import ApprovalRequest, CascadeMessage

logger = logging.getLogger(__name__)


class IDEDriver(ABC):
    """Abstract interface for IDE-specific CDP interactions.

    Each IDE (Windsurf, VS Code, Cursor, etc.) implements this
    to handle its unique DOM structure and selectors.
    """

    name: str = ""
    process_name: str = ""

    def __init__(self, evaluator: CdpEvaluator) -> None:
        """Initialize the driver with a CDP evaluator.

        Args:
            evaluator: CdpEvaluator connected to the IDE's debug target.
        """
        self.evaluator = evaluator

    @abstractmethod
    def get_selectors(self) -> dict[str, str]:
        """Return all DOM selectors for this IDE.

        Returns:
            Dict mapping selector names to CSS selector strings.
        """

    @abstractmethod
    def get_launch_commands(self) -> dict[str, str]:
        """Return per-OS launch commands with CDP flag.

        Returns:
            Dict mapping OS name ('macos', 'windows', 'linux') to launch command string.
        """

    @abstractmethod
    async def scroll_to_bottom(self) -> bool:
        """Scroll the AI chat panel to the bottom.

        IDEs with scroll virtualization need this to ensure the latest
        messages are rendered in the DOM before extraction.

        Returns:
            True if scroll was performed, False if panel not found.
        """

    @abstractmethod
    async def extract_messages(self) -> list[CascadeMessage]:
        """Extract all visible messages from the AI chat panel.

        Returns:
            List of CascadeMessage objects in display order.
        """

    @abstractmethod
    async def detect_approval(self) -> ApprovalRequest | None:
        """Check if an approval dialog is currently visible.

        Returns:
            An ApprovalRequest if approval is needed, None otherwise.
        """

    @abstractmethod
    async def inject_message(self, text: str) -> bool:
        """Type a message into the chat input and submit it.

        Args:
            text: Message text to send.

        Returns:
            True if the message was sent successfully.
        """

    @abstractmethod
    async def click_approve(self) -> bool:
        """Click the approve/allow button on the current approval dialog.

        Returns:
            True if the button was found and clicked.
        """

    @abstractmethod
    async def click_deny(self) -> bool:
        """Click the deny/cancel button on the current approval dialog.

        Returns:
            True if the button was found and clicked.
        """

    @abstractmethod
    async def validate_selectors(self) -> dict[str, bool]:
        """Validate that all critical selectors resolve in the current DOM.

        Returns:
            Dict mapping selector names to True (found) or False (missing).
        """

    @abstractmethod
    async def get_status(self) -> str:
        """Get the current AI assistant status.

        Returns:
            One of: 'idle', 'generating', 'waiting_for_approval', 'unknown'.
        """

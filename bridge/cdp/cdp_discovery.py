"""CDP target discovery — find IDE windows via the CDP HTTP endpoint."""

import json
import logging
from urllib.request import urlopen, Request
from urllib.error import URLError

from bridge.models import CdpTarget

logger = logging.getLogger(__name__)


class CdpDiscovery:
    """Discovers available CDP debug targets from a running IDE instance.

    Connects to the CDP HTTP endpoint (e.g., http://localhost:9222/json)
    and returns a list of available debug targets (IDE windows).
    """

    def __init__(self, host: str = "localhost", port: int = 9222) -> None:
        """Initialize CDP discovery.

        Args:
            host: CDP host address.
            port: CDP port number.
        """
        self.host = host
        self.port = port
        self.base_url = f"http://{host}:{port}"

    def get_version(self) -> dict:
        """Fetch CDP version info from /json/version.

        Returns:
            Dict with Browser, Protocol-Version, User-Agent, webSocketDebuggerUrl.

        Raises:
            ConnectionError: If the CDP endpoint is not reachable.
        """
        url = f"{self.base_url}/json/version"
        logger.debug("Fetching CDP version from %s", url)
        try:
            with urlopen(Request(url), timeout=5) as response:
                data = json.loads(response.read().decode())
                logger.info("CDP connected: %s", data.get("Browser", "unknown"))
                return data
        except URLError as e:
            msg = f"Cannot reach CDP at {url}. Is the IDE running with --remote-debugging-port={self.port}?"
            logger.error(msg)
            raise ConnectionError(msg) from e

    def get_targets(self) -> list[CdpTarget]:
        """Fetch all available CDP targets from /json.

        Returns:
            List of CdpTarget objects representing IDE windows and workers.

        Raises:
            ConnectionError: If the CDP endpoint is not reachable.
        """
        url = f"{self.base_url}/json"
        logger.debug("Fetching CDP targets from %s", url)
        try:
            with urlopen(Request(url), timeout=5) as response:
                raw_targets = json.loads(response.read().decode())
        except URLError as e:
            msg = f"Cannot reach CDP at {url}."
            logger.error(msg)
            raise ConnectionError(msg) from e

        targets = [CdpTarget.from_json(t) for t in raw_targets]
        logger.info("Found %d CDP targets", len(targets))
        for target in targets:
            logger.debug("  Target: type=%s title='%s' id=%s", target.target_type, target.title, target.id)
        return targets

    def get_page_targets(self) -> list[CdpTarget]:
        """Fetch only 'page' type targets (IDE windows).

        Returns:
            List of CdpTarget objects with type='page'.
        """
        return [t for t in self.get_targets() if t.target_type == "page"]

    def find_target_by_workspace(self, workspace_name: str) -> CdpTarget | None:
        """Find a CDP target by workspace name.

        Args:
            workspace_name: Workspace name to search for (case-insensitive substring match).

        Returns:
            Matching CdpTarget, or None if not found.
        """
        pages = self.get_page_targets()
        workspace_lower = workspace_name.lower()
        for target in pages:
            if workspace_lower in target.workspace_name.lower():
                logger.info("Found target for workspace '%s': %s", workspace_name, target.title)
                return target
        logger.warning("No target found for workspace '%s'. Available: %s",
                        workspace_name, [t.workspace_name for t in pages])
        return None

    def is_available(self) -> bool:
        """Check if the CDP endpoint is reachable.

        Returns:
            True if the endpoint responds, False otherwise.
        """
        try:
            self.get_version()
            return True
        except ConnectionError:
            return False

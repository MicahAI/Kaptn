"""Tests for CdpDiscovery — target discovery via CDP HTTP endpoint."""

import json
from unittest.mock import patch, MagicMock

import pytest

from bridge.cdp.cdp_discovery import CdpDiscovery
from bridge.models import CdpTarget


class TestCdpDiscovery:
    """Tests for the CdpDiscovery class."""

    def setup_method(self):
        """Create a discovery instance for each test."""
        self.discovery = CdpDiscovery(host="localhost", port=9222)

    def test_init_sets_base_url(self):
        """Base URL is correctly constructed from host and port."""
        assert self.discovery.base_url == "http://localhost:9222"

    def test_init_custom_host_port(self):
        """Custom host and port are respected."""
        d = CdpDiscovery(host="192.168.1.100", port=9333)
        assert d.base_url == "http://192.168.1.100:9333"

    @patch("bridge.cdp.cdp_discovery.urlopen")
    def test_get_version_success(self, mock_urlopen, sample_cdp_version):
        """get_version returns parsed version data on success."""
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(sample_cdp_version).encode()
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_response

        result = self.discovery.get_version()
        assert result["Browser"] == "Chrome/142.0.7444.235"
        assert "webSocketDebuggerUrl" in result

    @patch("bridge.cdp.cdp_discovery.urlopen")
    def test_get_version_connection_error(self, mock_urlopen):
        """get_version raises ConnectionError when endpoint is unreachable."""
        from urllib.error import URLError
        mock_urlopen.side_effect = URLError("Connection refused")

        with pytest.raises(ConnectionError, match="Cannot reach CDP"):
            self.discovery.get_version()

    @patch("bridge.cdp.cdp_discovery.urlopen")
    def test_get_targets_success(self, mock_urlopen, sample_cdp_targets):
        """get_targets returns list of CdpTarget objects."""
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(sample_cdp_targets).encode()
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_response

        targets = self.discovery.get_targets()
        assert len(targets) == 3
        assert all(isinstance(t, CdpTarget) for t in targets)
        assert targets[0].workspace_name == "Kaptn"

    @patch("bridge.cdp.cdp_discovery.urlopen")
    def test_get_page_targets_filters_workers(self, mock_urlopen, sample_cdp_targets):
        """get_page_targets returns only page-type targets."""
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(sample_cdp_targets).encode()
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_response

        pages = self.discovery.get_page_targets()
        assert len(pages) == 2
        assert all(t.target_type == "page" for t in pages)

    @patch("bridge.cdp.cdp_discovery.urlopen")
    def test_find_target_by_workspace_found(self, mock_urlopen, sample_cdp_targets):
        """find_target_by_workspace returns matching target."""
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(sample_cdp_targets).encode()
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_response

        target = self.discovery.find_target_by_workspace("Kaptn")
        assert target is not None
        assert target.workspace_name == "Kaptn"

    @patch("bridge.cdp.cdp_discovery.urlopen")
    def test_find_target_by_workspace_case_insensitive(self, mock_urlopen, sample_cdp_targets):
        """find_target_by_workspace is case-insensitive."""
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(sample_cdp_targets).encode()
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_response

        target = self.discovery.find_target_by_workspace("kaptn")
        assert target is not None

    @patch("bridge.cdp.cdp_discovery.urlopen")
    def test_find_target_by_workspace_not_found(self, mock_urlopen, sample_cdp_targets):
        """find_target_by_workspace returns None when no match."""
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(sample_cdp_targets).encode()
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_response

        target = self.discovery.find_target_by_workspace("NonExistent")
        assert target is None

    @patch("bridge.cdp.cdp_discovery.urlopen")
    def test_is_available_true(self, mock_urlopen, sample_cdp_version):
        """is_available returns True when endpoint responds."""
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(sample_cdp_version).encode()
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_response

        assert self.discovery.is_available() is True

    @patch("bridge.cdp.cdp_discovery.urlopen")
    def test_is_available_false(self, mock_urlopen):
        """is_available returns False when endpoint is unreachable."""
        from urllib.error import URLError
        mock_urlopen.side_effect = URLError("Connection refused")

        assert self.discovery.is_available() is False


class TestCdpTarget:
    """Tests for the CdpTarget model."""

    def test_from_json(self):
        """from_json correctly parses CDP target data."""
        data = {
            "id": "ABC123",
            "title": "MyProject — User — file.py",
            "type": "page",
            "url": "vscode-file://vscode-app/workbench.html",
            "webSocketDebuggerUrl": "ws://localhost:9222/devtools/page/ABC123",
        }
        target = CdpTarget.from_json(data)
        assert target.id == "ABC123"
        assert target.title == "MyProject — User — file.py"
        assert target.target_type == "page"
        assert target.websocket_url == "ws://localhost:9222/devtools/page/ABC123"

    def test_workspace_name_extracts_first_part(self):
        """workspace_name extracts the first segment before ' — '."""
        target = CdpTarget(
            id="1", title="Kaptn — Mine — README.md",
            target_type="page", url="", websocket_url=""
        )
        assert target.workspace_name == "Kaptn"

    def test_workspace_name_empty_title(self):
        """workspace_name returns empty string for empty title."""
        target = CdpTarget(id="1", title="", target_type="worker", url="", websocket_url="")
        assert target.workspace_name == ""

    def test_workspace_name_no_separator(self):
        """workspace_name returns full title when no ' — ' separator."""
        target = CdpTarget(id="1", title="SimpleTitle", target_type="page", url="", websocket_url="")
        assert target.workspace_name == "SimpleTitle"

"""Unit tests for Firewall Manager."""

from unittest.mock import MagicMock, patch
from core.firewall_manager import FirewallManager
from models.server_config import FirewallInfo, FirewallType
from utils.system import CommandResult


def test_open_ports_dry_run():
    fm = FirewallManager(dry_run=True)
    with patch.object(fm, "detect_firewall", return_value=FirewallInfo(type=FirewallType.UFW, is_active=True)):
        ok, logs = fm.open_ports([8000, 8001], include_standard_web=True)
        assert ok is True
        assert any("80" in log or "8000" in log for log in logs)


def test_firewall_none_detected():
    fm = FirewallManager(dry_run=True)
    with patch.object(fm, "detect_firewall", return_value=FirewallInfo(type=FirewallType.NONE, is_active=False)):
        ok, logs = fm.open_ports([8000])
        assert ok is True
        assert any("No active firewall detected" in log for log in logs)

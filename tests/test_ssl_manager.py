"""Unit tests for SSL Manager."""

from unittest.mock import MagicMock, patch
from core.ssl_manager import SSLManager


def test_certificate_paths():
    ssl_mgr = SSLManager(dry_run=True)
    cert, key = ssl_mgr.get_certificate_paths("api.example.com")
    assert cert == "/etc/letsencrypt/live/api.example.com/fullchain.pem"
    assert key == "/etc/letsencrypt/live/api.example.com/privkey.pem"


def test_invalid_domain_ssl():
    ssl_mgr = SSLManager(dry_run=True)
    ok, logs, cert, key = ssl_mgr.request_certificate("invalid domain name!@#")
    assert ok is False
    assert any("Invalid domain" in log for log in logs)


def test_dry_run_certificate_request():
    ssl_mgr = SSLManager(dry_run=True)
    with patch("utils.dns.DNSHelper.verify_domain_points_to_ip", return_value=(True, "Matched")):
        ok, logs, cert, key = ssl_mgr.request_certificate("example.com", email="admin@example.com")
        assert ok is True
        assert cert == "/etc/letsencrypt/live/example.com/fullchain.pem"
        assert key == "/etc/letsencrypt/live/example.com/privkey.pem"

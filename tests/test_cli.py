"""CLI integration tests using Typer CliRunner."""

from unittest.mock import MagicMock, patch
from typer.testing import CliRunner
from cli.main import app
from models.server_config import FirewallInfo, FirewallType, ServiceStatus
from utils.system import CommandResult

runner = CliRunner()


def test_cli_help():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "nginx-cli" in result.stdout or "Production-Grade" in result.stdout
    assert "setup" in result.stdout
    assert "add-service" in result.stdout
    assert "status" in result.stdout
    assert "list" in result.stdout


def test_cli_preview():
    result = runner.invoke(
        app,
        ["preview", "--project", "test-api", "--port", "9000", "--route", "/api/"],
    )
    assert result.exit_code == 0
    assert "Dry-Run Preview: test-api" in result.stdout
    assert "location /api/ {" in result.stdout
    assert "proxy_pass http://127.0.0.1:9000;" in result.stdout


def test_cli_status():
    with patch("core.firewall_manager.FirewallManager.detect_firewall", return_value=FirewallInfo(type=FirewallType.UFW, is_active=True)), \
         patch("core.service_manager.ServiceManager.get_nginx_status", return_value=ServiceStatus(is_installed=True, is_running=True, is_enabled=True)):
        result = runner.invoke(app, ["status"])
        assert result.exit_code == 0
        assert "System & Environment Diagnostics" in result.stdout
        assert "Operating System" in result.stdout


def test_cli_list():
    result = runner.invoke(app, ["list"])
    assert result.exit_code == 0


def test_cli_setup_dry_run_non_interactive():
    with patch("core.nginx_manager.NginxManager.test_config", return_value=CommandResult(command="nginx -t", returncode=0, stdout="ok", stderr="")):
        result = runner.invoke(
            app,
            [
                "setup",
                "--project", "unit-test-app",
                "--port", "8080",
                "--route", "/",
                "--dry-run",
                "--non-interactive",
            ],
        )
        assert result.exit_code == 0
        assert "Deployment & Configuration Succeeded" in result.stdout
        assert "unit-test-app" in result.stdout


def test_cli_add_service_dry_run():
    with patch("core.nginx_manager.NginxManager.test_config", return_value=CommandResult(command="nginx -t", returncode=0, stdout="ok", stderr="")):
        # First ensure project exists in registry
        runner.invoke(
            app,
            [
                "setup",
                "--project", "test-multi-app",
                "--port", "8000",
                "--route", "/",
                "--dry-run",
                "--non-interactive",
            ],
        )
        result = runner.invoke(
            app,
            [
                "add-service",
                "--project", "test-multi-app",
                "--path", "/api2/",
                "--port", "8002",
                "--dry-run",
            ],
        )
        assert result.exit_code == 0
        assert "Added route '/api2/'" in result.stdout or "Deployment & Configuration Succeeded" in result.stdout


def test_cli_remove_dry_run():
    with patch("core.nginx_manager.NginxManager.test_config", return_value=CommandResult(command="nginx -t", returncode=0, stdout="ok", stderr="")):
        result = runner.invoke(app, ["remove", "test-multi-app", "--dry-run"])
        assert result.exit_code == 0
        assert "successfully decommissioned" in result.stdout


def test_cli_enable_ssl_by_project_code_dry_run():
    with patch("core.nginx_manager.NginxManager.test_config", return_value=CommandResult(command="nginx -t", returncode=0, stdout="ok", stderr="")):
        # Ensure project exists
        runner.invoke(
            app,
            [
                "setup",
                "--project", "ssl-test-app",
                "--port", "8000",
                "--route", "/",
                "--dry-run",
                "--non-interactive",
            ],
        )
        # Enable SSL using project code or name
        result = runner.invoke(
            app,
            [
                "enable-ssl",
                "--project", "ssl-test-app",
                "--self-signed",
                "--dry-run",
                "--non-interactive",
            ],
        )
        assert result.exit_code == 0
        assert "SSL successfully enabled for Project CODE" in result.stdout or "Deployment & Configuration Succeeded" in result.stdout


def test_cli_menu_exit():
    result = runner.invoke(app, ["menu"], input="9\n")
    assert result.exit_code == 0
    assert "Please select an action by number" in result.stdout
    assert "Goodbye!" in result.stdout


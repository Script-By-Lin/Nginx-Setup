"""CLI integration tests using Typer CliRunner."""

from unittest.mock import MagicMock, patch
from typer.testing import CliRunner
from cli.main import app
from models.server_config import FirewallInfo, FirewallType, ServiceStatus
from utils.storage import StateManager
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
        assert "successfully added to Project CODE" in result.stdout or "Route '/api2/'" in result.stdout or "Deployment & Configuration Succeeded" in result.stdout


def test_cli_remove_dry_run():
    with patch("core.nginx_manager.NginxManager.test_config", return_value=CommandResult(command="nginx -t", returncode=0, stdout="ok", stderr="")):
        result = runner.invoke(app, ["remove", "test-multi-app", "--dry-run"])
        assert result.exit_code == 0
        assert "successfully decommissioned" in result.stdout


def test_cli_remove_by_project_code_dry_run():
    with patch("core.nginx_manager.NginxManager.test_config", return_value=CommandResult(command="nginx -t", returncode=0, stdout="ok", stderr="")):
        state_mgr = StateManager()
        # 1. Setup project
        runner.invoke(
            app,
            [
                "setup",
                "--project", "code-del-app",
                "--port", "8055",
                "--route", "/",
                "--dry-run",
                "--non-interactive",
            ],
        )
        # 2. Check project was saved in registry and has a code
        proj = state_mgr.get_project("code-del-app")
        assert proj is not None
        proj_code = proj.project_code

        # 3. Remove specifically by Project Code
        remove_res = runner.invoke(app, ["remove", proj_code, "--dry-run"])
        assert remove_res.exit_code == 0
        assert "successfully decommissioned" in remove_res.stdout

        # 4. Verify project is completely deleted from registry
        assert state_mgr.get_project("code-del-app") is None
        assert state_mgr.get_project(proj_code) is None


def test_cli_inspect():
    result = runner.invoke(app, ["inspect"])
    assert result.exit_code == 0


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


def test_cli_service_lifecycle():
    # 1. Setup service
    setup_res = runner.invoke(
        app,
        [
            "service-setup",
            "--name", "fastapi-unit",
            "--desc", "FastAPI App",
            "--user", "nginx",
            "--working-dir", "/home/bit/app",
            "--exec", "/usr/bin/uvicorn main:app --host 127.0.0.1 --port 8000",
            "--dry-run",
            "--non-interactive",
        ],
    )
    assert setup_res.exit_code == 0
    assert "successfully deployed" in setup_res.stdout or "fastapi-unit.service" in setup_res.stdout

    # 2. List services
    list_res = runner.invoke(app, ["service-list"])
    assert list_res.exit_code == 0
    assert "fastapi-unit" in list_res.stdout

    # 3. Control service
    ctrl_res = runner.invoke(
        app,
        [
            "service-control",
            "--service", "fastapi-unit",
            "--action", "restart",
            "--dry-run",
        ],
    )
    assert ctrl_res.exit_code == 0

    # 4. Remove service
    rem_res = runner.invoke(
        app,
        [
            "service-remove",
            "--service", "fastapi-unit",
            "--dry-run",
            "--non-interactive",
        ],
    )
    assert rem_res.exit_code == 0
    assert "removed" in rem_res.stdout or "decommissioned" in rem_res.stdout


def test_cli_menu_exit():
    result = runner.invoke(app, ["menu"], input="14\n")
    assert result.exit_code == 0
    assert "Please select an action by number" in result.stdout
    assert "Goodbye!" in result.stdout


def test_cli_menu_loop_return():
    # Simulate choosing Option 4 (List Projects), answering 'y' to return to menu, then choosing 14 (Exit)
    result = runner.invoke(app, ["menu"], input="4\ny\n14\n")
    assert result.exit_code == 0
    assert "projects" in result.stdout.lower() or "registered" in result.stdout.lower()
    assert "Goodbye!" in result.stdout







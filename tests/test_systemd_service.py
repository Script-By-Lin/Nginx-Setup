"""Tests for systemd service generation, lifecycle management, auto-enable, and persistence."""

from unittest.mock import MagicMock, patch
import pytest
from models.server_config import SystemdServiceConfig, SystemdServiceState
from core.service_manager import ServiceManager
from utils.storage import StateManager
from utils.system import CommandResult


@pytest.fixture
def temp_storage(tmp_path):
    db_file = tmp_path / "test_services.db"
    return StateManager(custom_path=str(db_file))


def test_systemd_config_model():
    cfg = SystemdServiceConfig(
        service_name="fastapi.service",
        description="FastAPI App",
        user="nginx",
        working_dir="/home/user/app",
        exec_start="/usr/bin/uvicorn main:app --host 127.0.0.1 --port 8000",
        restart="always",
    )
    assert cfg.service_name == "fastapi"  # clean_service_name validator strips .service
    assert cfg.description == "FastAPI App"
    assert cfg.user == "nginx"
    assert cfg.working_dir == "/home/user/app"
    assert "uvicorn" in cfg.exec_start


def test_render_systemd_unit():
    mgr = ServiceManager(dry_run=True)
    cfg = SystemdServiceConfig(
        service_name="fastapi",
        description="FastAPI App",
        user="nginx",
        working_dir="/home/user/app",
        exec_start="/usr/bin/uvicorn main:app --host 127.0.0.1 --port 8000",
        restart="always",
        restart_sec=5,
    )
    unit_str = mgr.render_systemd_unit(cfg)
    assert "[Unit]" in unit_str
    assert "Description=FastAPI App" in unit_str
    assert "After=network.target" in unit_str
    assert "[Service]" in unit_str
    assert "User=nginx" in unit_str
    assert "WorkingDirectory=/home/user/app" in unit_str
    assert "ExecStart=/usr/bin/uvicorn main:app --host 127.0.0.1 --port 8000" in unit_str
    assert "Restart=always" in unit_str
    assert "RestartSec=5" in unit_str
    assert "[Install]" in unit_str
    assert "WantedBy=multi-user.target" in unit_str


def test_create_systemd_service_dry_run():
    mgr = ServiceManager(dry_run=True)
    cfg = SystemdServiceConfig(
        service_name="fastapi",
        description="FastAPI App",
        user="nginx",
        working_dir="/home/user/app",
        exec_start="/usr/bin/uvicorn main:app --host 127.0.0.1 --port 8000",
    )
    success, logs, path = mgr.create_systemd_service(cfg)
    assert success is True
    assert path == "/etc/systemd/system/fastapi.service"
    assert any("written" in l or "Executed" in l or "Enabled" in l for l in logs)


def test_remove_systemd_service_dry_run():
    mgr = ServiceManager(dry_run=True)
    success, logs = mgr.remove_systemd_service("fastapi.service")
    assert success is True
    assert any("Stopped" in l for l in logs)
    assert any("Disabled" in l for l in logs)
    assert any("daemon-reload" in l for l in logs)


def test_storage_systemd_services(temp_storage):
    svc = SystemdServiceState(
        service_name="fastapi",
        description="FastAPI App",
        user="nginx",
        working_dir="/home/user/app",
        exec_start="/usr/bin/uvicorn main:app --host 127.0.0.1 --port 8000",
        restart="always",
        service_file_path="/etc/systemd/system/fastapi.service",
        created_at="2026-09-11 20:00:00",
        updated_at="2026-09-11 20:00:00",
        is_enabled=True,
        is_active=True,
    )

    temp_storage.save_service(svc)

    all_svcs = temp_storage.list_services()
    assert len(all_svcs) == 1
    assert all_svcs[0].service_name == "fastapi"
    assert all_svcs[0].description == "FastAPI App"

    # Query by name
    found = temp_storage.get_service("fastapi")
    assert found is not None
    assert found.user == "nginx"

    # Query by name with .service
    found_ext = temp_storage.get_service("fastapi.service")
    assert found_ext is not None
    assert found_ext.service_name == "fastapi"

    # Query by index '1'
    found_idx = temp_storage.get_service("1")
    assert found_idx is not None
    assert found_idx.service_name == "fastapi"

    # Delete
    del_ok = temp_storage.delete_service("fastapi")
    assert del_ok is True
    assert len(temp_storage.list_services()) == 0


def test_service_manager_control():
    mgr = ServiceManager(dry_run=True)
    with patch("core.service_manager.run_command", return_value=CommandResult(command="systemctl", returncode=0, stdout="active", stderr="")):
        ok, out = mgr.control_systemd_service("fastapi", "restart")
        assert ok is True
        assert "restart" in out


def test_systemd_config_with_option_info():
    import typer
    # Simulates Typer passing OptionInfo default objects when called directly in Python
    cfg = SystemdServiceConfig(
        service_name=typer.Option("my-api", help="help"),
        description=typer.Option("My API Service", help="help"),
        user=typer.Option("nginx", help="help"),
        working_dir=typer.Option("/home/user", help="help"),
        exec_start=typer.Option("/usr/bin/python3 app.py", help="help"),
        restart=typer.Option("always", help="help"),
    )
    assert cfg.service_name == "my-api"
    assert cfg.description == "My API Service"
    assert cfg.user == "nginx"
    assert cfg.working_dir == "/home/user"
    assert cfg.exec_start == "/usr/bin/python3 app.py"
    assert cfg.restart == "always"


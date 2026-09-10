"""Unit tests for SQLite persistent storage manager."""

import json
from pathlib import Path
from models.server_config import ProjectState, RouteConfig
from utils.storage import StateManager


def test_sqlite_storage_lifecycle(tmp_path: Path):
    db_file = tmp_path / "test_projects.db"
    mgr = StateManager(custom_path=str(db_file))

    # 1. Initially empty
    assert mgr.list_projects() == []
    assert mgr.get_project("non_existent") is None

    # 2. Add first project
    p1 = ProjectState(
        project_code="SE-001",
        project_name="api-gateway",
        domain="api.example.com",
        config_file_path="/etc/nginx/conf.d/api-gateway.conf",
        created_at="2026-09-11 12:00:00",
        updated_at="2026-09-11 12:00:00",
        ssl_enabled=False,
        routes=[
            RouteConfig(name="primary", path="/", backend_host="127.0.0.1", backend_port=8000)
        ],
    )
    mgr.save_project(p1)

    # 3. Verify retrieval by various identifiers
    retrieved_by_name = mgr.get_project("api-gateway")
    assert retrieved_by_name is not None
    assert retrieved_by_name.project_name == "api-gateway"
    assert retrieved_by_name.project_code == "SE-001"
    assert len(retrieved_by_name.routes) == 1

    retrieved_by_code = mgr.get_project("SE-001")
    assert retrieved_by_code is not None
    assert retrieved_by_code.project_name == "api-gateway"

    retrieved_by_code_lower = mgr.get_project("se-001")
    assert retrieved_by_code_lower is not None
    assert retrieved_by_code_lower.project_name == "api-gateway"

    retrieved_by_index = mgr.get_project("1")
    assert retrieved_by_index is not None
    assert retrieved_by_index.project_name == "api-gateway"

    # 4. Add second project and test sequential code auto-generation
    p2 = ProjectState(
        project_name="auth-service",
        domain="auth.example.com",
        config_file_path="/etc/nginx/conf.d/auth-service.conf",
        created_at="2026-09-11 12:05:00",
        updated_at="2026-09-11 12:05:00",
        ssl_enabled=True,
        ssl_type="letsencrypt",
        ssl_cert_path="/etc/letsencrypt/live/auth.example.com/fullchain.pem",
        ssl_key_path="/etc/letsencrypt/live/auth.example.com/privkey.pem",
        routes=[
            RouteConfig(name="auth", path="/auth/", backend_host="127.0.0.1", backend_port=8001)
        ],
    )
    mgr.save_project(p2)

    all_projs = mgr.list_projects()
    assert len(all_projs) == 2
    assert all_projs[1].project_code == "SE-002"

    # 5. Simulate closing and reopening VM (new StateManager instance pointing to same SQLite DB)
    mgr_reopened = StateManager(custom_path=str(db_file))
    reopened_projs = mgr_reopened.list_projects()
    assert len(reopened_projs) == 2
    assert reopened_projs[0].project_name == "api-gateway"
    assert reopened_projs[1].project_name == "auth-service"
    assert reopened_projs[1].ssl_enabled is True
    assert reopened_projs[1].ssl_cert_path == "/etc/letsencrypt/live/auth.example.com/fullchain.pem"

    # 6. Update project SSL status (enable SSL on api-gateway)
    p1_updated = mgr_reopened.get_project("SE-001")
    assert p1_updated is not None
    p1_updated.ssl_enabled = True
    p1_updated.ssl_type = "self-signed"
    p1_updated.ssl_cert_path = "/etc/ssl/certs/ip_192.168.1.150_selfsigned.crt"
    mgr_reopened.save_project(p1_updated)

    re_verified = mgr_reopened.get_project("api-gateway")
    assert re_verified.ssl_enabled is True
    assert re_verified.ssl_type == "self-signed"
    assert re_verified.project_code == "SE-001"

    # 7. Delete project
    deleted = mgr_reopened.delete_project("SE-002")
    assert deleted is True
    assert len(mgr_reopened.list_projects()) == 1
    assert mgr_reopened.get_project("auth-service") is None


def test_sqlite_auto_migration_from_json(tmp_path: Path):
    # Setup legacy json file
    state_dir = tmp_path / "nginx-setup"
    state_dir.mkdir(parents=True, exist_ok=True)
    json_file = state_dir / "projects.json"
    db_file = state_dir / "projects.db"

    legacy_data = {
        "legacy-app": {
            "project_code": "SE-001",
            "project_name": "legacy-app",
            "domain": "legacy.local",
            "config_file_path": "/etc/nginx/conf.d/legacy-app.conf",
            "created_at": "2026-09-10 10:00:00",
            "updated_at": "2026-09-10 10:00:00",
            "ssl_enabled": False,
            "ssl_type": "letsencrypt",
            "listen_port": 80,
            "ssl_port": 443,
            "routes": [
                {
                    "name": "primary",
                    "path": "/",
                    "backend_host": "127.0.0.1",
                    "backend_port": 5000,
                    "websocket": True,
                    "client_max_body_size": "50M",
                    "proxy_read_timeout": 300,
                    "proxy_connect_timeout": 60,
                    "proxy_send_timeout": 300,
                    "custom_headers": {},
                    "strip_path_prefix": False
                }
            ]
        }
    }
    with open(json_file, "w", encoding="utf-8") as f:
        json.dump(legacy_data, f, indent=2)

    # Initialize StateManager with this db_path in the same dir
    mgr = StateManager(custom_path=str(db_file))
    migrated_projects = mgr.list_projects()

    assert len(migrated_projects) == 1
    assert migrated_projects[0].project_name == "legacy-app"
    assert migrated_projects[0].project_code == "SE-001"
    assert migrated_projects[0].routes[0].backend_port == 5000

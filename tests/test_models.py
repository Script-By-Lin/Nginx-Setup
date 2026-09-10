"""Unit tests for Pydantic models."""

import pytest
from models.server_config import (
    FirewallInfo,
    FirewallType,
    OSFamily,
    OSInfo,
    PackageManager,
    ProjectState,
    RouteConfig,
    ServerConfig,
    ServiceStatus,
)


def test_route_config_path_validation():
    # Automatically prepends leading slash
    route = RouteConfig(name="api", path="api1/", backend_port=8001)
    assert route.path == "/api1/"
    assert route.target_url == "http://127.0.0.1:8001"

    # Test path strip prefix
    route_strip = RouteConfig(name="api", path="/api1/", backend_port=8001, strip_path_prefix=True)
    assert route_strip.target_url == "http://127.0.0.1:8001/"


def test_route_config_invalid_port():
    with pytest.raises(ValueError):
        RouteConfig(name="invalid", path="/", backend_port=70000)

    with pytest.raises(ValueError):
        RouteConfig(name="invalid", path="/", backend_port=0)


def test_server_config_domain_and_server_name():
    # When domain provided, server_name should match domain
    cfg1 = ServerConfig(project_name="my-app", domain="example.com")
    assert cfg1.server_name == "example.com"

    # When no domain provided, server_name defaults to _
    cfg2 = ServerConfig(project_name="my-app")
    assert cfg2.server_name == "_"


def test_project_state_serialization():
    route = RouteConfig(name="root", path="/", backend_port=8000)
    state = ProjectState(
        project_name="fastapi_app",
        domain="api.test.com",
        config_file_path="/etc/nginx/conf.d/fastapi_app.conf",
        created_at="2026-09-11 12:00:00",
        updated_at="2026-09-11 12:00:00",
        routes=[route],
        ssl_enabled=True,
    )
    data = state.model_dump()
    assert data["project_name"] == "fastapi_app"
    assert data["ssl_enabled"] is True
    assert len(data["routes"]) == 1

    # Deserialization test
    loaded = ProjectState.model_validate(data)
    assert loaded.project_name == state.project_name
    assert loaded.routes[0].backend_port == 8000

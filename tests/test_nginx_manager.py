"""Unit tests for Nginx Manager and Jinja2 template rendering."""

import tempfile
from pathlib import Path
from core.nginx_manager import NginxManager
from models.server_config import RouteConfig, ServerConfig
from utils.backup import BackupManager


def test_render_http_single_route():
    mgr = NginxManager(dry_run=True)
    config = ServerConfig(
        project_name="fastapi_demo",
        domain=None,
        server_name="_",
        listen_port=80,
        ssl_enabled=False,
        routes=[
            RouteConfig(
                name="main",
                path="/",
                backend_host="127.0.0.1",
                backend_port=8000,
                websocket=True,
            )
        ],
    )
    rendered = mgr.render_config(config)

    assert "server {" in rendered
    assert "listen 80;" in rendered
    assert "server_name _;" in rendered
    assert "location / {" in rendered
    assert "proxy_pass http://127.0.0.1:8000;" in rendered
    assert "proxy_set_header Upgrade $http_upgrade;" in rendered
    assert "proxy_set_header Host $host;" in rendered


def test_render_multi_service_routes():
    mgr = NginxManager(dry_run=True)
    config = ServerConfig(
        project_name="multi_svc",
        domain="api.mycompany.com",
        routes=[
            RouteConfig(name="frontend", path="/", backend_port=3000),
            RouteConfig(name="auth_service", path="/auth/", backend_port=8001),
            RouteConfig(name="payment_service", path="/payment/", backend_port=8002),
        ],
    )
    rendered = mgr.render_config(config)

    assert "server_name api.mycompany.com;" in rendered
    assert "location / {" in rendered
    assert "proxy_pass http://127.0.0.1:3000;" in rendered
    assert "location /auth/ {" in rendered
    assert "proxy_pass http://127.0.0.1:8001;" in rendered
    assert "location /payment/ {" in rendered
    assert "proxy_pass http://127.0.0.1:8002;" in rendered


def test_render_ssl_https_redirect():
    mgr = NginxManager(dry_run=True)
    config = ServerConfig(
        project_name="secure_app",
        domain="secure.example.com",
        ssl_enabled=True,
        ssl_redirect=True,
        ssl_cert_path="/etc/letsencrypt/live/secure.example.com/fullchain.pem",
        ssl_key_path="/etc/letsencrypt/live/secure.example.com/privkey.pem",
        routes=[RouteConfig(name="root", path="/", backend_port=8000)],
    )
    rendered = mgr.render_config(config)

    assert "return 301 https://$host$request_uri;" in rendered
    assert "listen 443 ssl http2;" in rendered
    assert "ssl_certificate /etc/letsencrypt/live/secure.example.com/fullchain.pem;" in rendered
    assert "ssl_certificate_key /etc/letsencrypt/live/secure.example.com/privkey.pem;" in rendered
    assert "ssl_protocols TLSv1.2 TLSv1.3;" in rendered
    assert "Strict-Transport-Security" in rendered


def test_backup_and_rollback():
    bm = BackupManager(dry_run=False)
    with tempfile.NamedTemporaryFile("w", delete=False) as tf:
        tf.write("original content")
        tf_path = tf.name

    try:
        # Write new content (should backup old)
        backup_path = bm.write_file(tf_path, "new content")
        assert backup_path is not None
        assert Path(backup_path).exists()

        with open(tf_path, "r") as f:
            assert f.read() == "new content"

        # Rollback
        bm.rollback(tf_path, backup_path)
        with open(tf_path, "r") as f:
            assert f.read() == "original content"

    finally:
        Path(tf_path).unlink(missing_ok=True)
        if backup_path:
            Path(backup_path).unlink(missing_ok=True)

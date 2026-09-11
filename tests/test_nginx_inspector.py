"""Unit tests for NginxInspector configuration scanner and port detector."""

from pathlib import Path
from core.nginx_inspector import NginxInspector


def test_nginx_inspector_scan(tmp_path: Path):
    nginx_root = tmp_path / "nginx"
    conf_d = nginx_root / "conf.d"
    conf_d.mkdir(parents=True, exist_ok=True)

    # Create main nginx.conf
    main_conf = nginx_root / "nginx.conf"
    main_conf.write_text(
        """
        events { worker_connections 1024; }
        http {
            include conf.d/*.conf;
            server {
                listen 80 default_server;
                listen [::]:80;
                server_name _;
                location / {
                    return 404;
                }
            }
        }
        """,
        encoding="utf-8",
    )

    # Create conf.d/api.conf
    api_conf = conf_d / "api.conf"
    api_conf.write_text(
        """
        server {
            listen 80;
            listen 443 ssl http2;
            server_name api.example.com www.api.example.com;

            ssl_certificate /etc/letsencrypt/live/api.example.com/fullchain.pem;
            ssl_certificate_key /etc/letsencrypt/live/api.example.com/privkey.pem;

            location / {
                proxy_pass http://127.0.0.1:8000;
            }

            location /auth/ {
                proxy_pass http://127.0.0.1:8001;
            }
        }
        """,
        encoding="utf-8",
    )

    # Create conf.d/custom_port.conf
    custom_conf = conf_d / "custom_port.conf"
    custom_conf.write_text(
        """
        server {
            listen 9090;
            server_name internal.local;

            location /metrics {
                proxy_pass http://127.0.0.1:9100;
            }
        }
        """,
        encoding="utf-8",
    )

    inspector = NginxInspector(root_conf_dir=str(nginx_root))
    scan = inspector.scan_all_configs()

    # 1. Config files detected
    assert len(scan.config_files_scanned) == 3
    assert str(main_conf) in scan.config_files_scanned
    assert str(api_conf) in scan.config_files_scanned
    assert str(custom_conf) in scan.config_files_scanned

    # 2. Ports detected across all files
    assert 80 in scan.all_listening_ports
    assert 443 in scan.all_listening_ports
    assert 9090 in scan.all_listening_ports

    # 3. Server names detected
    assert "api.example.com" in scan.all_server_names
    assert "www.api.example.com" in scan.all_server_names
    assert "internal.local" in scan.all_server_names

    # 4. Proxy pass targets detected
    assert "http://127.0.0.1:8000" in scan.all_proxy_targets
    assert "http://127.0.0.1:8001" in scan.all_proxy_targets
    assert "http://127.0.0.1:9100" in scan.all_proxy_targets

    # 5. Check helper methods
    in_use_80, matches_80 = inspector.is_port_in_use_by_nginx(80)
    assert in_use_80 is True
    assert len(matches_80) >= 2

    in_use_9999, matches_9999 = inspector.is_port_in_use_by_nginx(9999)
    assert in_use_9999 is False
    assert matches_9999 == []

    sn_found, sn_matches = inspector.is_server_name_configured("api.example.com")
    assert sn_found is True
    assert len(sn_matches) == 1

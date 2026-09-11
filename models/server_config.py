"""Pydantic models for Nginx + SSL configuration management."""

from enum import Enum
from typing import Dict, List, Optional
from pydantic import BaseModel, Field, field_validator, model_validator


class OSFamily(str, Enum):
    DEBIAN = "debian"
    RHEL = "rhel"
    ARCH = "arch"
    ALPINE = "alpine"
    SUSE = "suse"
    UNKNOWN = "unknown"


class PackageManager(str, Enum):
    APT = "apt"
    DNF = "dnf"
    YUM = "yum"
    PACMAN = "pacman"
    APK = "apk"
    ZYPPER = "zypper"
    UNKNOWN = "unknown"


class FirewallType(str, Enum):
    UFW = "ufw"
    FIREWALLD = "firewalld"
    IPTABLES = "iptables"
    NFTABLES = "nftables"
    NONE = "none"


class RouteConfig(BaseModel):
    """Configuration for an individual backend location route."""
    name: str = "default"
    path: str = Field(default="/", description="Nginx location path, e.g. / or /api1/")
    backend_host: str = Field(default="127.0.0.1", description="Backend target host")
    backend_port: int = Field(default=8000, ge=1, le=65535, description="Backend target port")
    backend_executable: Optional[str] = Field(
        default=None,
        description="Path or startup command for the backend service (e.g. uvicorn main:app)"
    )
    websocket: bool = Field(default=True, description="Enable WebSocket proxy headers")
    client_max_body_size: str = Field(default="50M", description="Max body size for this route")
    proxy_read_timeout: int = Field(default=300, description="Proxy read timeout in seconds")
    proxy_connect_timeout: int = Field(default=60, description="Proxy connect timeout in seconds")
    proxy_send_timeout: int = Field(default=300, description="Proxy send timeout in seconds")
    custom_headers: Dict[str, str] = Field(default_factory=dict, description="Custom HTTP headers to set")
    strip_path_prefix: bool = Field(
        default=False,
        description="Whether to strip route prefix in proxy_pass (e.g. /api1/ -> /)"
    )

    @field_validator("path")
    @classmethod
    def validate_path(cls, v: str) -> str:
        v = v.strip()
        if not v.startswith("/"):
            v = "/" + v
        return v

    @property
    def target_url(self) -> str:
        """Returns the full upstream URL."""
        if self.path != "/" and self.strip_path_prefix:
            return f"http://{self.backend_host}:{self.backend_port}/"
        return f"http://{self.backend_host}:{self.backend_port}"


class ServerConfig(BaseModel):
    """Full Nginx Server VirtualHost configuration."""
    project_name: str = Field(..., description="Unique project name")
    domain: Optional[str] = Field(default=None, description="Domain name (e.g. example.com)")
    server_name: str = Field(default="_", description="server_name directive value")
    listen_port: int = Field(default=80, ge=1, le=65535)
    ssl_listen_port: int = Field(default=443, ge=1, le=65535)
    ssl_enabled: bool = Field(default=False)
    ssl_type: str = Field(default="letsencrypt", description="SSL provider type: letsencrypt or self-signed")
    ssl_email: Optional[str] = Field(default=None, description="Email for Let's Encrypt / Certbot")
    ssl_cert_path: Optional[str] = Field(default=None, description="Path to SSL fullchain.pem")
    ssl_key_path: Optional[str] = Field(default=None, description="Path to SSL privkey.pem")
    ssl_redirect: bool = Field(default=True, description="Redirect HTTP (80) to HTTPS (443)")
    client_max_body_size: str = Field(default="50M")
    enable_gzip: bool = Field(default=True)
    enable_http2: bool = Field(default=True)
    routes: List[RouteConfig] = Field(default_factory=list)
    access_log: Optional[str] = None
    error_log: Optional[str] = None
    config_file_path: Optional[str] = None

    @model_validator(mode="after")
    def sync_server_name(self) -> "ServerConfig":
        if self.domain and self.domain.strip() and (not self.server_name or self.server_name == "_"):
            self.server_name = self.domain.strip()
        return self


class OSInfo(BaseModel):
    """Information about detected operating system and paths."""
    name: str
    pretty_name: str
    distro_id: str
    version_id: str = ""
    family: OSFamily
    package_manager: PackageManager
    nginx_conf_dir: str
    nginx_sites_available_dir: Optional[str] = None
    nginx_sites_enabled_dir: Optional[str] = None
    use_symlinks: bool = False
    service_manager: str = "systemd"


class FirewallInfo(BaseModel):
    """Information about active firewall system."""
    type: FirewallType
    is_active: bool = False
    open_ports: List[int] = Field(default_factory=list)


class ServiceStatus(BaseModel):
    """Status of a system service (e.g. Nginx)."""
    name: str = "nginx"
    is_installed: bool = False
    is_running: bool = False
    is_enabled: bool = False
    version: Optional[str] = None
    active_state: Optional[str] = None


class ProjectState(BaseModel):
    """Persisted state of a configured project."""
    project_code: str = Field(default="SE-001", description="Formatted project identifier code, e.g. SE-001")
    project_name: str
    domain: Optional[str] = None
    config_file_path: str
    created_at: str
    updated_at: str
    routes: List[RouteConfig] = Field(default_factory=list)
    ssl_enabled: bool = False
    ssl_type: str = "letsencrypt"
    ssl_cert_path: Optional[str] = None
    ssl_key_path: Optional[str] = None
    ssl_email: Optional[str] = None
    listen_port: int = 80
    ssl_port: int = 443


class SystemdServiceConfig(BaseModel):
    """Configuration for generating a systemd service unit file."""
    service_name: str = Field(..., description="Service unit name without .service extension, e.g. fastapi")
    description: str = Field(default="FastAPI App", description="Service Description")
    user: str = Field(default="nginx", description="Execution user, e.g. nginx, www-data, root")
    group: Optional[str] = Field(default=None, description="Execution group")
    working_dir: str = Field(..., description="Application working directory")
    exec_start: str = Field(..., description="Full startup command, e.g. /usr/bin/uvicorn main:app --host 127.0.0.1 --port 8000")
    restart: str = Field(default="always", description="Restart policy: always, on-failure, no")
    restart_sec: int = Field(default=3, description="RestartSec timeout")
    environment: Dict[str, str] = Field(default_factory=dict, description="Environment variables")
    service_file_path: Optional[str] = None

    @field_validator("service_name")
    @classmethod
    def clean_service_name(cls, v: str) -> str:
        v = v.strip()
        if v.endswith(".service"):
            v = v[:-8]
        return v


class SystemdServiceState(BaseModel):
    """Persisted state and metadata for managed systemd services."""
    service_name: str
    description: str
    user: str
    working_dir: str
    exec_start: str
    restart: str = "always"
    service_file_path: str
    created_at: str
    updated_at: str
    is_enabled: bool = True
    is_active: bool = False


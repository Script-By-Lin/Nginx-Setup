"""Core package for Nginx and system configuration automation."""

from core.os_detector import OSDetector
from core.installer import PackageInstaller
from core.nginx_manager import NginxManager
from core.ssl_manager import SSLManager
from core.firewall_manager import FirewallManager
from core.service_manager import ServiceManager

__all__ = [
    "OSDetector",
    "PackageInstaller",
    "NginxManager",
    "SSLManager",
    "FirewallManager",
    "ServiceManager",
]

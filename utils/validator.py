"""Validation utilities for ports, executables, paths, domains, and routes."""

import ipaddress
import os
import re
import socket
from pathlib import Path
from typing import Optional, Tuple
import psutil


class PortValidator:
    """Validator for network ports and process bindings."""

    @staticmethod
    def is_valid_port(port: int) -> bool:
        """Check if port is within valid TCP range 1-65535."""
        return isinstance(port, int) and 1 <= port <= 65535

    @staticmethod
    def is_port_listening(port: int, host: str = "127.0.0.1", timeout: float = 1.0) -> bool:
        """Check if a service is actively listening on host:port."""
        try:
            with socket.create_connection((host, port), timeout=timeout):
                return True
        except (socket.timeout, ConnectionRefusedError, OSError):
            return False

    @staticmethod
    def is_port_available(port: int, host: str = "0.0.0.0") -> bool:
        """Check if port can be bound to (i.e. is currently free)."""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                s.bind((host, port))
                return True
        except OSError:
            return False

    @staticmethod
    def get_process_using_port(port: int) -> Optional[str]:
        """Find the process name and PID currently listening on the given port."""
        try:
            for conn in psutil.net_connections(kind="inet"):
                if conn.laddr and conn.laddr.port == port and conn.status == psutil.CONN_LISTEN:
                    if conn.pid:
                        try:
                            proc = psutil.Process(conn.pid)
                            return f"{proc.name()} (PID: {conn.pid})"
                        except (psutil.NoSuchProcess, psutil.AccessDenied):
                            return f"PID {conn.pid}"
        except (psutil.AccessDenied, Exception):
            pass
        return None


class PathValidator:
    """Validator for filesystem paths and executables."""

    @staticmethod
    def validate_executable_path(path_or_cmd: str) -> Tuple[bool, str]:
        """
        Validate backend executable path or command string.
        Returns (is_valid, message).
        Example: '/home/user/app/.venv/bin/uvicorn' or 'uvicorn main:app'
        """
        if not path_or_cmd or not path_or_cmd.strip():
            return False, "Executable path cannot be empty."

        parts = path_or_cmd.strip().split()
        exe_path = parts[0]

        # Check direct absolute or relative file path
        if os.path.isabs(exe_path) or "/" in exe_path:
            p = Path(exe_path)
            if not p.exists():
                return False, f"Executable file not found at: {exe_path}"
            if not os.access(exe_path, os.X_OK) and not p.is_file():
                return False, f"File at {exe_path} is not executable."
            return True, f"Found executable: {exe_path}"

        # Check binary in PATH
        import shutil
        found = shutil.which(exe_path)
        if found:
            return True, f"Found binary in PATH: {found}"

        return False, f"Command/binary '{exe_path}' not found in system PATH or filesystem."

    @staticmethod
    def is_writable_directory(dir_path: str) -> bool:
        """Check if directory exists and is writable."""
        p = Path(dir_path)
        return p.is_dir() and os.access(dir_path, os.W_OK)


class DomainValidator:
    """Validator for domain names, IP addresses, and URL routes."""

    DOMAIN_REGEX = re.compile(
        r"^(?:[a-zA-Z0-9]"
        r"(?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+"
        r"[a-zA-Z]{2,63}$"
    )

    @classmethod
    def is_valid_domain(cls, domain: str) -> bool:
        """Validate if a string is a valid FQDN (e.g. app.example.com, example.com, localhost)."""
        if not domain or len(domain) > 253:
            return False
        domain = domain.strip().lower()
        if domain == "localhost":
            return True
        return bool(cls.DOMAIN_REGEX.match(domain))

    @staticmethod
    def is_valid_ip(ip_str: str) -> bool:
        """Check if string is a valid IPv4 or IPv6 address."""
        try:
            ipaddress.ip_address(ip_str.strip())
            return True
        except ValueError:
            return False

    @staticmethod
    def is_valid_route_path(route: str) -> bool:
        """Validate an Nginx route location path (e.g. / or /api/v1/ or /health)."""
        if not route or not route.strip():
            return False
        route = route.strip()
        if not route.startswith("/"):
            return False
        # Disallow invalid characters in location block
        if re.search(r"[\s{};#$]", route):
            return False
        return True

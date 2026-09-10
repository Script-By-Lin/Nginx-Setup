"""Systemd and service lifecycle management for Nginx and backend applications."""

import os
from typing import Optional, Tuple
from models.server_config import ServiceStatus
from utils.system import CommandResult, is_binary_available, run_command
from utils.validator import PathValidator, PortValidator


class ServiceManager:
    """Manages service lifecycle (systemd / init) for Nginx and backend microservices."""

    def __init__(self, dry_run: bool = False):
        self.dry_run = dry_run

    def get_nginx_status(self) -> ServiceStatus:
        """Get comprehensive Nginx service status."""
        installed = is_binary_available("nginx")
        if not installed:
            return ServiceStatus(name="nginx", is_installed=False, is_running=False, is_enabled=False)

        # Query version
        version = None
        ver_res = run_command("nginx -v")
        if ver_res.stderr or ver_res.stdout:
            ver_text = ver_res.stderr or ver_res.stdout
            version = ver_text.strip()

        # Check systemd status
        is_running = False
        is_enabled = False
        active_state = "unknown"

        if is_binary_available("systemctl"):
            status_res = run_command("systemctl is-active nginx")
            is_running = status_res.stdout.strip() == "active"
            active_state = status_res.stdout.strip()

            enabled_res = run_command("systemctl is-enabled nginx")
            is_enabled = enabled_res.stdout.strip() == "enabled"

        return ServiceStatus(
            name="nginx",
            is_installed=installed,
            is_running=is_running,
            is_enabled=is_enabled,
            version=version,
            active_state=active_state,
        )

    def ensure_nginx_running_and_enabled(self) -> Tuple[bool, str]:
        """Ensure Nginx service is both enabled at boot and currently running."""
        status = self.get_nginx_status()
        if not status.is_installed:
            return False, "Nginx is not installed on this system."

        messages = []

        if not status.is_enabled:
            res = run_command("systemctl enable nginx", sudo=True, dry_run=self.dry_run)
            if res.success:
                messages.append("Nginx service enabled on boot.")
            else:
                messages.append(f"Warning: Could not enable nginx service: {res.stderr}")

        if not status.is_running:
            res = run_command("systemctl start nginx", sudo=True, dry_run=self.dry_run)
            if res.success:
                messages.append("Nginx service started successfully.")
            else:
                return False, f"Failed to start Nginx service: {res.stderr}"
        else:
            messages.append("Nginx service is currently running.")

        return True, " | ".join(messages)

    def reload_nginx(self) -> Tuple[bool, str]:
        """Reload Nginx configuration without downtime."""
        # Prefer systemctl reload
        if is_binary_available("systemctl"):
            res = run_command("systemctl reload nginx", sudo=True, dry_run=self.dry_run)
            if res.success:
                return True, "Nginx reloaded successfully via systemctl."

        # Fallback to nginx -s reload
        res = run_command("nginx -s reload", sudo=True, dry_run=self.dry_run)
        if res.success:
            return True, "Nginx reloaded successfully via direct signal."

        return False, f"Failed to reload Nginx: {res.stderr}"

    def configure_selinux_for_nginx(self) -> Tuple[bool, str]:
        """
        Check if SELinux is in Enforcing mode, and if so, ensure httpd_can_network_connect is enabled
        so Nginx reverse proxy connections are permitted without 502 Permission Denied errors.
        """
        if not is_binary_available("getenforce"):
            return True, "SELinux not present on system."

        res = run_command("getenforce")
        if res.stdout.strip().lower() != "enforcing":
            return True, f"SELinux status: {res.stdout.strip()} (No restriction)."

        # Check if setsebool is available
        if not is_binary_available("setsebool"):
            return False, "SELinux is Enforcing, but setsebool utility is missing."

        # Check current boolean status
        bool_res = run_command("getsebool httpd_can_network_connect")
        if "--> on" in bool_res.stdout:
            return True, "SELinux boolean 'httpd_can_network_connect' is already enabled."

        # Enable persistently
        set_res = run_command("setsebool -P httpd_can_network_connect 1", sudo=True, dry_run=self.dry_run)
        if set_res.success:
            return True, "Enabled SELinux boolean 'httpd_can_network_connect' for Nginx reverse proxying."
        return False, f"Failed to set SELinux boolean: {set_res.stderr}"

    def restart_nginx(self) -> Tuple[bool, str]:
        """Restart Nginx service."""
        if is_binary_available("systemctl"):
            res = run_command("systemctl restart nginx", sudo=True, dry_run=self.dry_run)
            if res.success:
                return True, "Nginx restarted successfully."
        return False, "Failed to restart Nginx service."

    def create_backend_systemd_service(
        self,
        service_name: str,
        executable_cmd: str,
        working_dir: Optional[str] = None,
        user: str = "root",
        description: Optional[str] = None,
    ) -> Tuple[bool, str]:
        """
        Generates and installs a systemd unit service file for a backend application.
        E.g. /etc/systemd/system/{service_name}.service
        """
        valid_exe, exe_msg = PathValidator.validate_executable_path(executable_cmd)
        if not valid_exe and not self.dry_run:
            return False, f"Invalid backend executable command: {exe_msg}"

        if not working_dir:
            parts = executable_cmd.split()
            working_dir = os.path.dirname(os.path.abspath(parts[0])) if os.path.exists(parts[0]) else "/tmp"

        unit_content = f"""[Unit]
Description={description or f'Backend Service for {service_name}'}
After=network.target

[Service]
Type=simple
User={user}
WorkingDirectory={working_dir}
ExecStart={executable_cmd}
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
"""
        service_path = f"/etc/systemd/system/{service_name}.service"
        from utils.backup import BackupManager
        bm = BackupManager(dry_run=self.dry_run)
        bm.write_file(service_path, unit_content)

        # Reload systemd daemon
        run_command("systemctl daemon-reload", sudo=True, dry_run=self.dry_run)
        run_command(f"systemctl enable --now {service_name}", sudo=True, dry_run=self.dry_run)

        return True, f"Systemd backend service installed and started at {service_path}"

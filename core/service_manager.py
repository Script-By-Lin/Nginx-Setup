"""Systemd and service lifecycle management for Nginx and backend applications."""

import os
from typing import Dict, List, Optional, Tuple
from models.server_config import ServiceStatus, SystemdServiceConfig, SystemdServiceState
from utils.backup import BackupManager
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

    # -------------------------------------------------------------
    # Production Systemd Unit Automation for Backend Services
    # -------------------------------------------------------------

    def render_systemd_unit(self, config: SystemdServiceConfig) -> str:
        """Render standard systemd .service unit file content."""
        clean_name = config.service_name.strip()
        if clean_name.endswith(".service"):
            clean_name = clean_name[:-8]

        lines = [
            "[Unit]",
            f"Description={config.description or f'{clean_name} Application Service'}",
            "After=network.target",
            "",
            "[Service]",
            f"User={config.user}",
        ]

        if config.group:
            lines.append(f"Group={config.group}")

        lines.extend([
            f"WorkingDirectory={config.working_dir}",
            f"ExecStart={config.exec_start}",
            f"Restart={config.restart or 'always'}",
            f"RestartSec={config.restart_sec or 3}",
            "StandardOutput=journal",
            "StandardError=journal",
        ])

        if config.environment:
            for k, v in config.environment.items():
                lines.append(f"Environment={k}={v}")

        lines.extend([
            "",
            "[Install]",
            "WantedBy=multi-user.target",
            "",
        ])

        return "\n".join(lines)

    def create_systemd_service(self, config: SystemdServiceConfig) -> Tuple[bool, List[str], str]:
        """
        Creates systemd unit file (/etc/systemd/system/{name}.service), reloads systemd daemon,
        enables service to start automatically on every system boot/reboot, and starts the service.
        """
        logs: List[str] = []
        clean_name = config.service_name.strip()
        if clean_name.endswith(".service"):
            clean_name = clean_name[:-8]

        service_path = f"/etc/systemd/system/{clean_name}.service"
        unit_content = self.render_systemd_unit(config)

        # 1. Write unit file with backup
        bm = BackupManager(dry_run=self.dry_run)
        try:
            backup_path = bm.write_file(service_path, unit_content)
            logs.append(f"Service unit configuration written to {service_path}")
            if backup_path:
                logs.append(f"Backup created: {backup_path}")
        except Exception as e:
            logs.append(f"Failed to write service unit file: {e}")
            return False, logs, service_path

        # 2. systemctl daemon-reload
        if is_binary_available("systemctl"):
            reload_res = run_command("systemctl daemon-reload", sudo=True, dry_run=self.dry_run)
            if not reload_res.success and not self.dry_run:
                logs.append(f"Warning: daemon-reload failed: {reload_res.stderr}")
            else:
                logs.append("Executed 'systemctl daemon-reload'")

            # 3. systemctl enable (for every boot/reboot)
            enable_res = run_command(f"systemctl enable {clean_name}.service", sudo=True, dry_run=self.dry_run)
            if not enable_res.success and not self.dry_run:
                logs.append(f"Warning: Failed to enable {clean_name}.service on boot: {enable_res.stderr}")
            else:
                logs.append(f"Enabled {clean_name}.service to start automatically on boot/reboot")

            # 4. systemctl restart/start
            start_res = run_command(f"systemctl restart {clean_name}.service", sudo=True, dry_run=self.dry_run)
            if not start_res.success and not self.dry_run:
                logs.append(f"Warning: Failed to start service: {start_res.stderr}")
            else:
                logs.append(f"Service {clean_name}.service started/restarted successfully")
        else:
            logs.append("systemctl not detected on system; unit written without lifecycle trigger.")

        return True, logs, service_path

    def remove_systemd_service(self, service_name: str) -> Tuple[bool, List[str]]:
        """
        Safely stops, disables from boot, removes unit file, and executes daemon-reload.
        """
        logs: List[str] = []
        clean_name = service_name.strip()
        if clean_name.endswith(".service"):
            clean_name = clean_name[:-8]

        service_path = f"/etc/systemd/system/{clean_name}.service"

        if is_binary_available("systemctl"):
            # 1. Stop service
            stop_res = run_command(f"systemctl stop {clean_name}.service", sudo=True, dry_run=self.dry_run)
            if stop_res.success:
                logs.append(f"Stopped {clean_name}.service")
            else:
                logs.append(f"Stop notice: {stop_res.stderr.strip() or 'Service was not running'}")

            # 2. Disable service from autostart
            disable_res = run_command(f"systemctl disable {clean_name}.service", sudo=True, dry_run=self.dry_run)
            if disable_res.success:
                logs.append(f"Disabled {clean_name}.service from boot autostart")
            else:
                logs.append(f"Disable notice: {disable_res.stderr.strip() or 'Service was not enabled'}")

        # 3. Remove unit file with backup
        bm = BackupManager(dry_run=self.dry_run)
        if os.path.exists(service_path) or self.dry_run:
            rem_ok, rem_msg = bm.remove_file(service_path)
            if rem_ok:
                logs.append(f"Removed systemd unit file: {service_path}")
            else:
                logs.append(f"Notice on file removal: {rem_msg}")
        else:
            logs.append(f"Unit file {service_path} already absent on disk.")

        # 4. daemon-reload and reset-failed
        if is_binary_available("systemctl"):
            run_command("systemctl daemon-reload", sudo=True, dry_run=self.dry_run)
            run_command(f"systemctl reset-failed {clean_name}.service", sudo=True, dry_run=self.dry_run)
            logs.append("Executed 'systemctl daemon-reload' and reset-failed.")

        return True, logs

    def get_systemd_service_status(self, service_name: str) -> Dict[str, object]:
        """Query live systemctl status of a service unit."""
        clean_name = service_name.strip()
        if clean_name.endswith(".service"):
            clean_name = clean_name[:-8]

        service_path = f"/etc/systemd/system/{clean_name}.service"
        is_installed = os.path.exists(service_path)
        is_active = False
        is_enabled = False
        active_state = "unknown"
        enabled_state = "unknown"

        if is_binary_available("systemctl"):
            act_res = run_command(f"systemctl is-active {clean_name}.service")
            active_state = act_res.stdout.strip()
            is_active = active_state == "active"

            enb_res = run_command(f"systemctl is-enabled {clean_name}.service")
            enabled_state = enb_res.stdout.strip()
            is_enabled = enabled_state == "enabled"

        return {
            "service_name": clean_name,
            "unit_file": f"{clean_name}.service",
            "unit_path": service_path,
            "is_installed": is_installed,
            "is_active": is_active,
            "is_enabled": is_enabled,
            "active_state": active_state,
            "enabled_state": enabled_state,
        }

    def control_systemd_service(self, service_name: str, action: str) -> Tuple[bool, str]:
        """Control service lifecycle: start, stop, restart, reload, status, logs."""
        clean_name = service_name.strip()
        if clean_name.endswith(".service"):
            clean_name = clean_name[:-8]

        action = action.lower().strip()
        if action in ("start", "stop", "restart", "reload"):
            res = run_command(f"systemctl {action} {clean_name}.service", sudo=True, dry_run=self.dry_run)
            if res.success:
                return True, f"Successfully executed 'systemctl {action} {clean_name}.service'"
            return False, f"Failed to {action} service: {res.stderr}"

        elif action == "status":
            res = run_command(f"systemctl status {clean_name}.service --no-pager")
            return res.success, res.stdout or res.stderr

        elif action == "logs":
            res = run_command(f"journalctl -u {clean_name}.service -n 30 --no-pager")
            return res.success, res.stdout or res.stderr

        return False, f"Unknown service action: {action}"

    def create_backend_systemd_service(
        self,
        service_name: str,
        executable_cmd: str,
        working_dir: Optional[str] = None,
        user: str = "root",
        description: Optional[str] = None,
    ) -> Tuple[bool, str]:
        """Backwards-compatible wrapper for create_systemd_service."""
        if not working_dir:
            parts = executable_cmd.split()
            working_dir = os.path.dirname(os.path.abspath(parts[0])) if os.path.exists(parts[0]) else "/tmp"

        cfg = SystemdServiceConfig(
            service_name=service_name,
            description=description or f"Backend Service for {service_name}",
            user=user,
            working_dir=working_dir,
            exec_start=executable_cmd,
            restart="always",
        )
        ok, logs, service_path = self.create_systemd_service(cfg)
        return ok, " | ".join(logs)


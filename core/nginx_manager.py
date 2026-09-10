"""Nginx configuration generator, validator, file deployer, and reload controller."""

import os
from pathlib import Path
from typing import List, Optional, Tuple
from jinja2 import Environment, FileSystemLoader
from core.os_detector import OSDetector
from core.service_manager import ServiceManager
from models.server_config import OSInfo, ServerConfig
from utils.backup import BackupManager
from utils.system import CommandResult, is_root, run_command


class NginxManager:
    """Handles rendering, writing, validating, and deploying Nginx virtual host configurations."""

    def __init__(
        self,
        template_dir: Optional[str] = None,
        os_detector: Optional[OSDetector] = None,
        dry_run: bool = False,
    ):
        self.dry_run = dry_run
        self.os_detector = os_detector or OSDetector(dry_run=dry_run)
        self.service_manager = ServiceManager(dry_run=dry_run)
        self.backup_manager = BackupManager(dry_run=dry_run)

        # Initialize Jinja2 environment
        if not template_dir:
            base_dir = Path(__file__).resolve().parent.parent
            template_dir = str(base_dir / "templates")

        self.jinja_env = Environment(
            loader=FileSystemLoader(template_dir),
            trim_blocks=True,
            lstrip_blocks=True,
        )

    def render_config(self, config: ServerConfig) -> str:
        """Render Nginx virtualhost configuration string from Jinja2 template."""
        template = self.jinja_env.get_template("nginx.conf.j2")
        return template.render(server=config)

    def get_config_target_path(self, project_name: str) -> Tuple[str, Optional[str]]:
        """
        Determine target configuration file path and optional symlink destination.
        Returns: (main_target_path, symlink_enabled_path_or_none)
        """
        os_info: OSInfo = self.os_detector.detect()
        filename = f"{project_name}.conf"

        if os_info.use_symlinks and os_info.nginx_sites_available_dir:
            target_path = os.path.join(os_info.nginx_sites_available_dir, filename)
            symlink_path = (
                os.path.join(os_info.nginx_sites_enabled_dir, filename)
                if os_info.nginx_sites_enabled_dir
                else None
            )
            return target_path, symlink_path

        target_path = os.path.join(os_info.nginx_conf_dir, filename)
        return target_path, None

    def test_config(self) -> CommandResult:
        """Run 'nginx -t' to validate overall Nginx syntax and structure."""
        return run_command("nginx -t", sudo=True, dry_run=self.dry_run)

    def apply_config(self, config: ServerConfig) -> Tuple[bool, List[str], str]:
        """
        Renders, writes, validates with 'nginx -t', and deploys the Nginx config.
        If validation fails, rolls back immediately.
        Returns: (success, logs, target_file_path)
        """
        logs = []
        target_path, symlink_path = self.get_config_target_path(config.project_name)
        config.config_file_path = target_path

        # 1. Ensure OS includes conf.d if needed
        self.os_detector.ensure_include_directive()

        # 2. Render template
        logs.append(f"Rendering Nginx configuration for '{config.project_name}'...")
        content = self.render_config(config)

        # 3. Write file with backup
        logs.append(f"Writing configuration to {target_path} (with automated backup)...")
        backup_path = self.backup_manager.write_file(target_path, content)
        if backup_path:
            logs.append(f"Backup created at: {backup_path}")

        # 4. Create symlink if needed (e.g. Debian/Ubuntu)
        if symlink_path and not self.dry_run:
            if not os.path.exists(symlink_path):
                if is_root():
                    os.symlink(target_path, symlink_path)
                else:
                    run_command(["ln", "-sf", target_path, symlink_path], sudo=True)
                logs.append(f"Created symlink: {symlink_path} -> {target_path}")

        # 5. Validate with nginx -t
        logs.append("Testing configuration with 'nginx -t'...")
        test_res = self.test_config()

        if not test_res.success:
            err_msg = test_res.stderr or test_res.stdout
            logs.append(f"Nginx validation failed:\n{err_msg}")
            logs.append("Triggering automated rollback...")

            # Rollback
            self.backup_manager.rollback(target_path, backup_path)
            if symlink_path and not backup_path and not self.dry_run:
                if os.path.islink(symlink_path) or os.path.exists(symlink_path):
                    run_command(["rm", "-f", symlink_path], sudo=True)

            logs.append("Rollback completed. Original configuration restored.")
            return False, logs, target_path

        # 6. Ensure SELinux allows network proxying and ensure Nginx is running
        selinux_ok, selinux_msg = self.service_manager.configure_selinux_for_nginx()
        logs.append(f"SELinux Status: {selinux_msg}")

        self.service_manager.ensure_nginx_running_and_enabled()
        reload_ok, reload_msg = self.service_manager.reload_nginx()
        logs.append(f"Nginx Reload: {reload_msg}")

        return reload_ok, logs, target_path

    def remove_config(self, project_name: str) -> Tuple[bool, List[str]]:
        """Remove a project's Nginx configuration and reload."""
        logs = []
        target_path, symlink_path = self.get_config_target_path(project_name)

        if not os.path.exists(target_path) and not self.dry_run:
            return False, [f"Configuration file {target_path} does not exist."]

        backup_path = self.backup_manager.create_backup(target_path)
        if backup_path:
            logs.append(f"Backup created before removal: {backup_path}")

        if symlink_path and os.path.exists(symlink_path) and not self.dry_run:
            run_command(["rm", "-f", symlink_path], sudo=True)
            logs.append(f"Removed symlink: {symlink_path}")

        if os.path.exists(target_path) and not self.dry_run:
            run_command(["rm", "-f", target_path], sudo=True)
            logs.append(f"Removed configuration: {target_path}")

        # Test and reload
        test_res = self.test_config()
        if not test_res.success:
            logs.append("Warning: Nginx test failed after removal. Rolling back...")
            self.backup_manager.rollback(target_path, backup_path)
            return False, logs

        self.service_manager.reload_nginx()
        logs.append("Nginx reloaded successfully.")
        return True, logs

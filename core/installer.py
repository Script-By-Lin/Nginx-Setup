"""Automated package installation across Linux distributions for Nginx and Certbot."""

import shutil
from typing import Dict, List, Tuple
from core.os_detector import OSDetector
from models.server_config import OSFamily, PackageManager
from utils.system import CommandResult, is_binary_available, is_root, run_command


class PackageInstaller:
    """Detects missing dependencies and automates installation across various package managers."""

    def __init__(self, os_detector: OSDetector = None, dry_run: bool = False):
        self.os_detector = os_detector or OSDetector()
        self.dry_run = dry_run

    def is_nginx_installed(self) -> bool:
        """Check if Nginx binary is available."""
        return is_binary_available("nginx")

    def is_certbot_installed(self) -> bool:
        """Check if Certbot binary is available."""
        return is_binary_available("certbot")

    def is_certbot_nginx_installed(self) -> bool:
        """Check if certbot-nginx plugin is installed."""
        if not self.is_certbot_installed():
            return False
        # Run certbot plugins check
        res = run_command("certbot plugins --text", timeout=10)
        return "nginx" in res.stdout.lower()

    def check_all_installed(self) -> Dict[str, bool]:
        """Check status of all required packages."""
        return {
            "nginx": self.is_nginx_installed(),
            "certbot": self.is_certbot_installed(),
            "certbot-nginx": self.is_certbot_nginx_installed(),
        }

    def get_install_commands(self) -> List[List[str]]:
        """Get the specific package manager commands to install required components."""
        os_info = self.os_detector.detect()
        pkg = os_info.package_manager
        commands = []

        if pkg == PackageManager.APT:
            commands.append(["apt-get", "update"])
            commands.append(["apt-get", "install", "-y", "nginx", "certbot", "python3-certbot-nginx"])
        elif pkg == PackageManager.DNF or pkg == PackageManager.YUM:
            pkg_bin = "dnf" if pkg == PackageManager.DNF else "yum"
            # In RHEL/CentOS/Rocky, EPEL is required for certbot
            commands.append([pkg_bin, "install", "-y", "epel-release"])
            commands.append([pkg_bin, "install", "-y", "nginx", "certbot", "python3-certbot-nginx"])
        elif pkg == PackageManager.PACMAN:
            commands.append(["pacman", "-Sy", "--noconfirm", "nginx", "certbot", "certbot-nginx"])
        elif pkg == PackageManager.APK:
            commands.append(["apk", "update"])
            commands.append(["apk", "add", "nginx", "certbot", "certbot-nginx"])
        elif pkg == PackageManager.ZYPPER:
            commands.append(["zypper", "--non-interactive", "install", "nginx", "certbot", "python3-certbot-nginx"])
        else:
            raise RuntimeError(f"Unsupported package manager for automated install: {pkg}")

        return commands

    def install_missing(self) -> Tuple[bool, List[str]]:
        """
        Installs any missing required packages (nginx, certbot, certbot-nginx).
        Returns (success, messages).
        """
        status = self.check_all_installed()
        if all(status.values()):
            return True, ["All required packages (nginx, certbot, certbot-nginx) are already installed."]

        missing = [pkg for pkg, installed in status.items() if not installed]
        commands = self.get_install_commands()
        logs = [f"Missing packages detected: {', '.join(missing)}."]

        for cmd in commands:
            cmd_str = " ".join(cmd)
            logs.append(f"Running: {cmd_str}")
            res = run_command(cmd, sudo=True, dry_run=self.dry_run, timeout=300)
            if not res.success:
                err_msg = f"Installation command failed: {cmd_str}\nError: {res.stderr}"
                logs.append(err_msg)
                return False, logs

        logs.append("Successfully installed required packages.")
        return True, logs

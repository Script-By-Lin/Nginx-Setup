"""Firewall detection and automated port configuration (UFW, Firewalld, iptables)."""

import shutil
from typing import List, Optional, Tuple
from models.server_config import FirewallInfo, FirewallType
from utils.system import CommandResult, is_binary_available, run_command


class FirewallManager:
    """Detects active firewall services and opens required HTTP/HTTPS/backend ports."""

    def __init__(self, dry_run: bool = False):
        self.dry_run = dry_run

    def detect_firewall(self) -> FirewallInfo:
        """Detect which firewall utility is active on the system."""
        # 1. Check UFW via systemctl or non-interactive command
        if is_binary_available("ufw"):
            res = run_command("systemctl is-active ufw")
            if res.stdout.strip() == "active":
                return FirewallInfo(type=FirewallType.UFW, is_active=True)
            # Fallback to ufw status
            res = run_command("ufw status", sudo=True)
            if "status: active" in res.stdout.lower():
                return FirewallInfo(type=FirewallType.UFW, is_active=True)

        # 2. Check Firewalld via systemctl or firewall-cmd
        if is_binary_available("firewall-cmd"):
            res = run_command("systemctl is-active firewalld")
            if res.stdout.strip() == "active":
                return FirewallInfo(type=FirewallType.FIREWALLD, is_active=True)
            res = run_command("firewall-cmd --state", sudo=True)
            if "running" in res.stdout.lower():
                return FirewallInfo(type=FirewallType.FIREWALLD, is_active=True)

        # 3. Check iptables
        if is_binary_available("iptables"):
            res = run_command("iptables -L -n", sudo=True)
            if res.success and len(res.stdout.splitlines()) > 5:
                return FirewallInfo(type=FirewallType.IPTABLES, is_active=True)

        # 4. Check if binaries exist even if inactive
        if is_binary_available("ufw"):
            return FirewallInfo(type=FirewallType.UFW, is_active=False)
        if is_binary_available("firewall-cmd"):
            return FirewallInfo(type=FirewallType.FIREWALLD, is_active=False)
        if is_binary_available("iptables"):
            return FirewallInfo(type=FirewallType.IPTABLES, is_active=False)

        return FirewallInfo(type=FirewallType.NONE, is_active=False)

    def open_ports(self, ports: List[int], include_standard_web: bool = True) -> Tuple[bool, List[str]]:
        """
        Open specified ports (plus 80 and 443 if include_standard_web is True)
        in the detected active firewall.
        """
        all_ports = set(ports)
        if include_standard_web:
            all_ports.update([80, 443])

        fw_info = self.detect_firewall()
        logs = []

        if not fw_info.is_active or fw_info.type == FirewallType.NONE:
            logs.append(f"No active firewall detected ({fw_info.type.value}). Skipping port configuration.")
            return True, logs

        logs.append(f"Configuring active firewall: {fw_info.type.value}")

        if fw_info.type == FirewallType.UFW:
            for port in sorted(all_ports):
                cmd = ["ufw", "allow", f"{port}/tcp"]
                logs.append(f"Running: {' '.join(cmd)}")
                res = run_command(cmd, sudo=True, dry_run=self.dry_run)
                if not res.success:
                    logs.append(f"Warning: Failed to open port {port} with UFW: {res.stderr}")

        elif fw_info.type == FirewallType.FIREWALLD:
            # Add http and https services
            run_command(["firewall-cmd", "--permanent", "--add-service=http"], sudo=True, dry_run=self.dry_run)
            run_command(["firewall-cmd", "--permanent", "--add-service=https"], sudo=True, dry_run=self.dry_run)
            for port in sorted(all_ports):
                if port not in (80, 443):
                    cmd = ["firewall-cmd", "--permanent", f"--add-port={port}/tcp"]
                    logs.append(f"Running: {' '.join(cmd)}")
                    run_command(cmd, sudo=True, dry_run=self.dry_run)

            # Reload firewalld
            logs.append("Reloading firewalld...")
            res = run_command(["firewall-cmd", "--reload"], sudo=True, dry_run=self.dry_run)
            if not res.success:
                logs.append(f"Warning: firewalld reload failed: {res.stderr}")

        elif fw_info.type == FirewallType.IPTABLES:
            for port in sorted(all_ports):
                # Check if rule exists
                check_cmd = ["iptables", "-C", "INPUT", "-p", "tcp", "--dport", str(port), "-j", "ACCEPT"]
                check_res = run_command(check_cmd, sudo=True, dry_run=self.dry_run)
                if not check_res.success:
                    cmd = ["iptables", "-I", "INPUT", "-p", "tcp", "--dport", str(port), "-j", "ACCEPT"]
                    logs.append(f"Running: {' '.join(cmd)}")
                    run_command(cmd, sudo=True, dry_run=self.dry_run)

        logs.append(f"Successfully configured firewall rules for ports: {', '.join(str(p) for p in sorted(all_ports))}.")
        return True, logs

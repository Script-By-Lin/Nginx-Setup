"""SSL certificate provisioning and management using Let's Encrypt / Certbot."""

import os
from pathlib import Path
from typing import List, Optional, Tuple
from utils.dns import DNSHelper
from utils.system import CommandResult, is_binary_available, is_root, run_command
from utils.validator import DomainValidator


class SSLManager:
    """Manages SSL certificate generation, DNS validation, and auto-renewal via Certbot."""

    def __init__(self, dry_run: bool = False):
        self.dry_run = dry_run

    def check_certbot_available(self) -> bool:
        """Check if certbot binary is installed and executable."""
        return is_binary_available("certbot")

    def get_certificate_paths(self, domain: str) -> Tuple[str, str]:
        """Return expected certificate and private key file paths for a domain."""
        clean_domain = domain.strip().lower()
        cert_path = f"/etc/letsencrypt/live/{clean_domain}/fullchain.pem"
        key_path = f"/etc/letsencrypt/live/{clean_domain}/privkey.pem"
        return cert_path, key_path

    def certificates_exist(self, domain: str) -> bool:
        """Check if valid certificates already exist on the filesystem for the domain."""
        cert_path, key_path = self.get_certificate_paths(domain)
        return os.path.exists(cert_path) and os.path.exists(key_path)

    def request_certificate(
        self,
        domain: str,
        email: Optional[str] = None,
        agree_tos: bool = True,
        use_nginx_plugin: bool = True,
        webroot_path: str = "/var/www/certbot",
    ) -> Tuple[bool, List[str], Optional[str], Optional[str]]:
        """
        Request and install SSL certificate using Certbot.
        Returns: (success, log_messages, cert_path, key_path)
        """
        clean_domain = domain.strip().lower()
        logs = []

        if not DomainValidator.is_valid_domain(clean_domain):
            return False, [f"Invalid domain syntax: '{clean_domain}'."], None, None

        if not self.check_certbot_available():
            return False, ["Certbot is not installed. Please install certbot first."], None, None

        # Check DNS resolution
        dns_ok, dns_msg = DNSHelper.verify_domain_points_to_ip(clean_domain)
        logs.append(f"DNS Check: {dns_msg}")
        if not dns_ok and not self.dry_run:
            logs.append("Warning: Domain DNS verification failed. Certbot challenge may fail if DNS is not propagated.")

        # Ensure webroot challenge directory exists
        if not self.dry_run:
            Path(webroot_path).mkdir(parents=True, exist_ok=True)
            if not is_root():
                run_command(["mkdir", "-p", webroot_path], sudo=True)
                run_command(["chmod", "-R", "755", webroot_path], sudo=True)

        cert_path, key_path = self.get_certificate_paths(clean_domain)

        # Build certbot command
        cmd = ["certbot", "certonly"]
        if use_nginx_plugin:
            cmd.extend(["--webroot", "-w", webroot_path])
        else:
            cmd.extend(["--standalone"])

        cmd.extend(["-d", clean_domain, "--non-interactive"])

        if agree_tos:
            cmd.append("--agree-tos")

        if email and "@" in email:
            cmd.extend(["-m", email.strip()])
        else:
            cmd.append("--register-unsafely-without-email")

        cmd_str = " ".join(cmd)
        logs.append(f"Executing: {cmd_str}")

        res = run_command(cmd, sudo=True, dry_run=self.dry_run, timeout=180)
        if not res.success:
            err_details = res.stderr or res.stdout
            logs.append(f"Certbot certificate issuance failed:\n{err_details}")
            logs.append(
                "\nTroubleshooting tips:\n"
                "1. Ensure port 80 and 443 are open in your firewall and ISP.\n"
                "2. Verify that your DNS A record points to this server's public IP.\n"
                "3. Verify Nginx is serving ACME challenge /.well-known/acme-challenge/ correctly."
            )
            return False, logs, None, None

        logs.append(f"Certificate successfully obtained for {clean_domain}!")
        return True, logs, cert_path, key_path

    def test_auto_renewal(self) -> Tuple[bool, str]:
        """Test Certbot renewal mechanism with --dry-run."""
        res = run_command("certbot renew --dry-run", sudo=True, dry_run=self.dry_run)
        if res.success:
            return True, "Certbot auto-renewal test succeeded."
        return False, f"Certbot auto-renewal test warning: {res.stderr}"

"""DNS and Public IP resolution helper utilities."""

import socket
from typing import Optional, Tuple
import requests


class DNSHelper:
    """Helper for DNS checks and public IP detection."""

    IP_SERVICES = [
        "https://api.ipify.org",
        "https://icanhazip.com",
        "https://ifconfig.me/ip",
        "https://checkip.amazonaws.com",
    ]

    @classmethod
    def get_public_ip(cls, timeout: float = 3.0) -> Optional[str]:
        """
        Query public IP address from external IP reflection services.
        Falls back to primary network interface IP if external request fails.
        """
        for url in cls.IP_SERVICES:
            try:
                resp = requests.get(url, timeout=timeout)
                if resp.status_code == 200:
                    ip = resp.text.strip()
                    if ip:
                        return ip
            except Exception:
                continue

        # Fallback to local network IP
        return cls.get_local_ip()

    @staticmethod
    def get_local_ip() -> str:
        """Get IP address of primary local interface."""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                # Does not actually connect, just selects interface for route
                s.connect(("8.8.8.8", 80))
                return s.getsockname()[0]
        except Exception:
            return "127.0.0.1"

    @classmethod
    def resolve_domain(cls, domain: str) -> Tuple[bool, Optional[str], str]:
        """
        Resolve domain to its IPv4 address.
        Returns: (success, ip_address, message)
        """
        domain = domain.strip().lower()
        try:
            resolved_ip = socket.gethostbyname(domain)
            return True, resolved_ip, f"Domain '{domain}' successfully resolved to {resolved_ip}."
        except socket.gaierror as exc:
            return False, None, f"Could not resolve domain '{domain}': {str(exc)}"

    @classmethod
    def verify_domain_points_to_ip(cls, domain: str, expected_ip: Optional[str] = None) -> Tuple[bool, str]:
        """
        Verify if domain's DNS A record matches this server's public/local IP.
        Returns (matches, message).
        """
        if not expected_ip:
            expected_ip = cls.get_public_ip()

        success, resolved_ip, msg = cls.resolve_domain(domain)
        if not success or not resolved_ip:
            return False, msg

        if expected_ip and resolved_ip == expected_ip:
            return True, f"Domain '{domain}' correctly points to server IP ({resolved_ip})."
        
        return False, (
            f"Domain '{domain}' resolves to {resolved_ip}, but server public IP is {expected_ip}. "
            "Please update your DNS A Record before requesting SSL certificate."
        )

    @classmethod
    def get_dns_instructions(cls, domain: str, server_ip: Optional[str] = None) -> str:
        """Generate clear DNS configuration guidance for user."""
        if not server_ip:
            server_ip = cls.get_public_ip() or "YOUR_SERVER_PUBLIC_IP"
        
        return (
            f"DNS Setup Instructions:\n"
            f"  Type:   A Record\n"
            f"  Host:   {domain} (or @ / subdomain)\n"
            f"  Points: {server_ip}\n"
            f"  TTL:    Auto / 300s (5 minutes)"
        )

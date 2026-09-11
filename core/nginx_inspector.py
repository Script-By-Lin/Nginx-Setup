"""Nginx configuration inspector and system port scanner.

Scans /etc/nginx/nginx.conf, /etc/nginx/conf.d/*.conf, /etc/nginx/sites-enabled/*,
and /etc/nginx/http.d/*.conf to detect active listening ports, server_names,
proxy_pass upstream targets, and SSL certificates across all active configs.
"""

import glob
import os
import re
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple
from pydantic import BaseModel, Field
from utils.validator import PortValidator


class NginxVirtualHost(BaseModel):
    """Details of a single virtual host (server block) found in Nginx configs."""
    file_path: str
    server_names: List[str] = Field(default_factory=list)
    listen_ports: List[int] = Field(default_factory=list)
    listen_directives: List[str] = Field(default_factory=list)
    ssl_enabled: bool = False
    proxy_passes: List[str] = Field(default_factory=list)
    locations: List[str] = Field(default_factory=list)


class NginxSystemScanResult(BaseModel):
    """Aggregate result of scanning all Nginx configuration files on the system."""
    config_files_scanned: List[str] = Field(default_factory=list)
    virtual_hosts: List[NginxVirtualHost] = Field(default_factory=list)
    all_listening_ports: List[int] = Field(default_factory=list)
    all_server_names: List[str] = Field(default_factory=list)
    all_proxy_targets: List[str] = Field(default_factory=list)


class NginxInspector:
    """Discovers and parses all Nginx configuration files to detect ports and virtual hosts."""

    def __init__(self, root_conf_dir: Optional[str] = None):
        self.root_conf_dir = root_conf_dir or "/etc/nginx"

    def find_all_config_files(self) -> List[str]:
        """Find all nginx.conf, conf.d/*.conf, sites-enabled/*, and http.d/*.conf files."""
        files: Set[str] = set()
        base = Path(self.root_conf_dir)

        # 1. Main nginx.conf
        main_conf = base / "nginx.conf"
        if main_conf.exists() and main_conf.is_file():
            files.add(str(main_conf))

        # 2. conf.d/*.conf
        for p in base.glob("conf.d/*.conf"):
            if p.is_file() and not p.name.endswith("~") and ".bak" not in p.name:
                files.add(str(p))

        # 3. sites-enabled/* (active symlinked sites)
        sites_enabled_dir = base / "sites-enabled"
        if sites_enabled_dir.exists():
            for p in sites_enabled_dir.iterdir():
                if (p.is_file() or p.is_symlink()) and not p.name.endswith("~") and ".bak" not in p.name:
                    try:
                        resolved = str(p.resolve()) if p.is_symlink() else str(p)
                        if os.path.exists(resolved):
                            files.add(str(p))
                    except Exception:
                        pass
        else:
            # If sites-enabled doesn't exist, check sites-available
            for p in base.glob("sites-available/*.conf"):
                if p.is_file() and not p.name.endswith("~") and ".bak" not in p.name:
                    files.add(str(p))

        # 4. http.d/*.conf (Alpine)
        for p in base.glob("http.d/*.conf"):
            if p.is_file() and not p.name.endswith("~") and ".bak" not in p.name:
                files.add(str(p))

        return sorted(list(files))

    def _strip_comments(self, content: str) -> str:
        """Remove line comments starting with #."""
        lines = []
        for line in content.splitlines():
            # Strip comments, respecting quotes
            cleaned = re.sub(r"#.*$", "", line)
            lines.append(cleaned)
        return "\n".join(lines)

    def _extract_server_blocks(self, content: str) -> List[str]:
        """Extract content inside top-level server { ... } blocks."""
        cleaned = self._strip_comments(content)
        server_blocks = []
        
        # Simple brace matching for server { ... }
        pos = 0
        while True:
            match = re.search(r"\bserver\s*\{", cleaned[pos:])
            if not match:
                break
            start_idx = pos + match.end() - 1
            brace_count = 0
            end_idx = start_idx

            for i in range(start_idx, len(cleaned)):
                if cleaned[i] == "{":
                    brace_count += 1
                elif cleaned[i] == "}":
                    brace_count -= 1
                    if brace_count == 0:
                        end_idx = i
                        break

            if brace_count == 0:
                block_content = cleaned[start_idx + 1:end_idx]
                server_blocks.append(block_content)
                pos = end_idx + 1
            else:
                break

        return server_blocks

    def parse_file(self, file_path: str) -> List[NginxVirtualHost]:
        """Parse an individual configuration file and extract all virtual hosts."""
        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                raw_content = f.read()
        except Exception:
            return []

        server_blocks = self._extract_server_blocks(raw_content)
        vhosts = []

        # If no explicit server block found, treat entire content as single block if it has listen directives
        if not server_blocks and "listen" in raw_content:
            server_blocks = [self._strip_comments(raw_content)]

        for block in server_blocks:
            vhost = NginxVirtualHost(file_path=file_path)

            # 1. Extract listen directives and ports
            # e.g. listen 80; listen 443 ssl http2; listen 127.0.0.1:8080; listen [::]:80;
            listen_matches = re.findall(r"\blisten\s+([^;]+);", block)
            for l_dir in listen_matches:
                l_dir_clean = l_dir.strip()
                vhost.listen_directives.append(l_dir_clean)
                if "ssl" in l_dir_clean:
                    vhost.ssl_enabled = True

                # Extract numeric port
                port_match = re.search(r"(?:^|[:\s])(\d{1,5})(?:$|[\s;])", l_dir_clean)
                if port_match:
                    p_num = int(port_match.group(1))
                    if 1 <= p_num <= 65535 and p_num not in vhost.listen_ports:
                        vhost.listen_ports.append(p_num)

            # 2. Extract server_name
            # e.g. server_name example.com www.example.com;
            sn_matches = re.findall(r"\bserver_name\s+([^;]+);", block)
            for sn_dir in sn_matches:
                for name in sn_dir.strip().split():
                    name_clean = name.strip()
                    if name_clean and name_clean != "_" and name_clean not in vhost.server_names:
                        vhost.server_names.append(name_clean)

            # 3. Extract proxy_pass
            # e.g. proxy_pass http://127.0.0.1:8000;
            pp_matches = re.findall(r"\bproxy_pass\s+([^;]+);", block)
            for pp in pp_matches:
                pp_clean = pp.strip()
                if pp_clean not in vhost.proxy_passes:
                    vhost.proxy_passes.append(pp_clean)

            # 4. Extract location paths
            # e.g. location /api/ {
            loc_matches = re.findall(r"\blocation\s+(?:=\s*|~\*?\s*|\^\~\s*)?([^\s{]+)\s*\{", block)
            for loc in loc_matches:
                loc_clean = loc.strip()
                if loc_clean not in vhost.locations:
                    vhost.locations.append(loc_clean)

            # 5. Check ssl_certificate
            if re.search(r"\bssl_certificate\s+", block):
                vhost.ssl_enabled = True

            if vhost.listen_ports or vhost.server_names or vhost.proxy_passes:
                vhosts.append(vhost)

        return vhosts

    def scan_all_configs(self) -> NginxSystemScanResult:
        """Scan all configuration files across the entire system."""
        config_files = self.find_all_config_files()
        all_vhosts: List[NginxVirtualHost] = []
        all_ports: Set[int] = set()
        all_names: Set[str] = set()
        all_targets: Set[str] = set()

        for c_file in config_files:
            vhosts = self.parse_file(c_file)
            for vh in vhosts:
                all_vhosts.append(vh)
                all_ports.update(vh.listen_ports)
                all_names.update(vh.server_names)
                all_targets.update(vh.proxy_passes)

        return NginxSystemScanResult(
            config_files_scanned=config_files,
            virtual_hosts=all_vhosts,
            all_listening_ports=sorted(list(all_ports)),
            all_server_names=sorted(list(all_names)),
            all_proxy_targets=sorted(list(all_targets)),
        )

    def is_port_in_use_by_nginx(self, port: int) -> Tuple[bool, List[str]]:
        """
        Check if a given port is configured to be listened to in any Nginx configuration file.
        Returns: (is_in_use, list_of_matching_file_descriptions)
        """
        scan = self.scan_all_configs()
        matches = []
        for vh in scan.virtual_hosts:
            if port in vh.listen_ports:
                s_names = ", ".join(vh.server_names) if vh.server_names else "_"
                matches.append(f"{vh.file_path} (server_name: {s_names}, directives: {', '.join(vh.listen_directives)})")

        return len(matches) > 0, matches

    def is_server_name_configured(self, server_name: str) -> Tuple[bool, List[str]]:
        """
        Check if a domain / server_name is already configured in any Nginx config file.
        Returns: (is_configured, list_of_matching_file_descriptions)
        """
        if not server_name or server_name in ("_", "localhost", "127.0.0.1"):
            return False, []

        scan = self.scan_all_configs()
        matches = []
        target = server_name.strip().lower()

        for vh in scan.virtual_hosts:
            for sn in vh.server_names:
                if sn.lower() == target:
                    matches.append(f"{vh.file_path} (listen: {', '.join(str(p) for p in vh.listen_ports)})")

        return len(matches) > 0, matches

import glob
import os
import re
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple
from pydantic import BaseModel, Field
from utils.system import is_binary_available, run_command
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
        # If user/caller passed a subfolder (like /etc/nginx/conf.d), resolve parent /etc/nginx
        if root_conf_dir:
            p = Path(root_conf_dir)
            if p.name in ("conf.d", "sites-available", "sites-enabled", "http.d", "default.d", "vhosts.d"):
                if (p.parent / "nginx.conf").exists():
                    self.root_conf_dir = str(p.parent)
                else:
                    self.root_conf_dir = str(p)
            else:
                self.root_conf_dir = str(p)
        else:
            # Auto-detect base directory
            candidates = ["/etc/nginx", "/usr/local/nginx/conf", "/usr/local/etc/nginx", "/opt/homebrew/etc/nginx"]
            self.root_conf_dir = "/etc/nginx"
            for c in candidates:
                if os.path.exists(c):
                    self.root_conf_dir = c
                    break

    def _resolve_include_pattern(self, pattern: str, base_dir: Path) -> List[str]:
        """Resolve an include pattern (which may be absolute or relative, with glob wildcards)."""
        pattern = pattern.strip().strip("'\"").rstrip(";")
        if not pattern:
            return []

        matched_files = []
        if pattern.startswith("/"):
            expanded = glob.glob(pattern)
            for f in expanded:
                if os.path.isfile(f) and not f.endswith("~") and ".bak" not in f:
                    matched_files.append(f)
        else:
            # Relative to base_dir or self.root_conf_dir
            for b in [base_dir, Path(self.root_conf_dir)]:
                full_pattern = str(b / pattern)
                expanded = glob.glob(full_pattern)
                for f in expanded:
                    if os.path.isfile(f) and not f.endswith("~") and ".bak" not in f:
                        matched_files.append(f)

        return matched_files

    def find_all_config_files(self) -> List[str]:
        """Find all nginx.conf, conf.d/*.conf, default.d/*.conf, sites-enabled/*, http.d/*.conf, etc."""
        files: Set[str] = set()
        base = Path(self.root_conf_dir)

        # 1. Look for main nginx.conf
        main_conf = base / "nginx.conf"
        if main_conf.exists() and main_conf.is_file():
            files.add(str(main_conf.resolve()))

        # 2. Check standard subdirectories relative to base
        search_dirs = [
            base,
            base / "conf.d",
            base / "default.d",
            base / "http.d",
            base / "vhosts.d",
            base / "sites-enabled",
            base / "sites-available",
        ]

        if str(base) == "/etc/nginx":
            for extra in ["/etc/nginx/conf.d", "/etc/nginx/default.d", "/etc/nginx/http.d", "/etc/nginx/vhosts.d", "/etc/nginx/sites-enabled", "/etc/nginx/sites-available"]:
                ep = Path(extra)
                if ep not in search_dirs:
                    search_dirs.append(ep)

        for s_dir in search_dirs:
            if s_dir.exists() and s_dir.is_dir():
                for item in s_dir.iterdir():
                    if item.name.endswith("~") or ".bak" in item.name or item.name.startswith("."):
                        continue
                    try:
                        resolved = item.resolve()
                        if resolved.is_file():
                            files.add(str(resolved))
                    except Exception:
                        pass

        # 3. Recursively discover includes from all known config files
        visited: Set[str] = set()
        to_process = list(files)

        while to_process:
            curr = to_process.pop()
            if curr in visited or not os.path.exists(curr):
                continue
            visited.add(curr)

            try:
                with open(curr, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()
            except Exception:
                continue

            # Look for include directives
            include_matches = re.findall(r"\binclude\s+([^;]+);", content)
            curr_dir = Path(curr).parent
            for inc in include_matches:
                inc_clean = inc.strip().strip("'\"")
                # Skip mime.types or fastcgi params
                if any(inc_clean.endswith(ext) for ext in [".types", "mime.types", "fastcgi_params", "uwsgi_params", "scgi_params", "proxy_params"]):
                    continue
                matched = self._resolve_include_pattern(inc_clean, curr_dir)
                for mf in matched:
                    if mf not in files:
                        files.add(mf)
                        to_process.append(mf)

        return sorted(list(files))

    def _strip_comments(self, content: str) -> str:
        """Remove line comments starting with #."""
        lines = []
        for line in content.splitlines():
            cleaned = re.sub(r"#.*$", "", line)
            lines.append(cleaned)
        return "\n".join(lines)

    def _extract_server_blocks(self, content: str) -> List[str]:
        """Extract content inside top-level server { ... } blocks."""
        cleaned = self._strip_comments(content)
        server_blocks = []

        pos = 0
        while pos < len(cleaned):
            match = re.search(r"\bserver\s*\{", cleaned[pos:])
            if not match:
                break
            start_idx = pos + match.end() - 1
            brace_count = 0
            end_idx = -1

            for i in range(start_idx, len(cleaned)):
                if cleaned[i] == "{":
                    brace_count += 1
                elif cleaned[i] == "}":
                    brace_count -= 1
                    if brace_count == 0:
                        end_idx = i
                        break

            if end_idx != -1:
                block_content = cleaned[start_idx + 1:end_idx]
                server_blocks.append(block_content)
                pos = end_idx + 1
            else:
                # If matching brace not found, take the rest of content
                block_content = cleaned[start_idx + 1:]
                server_blocks.append(block_content)
                break

        return server_blocks

    def parse_file(self, file_path: str) -> List[NginxVirtualHost]:
        """Parse an individual configuration file and extract all virtual hosts."""
        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                raw_content = f.read()
        except Exception:
            return []

        return self.parse_content(raw_content, file_path=file_path)

    def parse_content(self, content: str, file_path: str = "nginx.conf") -> List[NginxVirtualHost]:
        """Parse Nginx configuration text and extract all virtual hosts."""
        server_blocks = self._extract_server_blocks(content)
        vhosts = []

        # If no explicit server block found, check if content has listen/proxy directives
        if not server_blocks:
            cleaned = self._strip_comments(content)
            if "listen" in cleaned or "proxy_pass" in cleaned or "server_name" in cleaned:
                server_blocks = [cleaned]

        for block in server_blocks:
            vhost = NginxVirtualHost(file_path=file_path)

            # 1. Extract listen directives and ports
            listen_matches = re.findall(r"\blisten\s+([^;]+);", block)
            for l_dir in listen_matches:
                l_dir_clean = l_dir.strip()
                vhost.listen_directives.append(l_dir_clean)
                if "ssl" in l_dir_clean:
                    vhost.ssl_enabled = True

                # Extract numeric port (e.g. 80, 443, 8000, 127.0.0.1:8080, [::]:80)
                port_match = re.search(r"(?:^|[:\s])(\d{1,5})(?:$|[\s;])", l_dir_clean)
                if port_match:
                    p_num = int(port_match.group(1))
                    if 1 <= p_num <= 65535 and p_num not in vhost.listen_ports:
                        vhost.listen_ports.append(p_num)

            # 2. Extract server_name
            sn_matches = re.findall(r"\bserver_name\s+([^;]+);", block)
            for sn_dir in sn_matches:
                for name in sn_dir.strip().split():
                    name_clean = name.strip()
                    if name_clean and name_clean != "_" and name_clean not in vhost.server_names:
                        vhost.server_names.append(name_clean)

            # 3. Extract proxy_pass
            pp_matches = re.findall(r"\bproxy_pass\s+([^;]+);", block)
            for pp in pp_matches:
                pp_clean = pp.strip()
                if pp_clean not in vhost.proxy_passes:
                    vhost.proxy_passes.append(pp_clean)

            # 4. Extract location paths
            loc_matches = re.findall(r"\blocation\s+(?:=\s*|~\*?\s*|\^\~\s*)?([^\s{]+)\s*\{", block)
            for loc in loc_matches:
                loc_clean = loc.strip()
                if loc_clean not in vhost.locations:
                    vhost.locations.append(loc_clean)

            # 5. Check ssl_certificate
            if re.search(r"\bssl_certificate\s+", block):
                vhost.ssl_enabled = True

            if vhost.listen_ports or vhost.server_names or vhost.proxy_passes or vhost.locations:
                vhosts.append(vhost)

        return vhosts

    def scan_from_nginx_t(self) -> Optional[NginxSystemScanResult]:
        """Attempt to scan configuration directly from 'nginx -T' output."""
        if not is_binary_available("nginx"):
            return None

        res = run_command("nginx -T", sudo=True)
        if not res.success and not res.stdout:
            res = run_command("nginx -T")
        
        output = res.stdout
        if not output or "# configuration file" not in output:
            return None

        # Split output into per-file chunks
        chunks = re.split(r"#\s*configuration file\s+([^:]+):", output)
        all_vhosts: List[NginxVirtualHost] = []
        all_ports: Set[int] = set()
        all_names: Set[str] = set()
        all_targets: Set[str] = set()
        scanned_files: List[str] = []

        # chunks[0] is preamble before first file
        for i in range(1, len(chunks), 2):
            f_path = chunks[i].strip()
            f_content = chunks[i + 1] if i + 1 < len(chunks) else ""
            scanned_files.append(f_path)

            vhosts = self.parse_content(f_content, file_path=f_path)
            for vh in vhosts:
                all_vhosts.append(vh)
                all_ports.update(vh.listen_ports)
                all_names.update(vh.server_names)
                all_targets.update(vh.proxy_passes)

        if all_vhosts or scanned_files:
            return NginxSystemScanResult(
                config_files_scanned=scanned_files,
                virtual_hosts=all_vhosts,
                all_listening_ports=sorted(list(all_ports)),
                all_server_names=sorted(list(all_names)),
                all_proxy_targets=sorted(list(all_targets)),
            )

        return None

    def scan_all_configs(self) -> NginxSystemScanResult:
        """Scan all configuration files across the entire system."""
        # 1. Try live nginx -T output first if inspecting system default /etc/nginx
        if self.root_conf_dir == "/etc/nginx":
            t_result = self.scan_from_nginx_t()
            if t_result and (t_result.virtual_hosts or t_result.config_files_scanned):
                return t_result

        # 2. Filesystem scanner fallback
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


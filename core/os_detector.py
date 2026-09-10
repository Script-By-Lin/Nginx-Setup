"""Operating System and distribution detection for Nginx directory structures and package managers."""

import os
import re
from pathlib import Path
from typing import Dict, Optional
from models.server_config import OSFamily, OSInfo, PackageManager
from utils.system import is_root, run_command


class OSDetector:
    """Detects host operating system, Linux distribution, package manager, and Nginx directories."""

    def __init__(self, os_release_path: str = "/etc/os-release", dry_run: bool = False):
        self.os_release_path = os_release_path
        self.dry_run = dry_run
        self._os_info: Optional[OSInfo] = None

    def parse_os_release(self) -> Dict[str, str]:
        """Parse standard /etc/os-release key-value pairs."""
        info = {}
        if not os.path.exists(self.os_release_path):
            return info

        try:
            with open(self.os_release_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, val = line.split("=", 1)
                    val = val.strip().strip('"').strip("'")
                    info[key.strip()] = val
        except Exception:
            pass

        return info

    def detect(self) -> OSInfo:
        """Detect OS information and configure appropriate paths."""
        if self._os_info:
            return self._os_info

        data = self.parse_os_release()
        distro_id = data.get("ID", "").lower()
        id_like = data.get("ID_LIKE", "").lower()
        name = data.get("NAME", "Linux")
        pretty_name = data.get("PRETTY_NAME", name)
        version_id = data.get("VERSION_ID", "")

        # Determine OS Family & Package Manager
        family = OSFamily.UNKNOWN
        pkg_manager = PackageManager.UNKNOWN
        conf_dir = "/etc/nginx/conf.d"
        sites_avail = None
        sites_enabled = None
        use_symlinks = False

        if distro_id in ["ubuntu", "debian", "linuxmint", "pop", "kali"] or "debian" in id_like or "ubuntu" in id_like:
            family = OSFamily.DEBIAN
            pkg_manager = PackageManager.APT
            conf_dir = "/etc/nginx/sites-available"
            sites_avail = "/etc/nginx/sites-available"
            sites_enabled = "/etc/nginx/sites-enabled"
            use_symlinks = True

        elif distro_id in ["rocky", "centos", "rhel", "almalinux", "fedora", "ol", "amzn"] or "rhel" in id_like or "fedora" in id_like or "centos" in id_like:
            family = OSFamily.RHEL
            pkg_manager = PackageManager.DNF if distro_id != "centos" or (version_id and int(version_id.split(".")[0]) >= 8) else PackageManager.YUM
            conf_dir = "/etc/nginx/conf.d"
            use_symlinks = False

        elif distro_id in ["arch", "cachyos", "manjaro", "endeavouros", "artix"] or "arch" in id_like:
            family = OSFamily.ARCH
            pkg_manager = PackageManager.PACMAN
            conf_dir = "/etc/nginx/conf.d"
            use_symlinks = False

        elif distro_id in ["alpine"]:
            family = OSFamily.ALPINE
            pkg_manager = PackageManager.APK
            conf_dir = "/etc/nginx/http.d" if os.path.exists("/etc/nginx/http.d") else "/etc/nginx/conf.d"
            use_symlinks = False

        elif distro_id in ["opensuse", "sles", "opensuse-tumbleweed", "opensuse-leap"] or "suse" in id_like:
            family = OSFamily.SUSE
            pkg_manager = PackageManager.ZYPPER
            conf_dir = "/etc/nginx/vhosts.d" if os.path.exists("/etc/nginx/vhosts.d") else "/etc/nginx/conf.d"
            use_symlinks = False

        else:
            # Generic fallback
            family = OSFamily.UNKNOWN
            pkg_manager = PackageManager.UNKNOWN
            conf_dir = "/etc/nginx/conf.d"

        # Detect service manager
        service_manager = "systemd"
        if not os.path.exists("/run/systemd/system"):
            if os.path.exists("/sbin/openrc-run") or os.path.exists("/etc/init.d"):
                service_manager = "openrc" if os.path.exists("/sbin/openrc-run") else "init.d"

        self._os_info = OSInfo(
            name=name,
            pretty_name=pretty_name,
            distro_id=distro_id,
            version_id=version_id,
            family=family,
            package_manager=pkg_manager,
            nginx_conf_dir=conf_dir,
            nginx_sites_available_dir=sites_avail,
            nginx_sites_enabled_dir=sites_enabled,
            use_symlinks=use_symlinks,
            service_manager=service_manager,
        )
        return self._os_info

    def ensure_include_directive(self, nginx_main_conf: str = "/etc/nginx/nginx.conf") -> bool:
        """
        Ensures that /etc/nginx/nginx.conf contains an 'include ...;' directive
        pointing to the virtual hosts configuration directory.
        Particularly needed on Arch Linux / custom Nginx distributions.
        """
        if not os.path.exists(nginx_main_conf):
            return False

        try:
            with open(nginx_main_conf, "r", encoding="utf-8") as f:
                content = f.read()

            os_info = self.detect()
            include_pattern = os_info.nginx_conf_dir + "/*.conf"

            # Check if include already exists
            if re.search(rf"include\s+({re.escape(include_pattern)}|conf\.d/\*\.conf|sites-enabled/\*);", content):
                return True

            # Insert inside http { ... } block before the closing brace
            http_match = re.search(r"http\s*\{", content)
            if not http_match:
                return False

            include_line = f"\n    # Added by Nginx-CLI\n    include {include_pattern};\n"
            
            # Find the last closing brace of http block
            last_brace_idx = content.rfind("}")
            if last_brace_idx == -1:
                return False

            new_content = content[:last_brace_idx] + include_line + content[last_brace_idx:]

            from utils.backup import BackupManager
            bm = BackupManager(dry_run=self.dry_run)
            bm.write_file(nginx_main_conf, new_content)
            return True

        except Exception:
            return False

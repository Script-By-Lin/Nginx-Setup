"""Backup and rollback manager for system configuration files."""

import datetime
import os
import shutil
import tempfile
from pathlib import Path
from typing import List, Optional
from utils.system import is_root, run_command


class BackupManager:
    """Manages file backups, safe writes with privilege escalation, and rollback capabilities."""

    def __init__(self, dry_run: bool = False):
        self.dry_run = dry_run

    @staticmethod
    def _is_writable(target_path: str) -> bool:
        """Check if target file or its parent directory is directly writable by the current user."""
        target = Path(target_path)
        if target.exists():
            return os.access(target_path, os.W_OK)
        parent = target.parent
        while not parent.exists() and parent != parent.parent:
            parent = parent.parent
        return os.access(str(parent), os.W_OK)

    def create_backup(self, target_path: str) -> Optional[str]:
        """
        Creates a timestamped backup of target_path if it exists.
        Returns the backup file path, or None if the target doesn't exist.
        """
        target = Path(target_path)
        if not target.exists():
            return None

        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = f"{target_path}.bak.{timestamp}"

        if self.dry_run:
            return backup_path

        if is_root() or self._is_writable(target_path):
            shutil.copy2(target_path, backup_path)
        else:
            res = run_command(["cp", "-p", target_path, backup_path], sudo=True)
            if not res.success:
                raise RuntimeError(f"Failed to create backup of {target_path}: {res.stderr}")

        return backup_path

    def write_file(self, target_path: str, content: str) -> Optional[str]:
        """
        Writes content to target_path with automatic backup.
        Supports writing to privileged directories (/etc/nginx/...) using sudo.
        Returns the backup path if an existing file was backed up.
        """
        target = Path(target_path)
        parent_dir = target.parent

        backup_path = self.create_backup(target_path)

        if self.dry_run:
            return backup_path

        # Ensure parent directory exists
        if not parent_dir.exists():
            if is_root() or self._is_writable(str(parent_dir.parent)):
                parent_dir.mkdir(parents=True, exist_ok=True)
            else:
                run_command(["mkdir", "-p", str(parent_dir)], sudo=True, check=True)

        if is_root() or self._is_writable(target_path):
            # Atomic write via temp file in same filesystem/parent dir
            temp_fd, temp_path = tempfile.mkstemp(dir=str(parent_dir) if parent_dir.exists() else None, prefix="nginx_tmp_")
            with os.fdopen(temp_fd, "w", encoding="utf-8") as f:
                f.write(content)
            os.chmod(temp_path, 0o644)
            shutil.move(temp_path, target_path)
        else:
            # Write via temporary file then sudo mv
            with tempfile.NamedTemporaryFile("w", delete=False, encoding="utf-8") as tf:
                tf.write(content)
                temp_path = tf.name
            
            try:
                run_command(["mv", temp_path, target_path], sudo=True, check=True)
                run_command(["chmod", "644", target_path], sudo=True, check=True)
            except Exception:
                if os.path.exists(temp_path):
                    os.remove(temp_path)
                raise

        return backup_path

    def rollback(self, target_path: str, backup_path: Optional[str]) -> bool:
        """
        Rolls back target_path to backup_path.
        If backup_path is None (meaning file didn't exist prior), deletes target_path.
        """
        if self.dry_run:
            return True

        if backup_path and os.path.exists(backup_path):
            if is_root() or self._is_writable(target_path):
                shutil.copy2(backup_path, target_path)
            else:
                run_command(["cp", "-p", backup_path, target_path], sudo=True, check=True)
            return True
        else:
            # Target did not exist previously, remove newly created file
            if os.path.exists(target_path):
                if is_root() or self._is_writable(target_path):
                    os.remove(target_path)
                else:
                    run_command(["rm", "-f", target_path], sudo=True, check=True)
            return True

    def list_backups(self, target_path: str) -> List[str]:
        """List all available backup files for a target config file, newest first."""
        target = Path(target_path)
        parent_dir = target.parent
        if not parent_dir.exists():
            return []

        prefix = f"{target.name}.bak."
        backups = [
            str(parent_dir / f)
            for f in os.listdir(parent_dir)
            if f.startswith(prefix)
        ]
        backups.sort(reverse=True)
        return backups

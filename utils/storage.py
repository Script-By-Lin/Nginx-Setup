"""Persistent SQLite storage manager for tracking configured projects, codes, and routes."""

import json
import os
import re
import sqlite3
from pathlib import Path
from typing import Dict, List, Optional
from models.server_config import ProjectState, RouteConfig, SystemdServiceState


class StateManager:
    """Manages persistent SQLite registry of configured Nginx projects and systemd services."""

    def __init__(self, custom_path: Optional[str] = None):
        if custom_path:
            self.db_path = Path(custom_path)
            self.state_dir = self.db_path.parent
        else:
            config_home = os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config"))
            self.state_dir = Path(config_home) / "nginx-setup"
            self.db_path = self.state_dir / "projects.db"

        self._ensure_storage()
        self._init_db()
        self._migrate_from_json_if_needed()

    def _ensure_storage(self) -> None:
        """Ensure parent directory exists."""
        self.state_dir.mkdir(parents=True, exist_ok=True)

    def _get_connection(self) -> sqlite3.Connection:
        """Get SQLite connection with Row factory enabled."""
        conn = sqlite3.connect(str(self.db_path), timeout=10.0)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        """Create tables and indices if they do not already exist."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS projects (
                    project_name TEXT PRIMARY KEY,
                    project_code TEXT UNIQUE NOT NULL,
                    domain TEXT,
                    config_file_path TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    ssl_enabled INTEGER NOT NULL DEFAULT 0,
                    ssl_type TEXT NOT NULL DEFAULT 'letsencrypt',
                    ssl_cert_path TEXT,
                    ssl_key_path TEXT,
                    ssl_email TEXT,
                    listen_port INTEGER NOT NULL DEFAULT 80,
                    ssl_port INTEGER NOT NULL DEFAULT 443,
                    routes_json TEXT NOT NULL DEFAULT '[]'
                )
                """
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_project_code ON projects (project_code COLLATE NOCASE)"
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_project_name ON projects (project_name COLLATE NOCASE)"
            )

            # Systemd background services table
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS systemd_services (
                    service_name TEXT PRIMARY KEY,
                    description TEXT NOT NULL,
                    user TEXT NOT NULL DEFAULT 'nginx',
                    working_dir TEXT NOT NULL,
                    exec_start TEXT NOT NULL,
                    restart TEXT NOT NULL DEFAULT 'always',
                    service_file_path TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    is_enabled INTEGER NOT NULL DEFAULT 1
                )
                """
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_service_name ON systemd_services (service_name COLLATE NOCASE)"
            )
            conn.commit()

    def _migrate_from_json_if_needed(self) -> None:
        """Auto-migrate legacy JSON state file to SQLite if JSON exists and SQLite is empty."""
        legacy_json = self.state_dir / "projects.json"
        if legacy_json.exists():
            try:
                with self._get_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute("SELECT COUNT(*) FROM projects")
                    count = cursor.fetchone()[0]
                    if count == 0:
                        with open(legacy_json, "r", encoding="utf-8") as f:
                            data = json.load(f)
                        for name, pdata in data.items():
                            pstate = ProjectState.model_validate(pdata)
                            self.save_project(pstate)
                # Remove legacy JSON file once migrated so it never resurrects deleted projects
                legacy_json.unlink(missing_ok=True)
            except Exception:
                try:
                    legacy_json.unlink(missing_ok=True)
                except Exception:
                    pass

    def _row_to_project_state(self, row: sqlite3.Row) -> ProjectState:
        """Convert a SQLite row into a ProjectState model."""
        routes_data = json.loads(row["routes_json"]) if row["routes_json"] else []
        routes = [RouteConfig.model_validate(r) for r in routes_data]
        return ProjectState(
            project_code=row["project_code"],
            project_name=row["project_name"],
            domain=row["domain"],
            config_file_path=row["config_file_path"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            ssl_enabled=bool(row["ssl_enabled"]),
            ssl_type=row["ssl_type"],
            ssl_cert_path=row["ssl_cert_path"],
            ssl_key_path=row["ssl_key_path"],
            ssl_email=row["ssl_email"],
            listen_port=row["listen_port"],
            ssl_port=row["ssl_port"],
            routes=routes,
        )

    def generate_next_project_code(self) -> str:
        """Generate next sequential Project Code (e.g. SE-001, SE-002, etc.)."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT project_code FROM projects")
            rows = cursor.fetchall()

        max_num = 0
        for row in rows:
            code = row["project_code"]
            if code:
                match = re.search(r"SE-(\d+)", code, re.IGNORECASE)
                if match:
                    max_num = max(max_num, int(match.group(1)))
        return f"SE-{max_num + 1:03d}"

    def list_projects(self) -> List[ProjectState]:
        """List all registered projects ordered by project_code."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM projects ORDER BY project_code ASC")
            rows = cursor.fetchall()
            return [self._row_to_project_state(row) for row in rows]

    def load_all(self) -> Dict[str, ProjectState]:
        """Load all registered projects as a dictionary keyed by project_name."""
        projects = self.list_projects()
        return {p.project_name: p for p in projects}

    def get_project(self, identifier: str) -> Optional[ProjectState]:
        """
        Get project state by project name, Project Code (e.g. SE-001), or 1-based index number.
        """
        if not identifier:
            return None

        clean_id = identifier.strip()

        with self._get_connection() as conn:
            cursor = conn.cursor()

            # 1. Match exact project_name
            cursor.execute("SELECT * FROM projects WHERE project_name = ?", (clean_id,))
            row = cursor.fetchone()
            if row:
                return self._row_to_project_state(row)

            # 2. Match case-insensitive project_code (e.g. SE-001)
            cursor.execute("SELECT * FROM projects WHERE project_code = ? COLLATE NOCASE", (clean_id,))
            row = cursor.fetchone()
            if row:
                return self._row_to_project_state(row)

            # 3. Match case-insensitive project_name
            cursor.execute("SELECT * FROM projects WHERE project_name = ? COLLATE NOCASE", (clean_id,))
            row = cursor.fetchone()
            if row:
                return self._row_to_project_state(row)

        # 4. Match 1-based index number (e.g. '1', '2')
        if clean_id.isdigit():
            idx = int(clean_id) - 1
            all_projs = self.list_projects()
            if 0 <= idx < len(all_projs):
                return all_projs[idx]

        return None

    def save_project(self, project: ProjectState) -> None:
        """Save or update a project's state in SQLite with ACID safety."""
        existing = self.get_project(project.project_name)

        # Handle Project Code assignment
        if not existing:
            if not project.project_code or project.project_code == "SE-001":
                # Check if SE-001 is already taken by another project
                with self._get_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute("SELECT 1 FROM projects WHERE project_code = ?", (project.project_code,))
                    if cursor.fetchone():
                        project.project_code = self.generate_next_project_code()
        else:
            # Preserve existing project code if updating and not explicitly changed
            if existing.project_code and not project.project_code:
                project.project_code = existing.project_code

        routes_json = json.dumps([r.model_dump() for r in project.routes])

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO projects (
                    project_name, project_code, domain, config_file_path,
                    created_at, updated_at, ssl_enabled, ssl_type,
                    ssl_cert_path, ssl_key_path, ssl_email,
                    listen_port, ssl_port, routes_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(project_name) DO UPDATE SET
                    project_code = excluded.project_code,
                    domain = excluded.domain,
                    config_file_path = excluded.config_file_path,
                    created_at = excluded.created_at,
                    updated_at = excluded.updated_at,
                    ssl_enabled = excluded.ssl_enabled,
                    ssl_type = excluded.ssl_type,
                    ssl_cert_path = excluded.ssl_cert_path,
                    ssl_key_path = excluded.ssl_key_path,
                    ssl_email = excluded.ssl_email,
                    listen_port = excluded.listen_port,
                    ssl_port = excluded.ssl_port,
                    routes_json = excluded.routes_json
                """,
                (
                    project.project_name,
                    project.project_code,
                    project.domain,
                    project.config_file_path,
                    project.created_at,
                    project.updated_at,
                    1 if project.ssl_enabled else 0,
                    project.ssl_type,
                    project.ssl_cert_path,
                    project.ssl_key_path,
                    project.ssl_email,
                    project.listen_port,
                    project.ssl_port,
                    routes_json,
                ),
            )
            conn.commit()

    def delete_project(self, identifier: str) -> bool:
        """Remove a project from the SQLite database by name, Project Code, or index."""
        # Clean up legacy json file if it exists so deleted project cannot be re-imported
        legacy_json = self.state_dir / "projects.json"
        if legacy_json.exists():
            try:
                legacy_json.unlink(missing_ok=True)
            except Exception:
                pass

        target = self.get_project(identifier)
        if not target:
            # Attempt direct delete by identifier in case target object lookup differed
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "DELETE FROM projects WHERE project_name = ? OR project_code = ? COLLATE NOCASE",
                    (identifier, identifier),
                )
                conn.commit()
                return cursor.rowcount > 0

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "DELETE FROM projects WHERE project_name = ? OR project_code = ? COLLATE NOCASE",
                (target.project_name, target.project_code),
            )
            conn.commit()
            return cursor.rowcount > 0


    # -------------------------------------------------------------
    # Systemd Background Services Persistence
    # -------------------------------------------------------------

    def _row_to_service_state(self, row: sqlite3.Row) -> SystemdServiceState:
        """Convert a SQLite row to SystemdServiceState."""
        return SystemdServiceState(
            service_name=row["service_name"],
            description=row["description"],
            user=row["user"],
            working_dir=row["working_dir"],
            exec_start=row["exec_start"],
            restart=row["restart"],
            service_file_path=row["service_file_path"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            is_enabled=bool(row["is_enabled"]),
        )

    def list_services(self) -> List[SystemdServiceState]:
        """List all managed systemd services ordered by service_name."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM systemd_services ORDER BY service_name ASC")
            rows = cursor.fetchall()
            return [self._row_to_service_state(row) for row in rows]

    def get_service(self, identifier: str) -> Optional[SystemdServiceState]:
        """
        Get systemd service state by service name (with or without .service) or 1-based index number.
        """
        if not identifier:
            return None

        clean_id = identifier.strip()
        if clean_id.endswith(".service"):
            clean_id = clean_id[:-8]

        with self._get_connection() as conn:
            cursor = conn.cursor()

            # 1. Match exact service_name
            cursor.execute("SELECT * FROM systemd_services WHERE service_name = ?", (clean_id,))
            row = cursor.fetchone()
            if row:
                return self._row_to_service_state(row)

            # 2. Match case-insensitive service_name
            cursor.execute("SELECT * FROM systemd_services WHERE service_name = ? COLLATE NOCASE", (clean_id,))
            row = cursor.fetchone()
            if row:
                return self._row_to_service_state(row)

        # 3. Match 1-based index number (e.g. '1', '2')
        if clean_id.isdigit():
            idx = int(clean_id) - 1
            all_svcs = self.list_services()
            if 0 <= idx < len(all_svcs):
                return all_svcs[idx]

        return None

    def save_service(self, service: SystemdServiceState) -> None:
        """Save or update a systemd service state in SQLite with ACID safety."""
        clean_name = service.service_name.strip()
        if clean_name.endswith(".service"):
            clean_name = clean_name[:-8]

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO systemd_services (
                    service_name, description, user, working_dir,
                    exec_start, restart, service_file_path,
                    created_at, updated_at, is_enabled
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(service_name) DO UPDATE SET
                    description = excluded.description,
                    user = excluded.user,
                    working_dir = excluded.working_dir,
                    exec_start = excluded.exec_start,
                    restart = excluded.restart,
                    service_file_path = excluded.service_file_path,
                    created_at = excluded.created_at,
                    updated_at = excluded.updated_at,
                    is_enabled = excluded.is_enabled
                """,
                (
                    clean_name,
                    service.description,
                    service.user,
                    service.working_dir,
                    service.exec_start,
                    service.restart,
                    service.service_file_path,
                    service.created_at,
                    service.updated_at,
                    1 if service.is_enabled else 0,
                ),
            )
            conn.commit()

    def delete_service(self, identifier: str) -> bool:
        """Remove a systemd service record from the SQLite database."""
        target = self.get_service(identifier)
        if not target:
            return False

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM systemd_services WHERE service_name = ?", (target.service_name,))
            conn.commit()
            return cursor.rowcount > 0


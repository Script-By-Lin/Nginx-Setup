"""Persistent storage manager for tracking configured projects and services."""

import json
import os
from pathlib import Path
from typing import Dict, List, Optional
from models.server_config import ProjectState, RouteConfig


class StateManager:
    """Manages persistent JSON registry of configured Nginx projects and routes."""

    def __init__(self, custom_path: Optional[str] = None):
        if custom_path:
            self.state_file = Path(custom_path)
        else:
            config_home = os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config"))
            self.state_dir = Path(config_home) / "nginx-setup"
            self.state_file = self.state_dir / "projects.json"

    def _ensure_storage(self) -> None:
        """Ensure parent directory exists."""
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        if not self.state_file.exists():
            with open(self.state_file, "w", encoding="utf-8") as f:
                json.dump({}, f, indent=2)

    def load_all(self) -> Dict[str, ProjectState]:
        """Load all registered projects from disk."""
        self._ensure_storage()
        try:
            with open(self.state_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            return {name: ProjectState.model_validate(pdata) for name, pdata in data.items()}
        except Exception:
            return {}

    def get_project(self, project_name: str) -> Optional[ProjectState]:
        """Get state for a specific project."""
        projects = self.load_all()
        return projects.get(project_name)

    def save_project(self, project: ProjectState) -> None:
        """Save or update a project's state in the registry."""
        projects = self.load_all()
        projects[project.project_name] = project
        self._write_all(projects)

    def delete_project(self, project_name: str) -> bool:
        """Remove a project from the registry."""
        projects = self.load_all()
        if project_name in projects:
            del projects[project_name]
            self._write_all(projects)
            return True
        return False

    def list_projects(self) -> List[ProjectState]:
        """List all registered projects."""
        return list(self.load_all().values())

    def _write_all(self, projects: Dict[str, ProjectState]) -> None:
        """Write all projects to the storage file."""
        self._ensure_storage()
        data = {name: p.model_dump() for name, p in projects.items()}
        temp_file = self.state_file.with_suffix(".tmp")
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        temp_file.replace(self.state_file)

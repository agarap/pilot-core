"""Test project structure validation enforcement."""

import subprocess
import tempfile
import pytest
from pathlib import Path
from pilot_core.validate import check_project_structure


class TestProjectStructureValidation:
    """Test project structure validation."""

    def test_project_without_runs_warns(self, tmp_path, monkeypatch):
        """Project without .runs/ should produce warning."""
        # Create a project without .runs
        project_dir = tmp_path / "projects" / "test-project"
        project_dir.mkdir(parents=True)
        (project_dir / "output.txt").write_text("test")

        monkeypatch.chdir(tmp_path)

        files = ["projects/test-project/output.txt"]
        errors = check_project_structure(files)

        # Should produce error about missing .runs/
        assert len(errors) > 0
        assert "no .runs/ directory" in errors[0].lower() or ".runs" in errors[0]

    def test_project_with_runs_passes(self, tmp_path, monkeypatch):
        """Project with .runs/ should not produce warning."""
        # Create a project with .runs
        project_dir = tmp_path / "projects" / "test-project"
        runs_dir = project_dir / ".runs"
        runs_dir.mkdir(parents=True)
        (project_dir / "output.txt").write_text("test")

        monkeypatch.chdir(tmp_path)

        files = ["projects/test-project/output.txt"]
        errors = check_project_structure(files)

        # Should NOT produce error
        assert len(errors) == 0

    def test_gitkeep_ignored(self, tmp_path, monkeypatch):
        """Changes to .gitkeep should be ignored."""
        project_dir = tmp_path / "projects"
        project_dir.mkdir(parents=True)
        (project_dir / ".gitkeep").write_text("")

        monkeypatch.chdir(tmp_path)

        files = ["projects/.gitkeep"]
        errors = check_project_structure(files)

        assert len(errors) == 0

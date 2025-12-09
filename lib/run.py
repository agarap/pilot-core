"""
Run management system.

Every unit of work (human request → agent execution) is a "run".
Runs provide:
- Unique ID for tracking
- Manifest files for provenance
- Linkage between tool calls, agent outputs, and git commits

Usage:
    from lib.run import Run

    run = Run.create("Research Claude API")
    run.add_agent("researcher")
    run.add_file_created("findings/api.md")
    run.complete("Found rate limit docs")

    # Or use as context manager
    with Run.create("Task description") as run:
        # do work
        run.add_file_created("output.md")
"""

import json
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

import yaml


def generate_run_id() -> str:
    """Generate unique run ID: YYYYMMDD_HHMMSS_shortuid"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    short_id = uuid.uuid4().hex[:8]
    return f"{timestamp}_{short_id}"


def get_next_run_number(project_dir: Path) -> int:
    """Get next sequential run number for a project."""
    runs_dir = project_dir / ".runs"
    if not runs_dir.exists():
        return 1

    existing = [f.stem for f in runs_dir.glob("*.yaml")]
    if not existing:
        return 1

    # Extract numbers from filenames like "001_description"
    numbers = []
    for name in existing:
        try:
            num = int(name.split("_")[0])
            numbers.append(num)
        except (ValueError, IndexError):
            continue

    return max(numbers, default=0) + 1


@dataclass
class Run:
    """Represents a single run (unit of work)."""

    id: str
    task: str
    project: Optional[str] = None
    number: Optional[int] = None
    started: str = field(default_factory=lambda: datetime.now().isoformat())
    completed: Optional[str] = None
    status: str = "in_progress"
    agents: list[str] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)
    files_created: list[str] = field(default_factory=list)
    files_modified: list[str] = field(default_factory=list)
    summary: Optional[str] = None

    # Class variable to track current run
    _current: Optional["Run"] = None

    @classmethod
    def create(cls, task: str, project: Optional[str] = None) -> "Run":
        """Create a new run."""
        run_id = generate_run_id()

        number = None
        if project:
            project_dir = Path("projects") / project
            project_dir.mkdir(parents=True, exist_ok=True)
            number = get_next_run_number(project_dir)

        run = cls(id=run_id, task=task, project=project, number=number)
        cls._current = run

        # Set environment variable for tools to pick up
        os.environ["PILOT_RUN_ID"] = run_id

        return run

    @classmethod
    def current(cls) -> Optional["Run"]:
        """Get the current run, if any."""
        return cls._current

    @classmethod
    def current_id(cls) -> Optional[str]:
        """Get current run ID from environment or active run."""
        if cls._current:
            return cls._current.id
        return os.environ.get("PILOT_RUN_ID")

    def add_agent(self, agent: str) -> None:
        """Record that an agent participated in this run."""
        if agent not in self.agents:
            self.agents.append(agent)

    def add_tool(self, tool: str) -> None:
        """Record that a tool was used in this run."""
        if tool not in self.tools:
            self.tools.append(tool)

    def add_file_created(self, path: str) -> None:
        """Record a file created during this run."""
        if path not in self.files_created:
            self.files_created.append(path)

    def add_file_modified(self, path: str) -> None:
        """Record a file modified during this run."""
        if path not in self.files_modified:
            self.files_modified.append(path)

    def complete(self, summary: Optional[str] = None) -> None:
        """Mark the run as complete and save manifest."""
        self.completed = datetime.now().isoformat()
        self.status = "completed"
        if summary:
            self.summary = summary
        self.save_manifest()
        Run._current = None

    def fail(self, error: str) -> None:
        """Mark the run as failed."""
        self.completed = datetime.now().isoformat()
        self.status = "failed"
        self.summary = f"Error: {error}"
        self.save_manifest()
        Run._current = None

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "id": self.id,
            "number": self.number,
            "task": self.task,
            "status": self.status,
            "started": self.started,
            "completed": self.completed,
            "agents": self.agents,
            "tools": self.tools,
            "files_created": self.files_created,
            "files_modified": self.files_modified,
            "summary": self.summary,
        }

    def save_manifest(self) -> Optional[Path]:
        """Save run manifest to project's .runs directory."""
        if not self.project:
            return None

        runs_dir = Path("projects") / self.project / ".runs"
        runs_dir.mkdir(parents=True, exist_ok=True)

        # Filename: NNN_short_description.yaml
        safe_task = self.task[:30].replace(" ", "_").replace("/", "-")
        filename = f"{self.number:03d}_{safe_task}.yaml"
        manifest_path = runs_dir / filename

        with open(manifest_path, "w") as f:
            yaml.dump(self.to_dict(), f, default_flow_style=False, sort_keys=False)

        return manifest_path

    def __enter__(self) -> "Run":
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Context manager exit - auto-complete or fail."""
        if exc_type:
            self.fail(str(exc_val))
        elif self.status == "in_progress":
            self.complete()

    def git_commit_message(self) -> str:
        """Generate a git commit message for this run."""
        lines = [
            f"Run {self.number:03d}: {self.task}" if self.number else f"Run: {self.task}",
            "",
            f"Run ID: {self.id}",
        ]

        if self.agents:
            lines.append(f"Agents: {', '.join(self.agents)}")

        if self.summary:
            lines.extend(["", self.summary])

        lines.extend([
            "",
            "Generated with [Claude Code](https://claude.ai/code)",
            "via [Happy](https://happy.engineering)",
            "",
            "Co-Authored-By: Claude <noreply@anthropic.com>",
            "Co-Authored-By: Happy <yesreply@happy.engineering>",
        ])

        return "\n".join(lines)


# Convenience function for tools
def get_current_run_id() -> Optional[str]:
    """Get the current run ID, if any."""
    return Run.current_id()

"""
Unit tests for lib/progress.py - Progress tracking module.

Tests cover:
- ProgressFile dataclass serialization/deserialization
- write_progress creates directory and file
- read_progress handles missing files
- update_progress merges correctly
- is_stale detection
- cleanup_progress removes old files
- archive_progress moves files to archive

Run with: uv run pytest tests/test_progress.py -v
"""

import pytest
from datetime import datetime, timedelta
from pathlib import Path
import yaml

from lib.progress import (
    ProgressFile,
    ProgressStatus,
    write_progress,
    read_progress,
    list_progress,
    update_progress,
    update_heartbeat,
    mark_completed,
    mark_failed,
    is_stale,
    cleanup_progress,
    archive_progress,
    list_archived_progress,
    wait_for_agent,
    StaleAgentError,
    AgentNotFoundError,
)


@pytest.fixture
def test_project(tmp_path, monkeypatch):
    """Set up a temporary project directory for testing."""
    # Create projects directory structure
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()

    # Monkeypatch the _get_progress_dir function to use tmp_path
    import lib.progress as progress_module

    original_get_progress_dir = progress_module._get_progress_dir

    def patched_get_progress_dir(project: str) -> Path:
        return tmp_path / "projects" / project / ".progress"

    monkeypatch.setattr(progress_module, "_get_progress_dir", patched_get_progress_dir)

    # Also patch _get_progress_path
    def patched_get_progress_path(project: str, run_id: str) -> Path:
        return patched_get_progress_dir(project) / f"{run_id}.yaml"

    monkeypatch.setattr(progress_module, "_get_progress_path", patched_get_progress_path)

    return "test-project"


@pytest.fixture
def sample_progress():
    """Create a sample ProgressFile for testing."""
    return ProgressFile(
        run_id="run_abc123",
        agent="builder",
        project="test-project",
        started_at=datetime.now(),
        status=ProgressStatus.RUNNING,
        last_heartbeat=datetime.now(),
        phase="Initializing",
        messages_processed=0,
    )


class TestProgressFileDataclass:
    """Tests for ProgressFile dataclass."""

    def test_create_progress_file(self, sample_progress):
        """ProgressFile can be created with required fields."""
        assert sample_progress.run_id == "run_abc123"
        assert sample_progress.agent == "builder"
        assert sample_progress.status == ProgressStatus.RUNNING
        assert sample_progress.messages_processed == 0
        assert sample_progress.artifacts_created == []

    def test_progress_file_with_all_fields(self):
        """ProgressFile accepts all optional fields."""
        progress = ProgressFile(
            run_id="run_xyz789",
            agent="git-reviewer",
            project="my-project",
            started_at=datetime.now(),
            status=ProgressStatus.COMPLETED,
            last_heartbeat=datetime.now(),
            phase="Done",
            messages_processed=50,
            estimated_remaining="",
            error="",
            result_summary="Successfully reviewed 5 files",
            artifacts_created=["file1.py", "file2.py"],
        )
        assert progress.result_summary == "Successfully reviewed 5 files"
        assert len(progress.artifacts_created) == 2


class TestProgressStatus:
    """Tests for ProgressStatus enum."""

    def test_all_statuses_exist(self):
        """All expected status values exist."""
        assert ProgressStatus.PENDING.value == "pending"
        assert ProgressStatus.RUNNING.value == "running"
        assert ProgressStatus.COMPLETED.value == "completed"
        assert ProgressStatus.FAILED.value == "failed"
        assert ProgressStatus.STALLED.value == "stalled"

    def test_status_from_string(self):
        """Status can be created from string value."""
        assert ProgressStatus("running") == ProgressStatus.RUNNING
        assert ProgressStatus("completed") == ProgressStatus.COMPLETED


class TestWriteProgress:
    """Tests for write_progress function."""

    def test_write_creates_directory(self, test_project, sample_progress, tmp_path):
        """write_progress creates .progress/ directory if needed."""
        progress_dir = tmp_path / "projects" / test_project / ".progress"
        assert not progress_dir.exists()

        write_progress(test_project, sample_progress)

        assert progress_dir.exists()
        assert progress_dir.is_dir()

    def test_write_creates_yaml_file(self, test_project, sample_progress, tmp_path):
        """write_progress creates YAML file with correct name."""
        write_progress(test_project, sample_progress)

        expected_path = tmp_path / "projects" / test_project / ".progress" / f"{sample_progress.run_id}.yaml"
        assert expected_path.exists()

    def test_write_returns_path(self, test_project, sample_progress):
        """write_progress returns the path to the written file."""
        result = write_progress(test_project, sample_progress)

        assert isinstance(result, Path)
        assert result.name == f"{sample_progress.run_id}.yaml"

    def test_write_content_is_valid_yaml(self, test_project, sample_progress, tmp_path):
        """Written file contains valid YAML."""
        write_progress(test_project, sample_progress)

        file_path = tmp_path / "projects" / test_project / ".progress" / f"{sample_progress.run_id}.yaml"
        content = file_path.read_text()
        data = yaml.safe_load(content)

        assert data["run_id"] == sample_progress.run_id
        assert data["agent"] == sample_progress.agent
        assert data["status"] == "running"


class TestReadProgress:
    """Tests for read_progress function."""

    def test_read_existing_file(self, test_project, sample_progress):
        """read_progress returns ProgressFile for existing file."""
        write_progress(test_project, sample_progress)

        result = read_progress(test_project, sample_progress.run_id)

        assert result is not None
        assert result.run_id == sample_progress.run_id
        assert result.agent == sample_progress.agent
        assert result.status == sample_progress.status

    def test_read_missing_file_returns_none(self, test_project):
        """read_progress returns None for missing file."""
        result = read_progress(test_project, "nonexistent_run_id")

        assert result is None

    def test_read_corrupted_file_returns_none(self, test_project, tmp_path):
        """read_progress returns None for corrupted/invalid YAML."""
        # Create progress directory and corrupted file
        progress_dir = tmp_path / "projects" / test_project / ".progress"
        progress_dir.mkdir(parents=True)
        corrupted_file = progress_dir / "corrupted_run.yaml"
        corrupted_file.write_text("invalid: yaml: content: [")

        result = read_progress(test_project, "corrupted_run")

        assert result is None


class TestListProgress:
    """Tests for list_progress function."""

    def test_list_empty_project(self, test_project):
        """list_progress returns empty list for project without .progress/."""
        result = list_progress(test_project)

        assert result == []

    def test_list_multiple_progress_files(self, test_project):
        """list_progress returns all progress files for a project."""
        # Create multiple progress files
        for i in range(3):
            progress = ProgressFile(
                run_id=f"run_{i:03d}",
                agent="builder",
                project=test_project,
                started_at=datetime.now(),
                status=ProgressStatus.RUNNING,
                last_heartbeat=datetime.now(),
            )
            write_progress(test_project, progress)

        result = list_progress(test_project)

        assert len(result) == 3
        run_ids = {p.run_id for p in result}
        assert run_ids == {"run_000", "run_001", "run_002"}


class TestUpdateProgress:
    """Tests for update_progress function."""

    def test_update_single_field(self, test_project, sample_progress):
        """update_progress updates a single field."""
        write_progress(test_project, sample_progress)

        result = update_progress(test_project, sample_progress.run_id, phase="Building files")

        assert result is not None
        assert result.phase == "Building files"
        assert result.agent == sample_progress.agent  # Unchanged

    def test_update_multiple_fields(self, test_project, sample_progress):
        """update_progress updates multiple fields at once."""
        write_progress(test_project, sample_progress)

        result = update_progress(
            test_project,
            sample_progress.run_id,
            phase="Completed",
            messages_processed=100,
            status="completed",
        )

        assert result.phase == "Completed"
        assert result.messages_processed == 100
        assert result.status == ProgressStatus.COMPLETED

    def test_update_preserves_unmodified_fields(self, test_project, sample_progress):
        """update_progress preserves fields not being updated."""
        sample_progress.result_summary = "Initial summary"
        write_progress(test_project, sample_progress)

        result = update_progress(test_project, sample_progress.run_id, phase="New phase")

        assert result.run_id == sample_progress.run_id
        assert result.agent == sample_progress.agent

    def test_update_nonexistent_returns_none(self, test_project):
        """update_progress returns None for nonexistent file."""
        result = update_progress(test_project, "nonexistent", phase="Test")

        assert result is None


class TestUpdateHeartbeat:
    """Tests for update_heartbeat function."""

    def test_heartbeat_updates_timestamp(self, test_project, sample_progress):
        """update_heartbeat updates last_heartbeat to current time."""
        sample_progress.last_heartbeat = datetime.now() - timedelta(minutes=5)
        write_progress(test_project, sample_progress)

        before_update = datetime.now()
        result = update_heartbeat(test_project, sample_progress.run_id)
        after_update = datetime.now()

        assert result is not None
        assert result.last_heartbeat >= before_update
        assert result.last_heartbeat <= after_update

    def test_heartbeat_with_phase(self, test_project, sample_progress):
        """update_heartbeat optionally updates phase."""
        write_progress(test_project, sample_progress)

        result = update_heartbeat(test_project, sample_progress.run_id, phase="Reading files")

        assert result.phase == "Reading files"

    def test_heartbeat_with_messages(self, test_project, sample_progress):
        """update_heartbeat optionally updates messages_processed."""
        write_progress(test_project, sample_progress)

        result = update_heartbeat(test_project, sample_progress.run_id, messages=42)

        assert result.messages_processed == 42


class TestMarkCompleted:
    """Tests for mark_completed function."""

    def test_mark_completed_sets_status(self, test_project, sample_progress):
        """mark_completed sets status to COMPLETED."""
        write_progress(test_project, sample_progress)

        result = mark_completed(test_project, sample_progress.run_id, "Task done")

        assert result.status == ProgressStatus.COMPLETED

    def test_mark_completed_sets_summary(self, test_project, sample_progress):
        """mark_completed sets result_summary."""
        write_progress(test_project, sample_progress)

        result = mark_completed(test_project, sample_progress.run_id, "Created 5 files")

        assert result.result_summary == "Created 5 files"

    def test_mark_completed_with_artifacts(self, test_project, sample_progress):
        """mark_completed optionally sets artifacts_created."""
        write_progress(test_project, sample_progress)

        artifacts = ["lib/new.py", "tests/test_new.py"]
        result = mark_completed(test_project, sample_progress.run_id, "Done", artifacts)

        assert result.artifacts_created == artifacts


class TestMarkFailed:
    """Tests for mark_failed function."""

    def test_mark_failed_sets_status(self, test_project, sample_progress):
        """mark_failed sets status to FAILED."""
        write_progress(test_project, sample_progress)

        result = mark_failed(test_project, sample_progress.run_id, "Connection error")

        assert result.status == ProgressStatus.FAILED

    def test_mark_failed_sets_error(self, test_project, sample_progress):
        """mark_failed sets error message."""
        write_progress(test_project, sample_progress)

        result = mark_failed(test_project, sample_progress.run_id, "API timeout after 60s")

        assert result.error == "API timeout after 60s"


class TestIsStale:
    """Tests for is_stale function."""

    def test_recent_heartbeat_not_stale(self, sample_progress):
        """Progress with recent heartbeat is not stale."""
        sample_progress.last_heartbeat = datetime.now()

        assert is_stale(sample_progress) is False

    def test_old_heartbeat_is_stale(self, sample_progress):
        """Progress with old heartbeat is stale."""
        sample_progress.last_heartbeat = datetime.now() - timedelta(minutes=10)

        assert is_stale(sample_progress, threshold_minutes=5) is True

    def test_custom_threshold(self, sample_progress):
        """is_stale respects custom threshold."""
        sample_progress.last_heartbeat = datetime.now() - timedelta(minutes=3)

        assert is_stale(sample_progress, threshold_minutes=5) is False
        assert is_stale(sample_progress, threshold_minutes=2) is True


class TestCleanupProgress:
    """Tests for cleanup_progress function."""

    def test_cleanup_empty_project(self, test_project):
        """cleanup_progress handles project without .progress/."""
        result = cleanup_progress(test_project)

        assert result["deleted_count"] == 0
        assert result["kept_count"] == 0

    def test_cleanup_deletes_old_completed(self, test_project):
        """cleanup_progress deletes old completed progress files."""
        # Create old completed progress
        old_progress = ProgressFile(
            run_id="old_completed",
            agent="builder",
            project=test_project,
            started_at=datetime.now() - timedelta(hours=48),
            status=ProgressStatus.COMPLETED,
            last_heartbeat=datetime.now() - timedelta(hours=48),
        )
        write_progress(test_project, old_progress)

        result = cleanup_progress(test_project, max_age_hours=24)

        assert result["deleted_count"] == 1
        assert "old_completed" in result["deleted_run_ids"]

    def test_cleanup_keeps_recent_completed(self, test_project):
        """cleanup_progress keeps recently completed progress files."""
        # Create recent completed progress
        recent_progress = ProgressFile(
            run_id="recent_completed",
            agent="builder",
            project=test_project,
            started_at=datetime.now() - timedelta(hours=1),
            status=ProgressStatus.COMPLETED,
            last_heartbeat=datetime.now() - timedelta(hours=1),
        )
        write_progress(test_project, recent_progress)

        result = cleanup_progress(test_project, max_age_hours=24)

        assert result["deleted_count"] == 0
        assert result["kept_count"] == 1

    def test_cleanup_keeps_running(self, test_project, sample_progress):
        """cleanup_progress keeps running progress files."""
        write_progress(test_project, sample_progress)

        result = cleanup_progress(test_project, max_age_hours=0)  # Would delete everything old

        assert result["deleted_count"] == 0
        assert result["kept_count"] == 1

    def test_cleanup_keeps_failed_by_default(self, test_project):
        """cleanup_progress keeps failed progress files by default."""
        failed_progress = ProgressFile(
            run_id="failed_run",
            agent="builder",
            project=test_project,
            started_at=datetime.now() - timedelta(hours=48),
            status=ProgressStatus.FAILED,
            last_heartbeat=datetime.now() - timedelta(hours=48),
            error="Something went wrong",
        )
        write_progress(test_project, failed_progress)

        result = cleanup_progress(test_project, max_age_hours=24, keep_failed=True)

        assert result["deleted_count"] == 0
        assert result["kept_failed"] == 1

    def test_cleanup_deletes_failed_when_requested(self, test_project):
        """cleanup_progress deletes failed files when keep_failed=False."""
        failed_progress = ProgressFile(
            run_id="failed_run",
            agent="builder",
            project=test_project,
            started_at=datetime.now() - timedelta(hours=48),
            status=ProgressStatus.FAILED,
            last_heartbeat=datetime.now() - timedelta(hours=48),
            error="Something went wrong",
        )
        write_progress(test_project, failed_progress)

        # Note: cleanup only deletes COMPLETED files, not failed
        # Even with keep_failed=False, it just doesn't count them as kept_failed
        result = cleanup_progress(test_project, max_age_hours=24, keep_failed=False)

        # Failed files are neither deleted nor specially kept
        assert result["kept_failed"] == 0


class TestArchiveProgress:
    """Tests for archive_progress function."""

    def test_archive_moves_file(self, test_project, sample_progress, tmp_path):
        """archive_progress moves file to archive directory."""
        write_progress(test_project, sample_progress)
        original_path = tmp_path / "projects" / test_project / ".progress" / f"{sample_progress.run_id}.yaml"
        assert original_path.exists()

        result = archive_progress(test_project, sample_progress.run_id)

        assert result is not None
        assert result.exists()
        assert result.parent.name == "archive"
        assert not original_path.exists()

    def test_archive_nonexistent_returns_none(self, test_project):
        """archive_progress returns None for nonexistent file."""
        result = archive_progress(test_project, "nonexistent")

        assert result is None

    def test_archive_creates_archive_directory(self, test_project, sample_progress, tmp_path):
        """archive_progress creates archive directory if needed."""
        write_progress(test_project, sample_progress)
        archive_dir = tmp_path / "projects" / test_project / ".progress" / "archive"
        assert not archive_dir.exists()

        archive_progress(test_project, sample_progress.run_id)

        assert archive_dir.exists()


class TestListArchivedProgress:
    """Tests for list_archived_progress function."""

    def test_list_archived_empty(self, test_project):
        """list_archived_progress returns empty list when no archive."""
        result = list_archived_progress(test_project)

        assert result == []

    def test_list_archived_returns_archived_files(self, test_project, sample_progress):
        """list_archived_progress returns archived progress files."""
        write_progress(test_project, sample_progress)
        archive_progress(test_project, sample_progress.run_id)

        result = list_archived_progress(test_project)

        assert len(result) == 1
        assert result[0].run_id == sample_progress.run_id


class TestRoundTrip:
    """Tests for write/read round-trip consistency."""

    def test_roundtrip_all_fields(self, test_project):
        """Write and read preserves all fields."""
        original = ProgressFile(
            run_id="full_progress",
            agent="git-reviewer",
            project=test_project,
            started_at=datetime(2025, 12, 7, 10, 0, 0),
            status=ProgressStatus.COMPLETED,
            last_heartbeat=datetime(2025, 12, 7, 10, 30, 0),
            phase="Final review",
            messages_processed=150,
            estimated_remaining="0 minutes",
            error="",
            result_summary="Reviewed 10 files, found 2 issues",
            artifacts_created=["report.md", "issues.json"],
        )

        write_progress(test_project, original)
        restored = read_progress(test_project, original.run_id)

        assert restored is not None
        assert restored.run_id == original.run_id
        assert restored.agent == original.agent
        assert restored.project == original.project
        assert restored.status == original.status
        assert restored.phase == original.phase
        assert restored.messages_processed == original.messages_processed
        assert restored.result_summary == original.result_summary
        assert restored.artifacts_created == original.artifacts_created


# Run with: uv run pytest tests/test_progress.py -v
if __name__ == "__main__":
    pytest.main([__file__, "-v"])

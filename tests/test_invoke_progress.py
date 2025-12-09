"""
Integration tests for invoke progress tracking.

Tests verify that invoke_agent properly creates and updates progress files
during agent execution lifecycle.

Run with: uv run pytest tests/test_invoke_progress.py -v
"""

import asyncio
import pytest
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch
from dataclasses import dataclass

from pilot_core.progress import (
    ProgressFile,
    ProgressStatus,
    read_progress,
    list_progress,
)


def run_async(coro):
    """Helper to run async code in sync tests."""
    return asyncio.get_event_loop().run_until_complete(coro)


@dataclass
class MockTextBlock:
    """Mock TextBlock from claude_code_sdk."""
    type: str = "text"
    text: str = "Test response"


@dataclass
class MockToolUseBlock:
    """Mock ToolUseBlock from claude_code_sdk."""
    type: str = "tool_use"
    id: str = "tool_123"
    name: str = "Read"
    input: dict = None

    def __post_init__(self):
        if self.input is None:
            self.input = {"file_path": "/test/file.py"}


@dataclass
class MockToolResultBlock:
    """Mock ToolResultBlock from claude_code_sdk."""
    type: str = "tool_result"
    tool_use_id: str = "tool_123"
    content: str = "File content here"


@dataclass
class MockAssistantMessage:
    """Mock AssistantMessage from claude_code_sdk."""
    type: str = "assistant"
    content: list = None

    def __post_init__(self):
        if self.content is None:
            self.content = [MockTextBlock()]


@pytest.fixture
def test_project(tmp_path, monkeypatch):
    """Set up a temporary project directory for testing."""
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()

    # Monkeypatch progress module to use tmp_path
    import pilot_core.progress as progress_module

    def patched_get_progress_dir(project: str) -> Path:
        return tmp_path / "projects" / project / ".progress"

    def patched_get_progress_path(project: str, run_id: str) -> Path:
        return patched_get_progress_dir(project) / f"{run_id}.yaml"

    monkeypatch.setattr(progress_module, "_get_progress_dir", patched_get_progress_dir)
    monkeypatch.setattr(progress_module, "_get_progress_path", patched_get_progress_path)

    return "test-invoke-project"


@pytest.fixture
def mock_agent_config():
    """Mock agent configuration."""
    return {
        "name": "test-agent",
        "description": "Test agent for integration tests",
        "model": "claude-sonnet-4-20250514",
        "system_prompt": "You are a test agent.",
        "tools": ["Read", "Write"],
    }


class TestInvokeProgressIntegration:
    """Integration tests for invoke progress tracking."""

    def test_progress_file_created_at_start(self, test_project, tmp_path, mock_agent_config, monkeypatch):
        """Progress file is created before agent starts processing."""
        # Track when progress was written
        progress_written = []

        original_write = None
        import pilot_core.progress as progress_module
        original_write = progress_module.write_progress

        def track_write_progress(project, progress):
            progress_written.append({
                "project": project,
                "run_id": progress.run_id,
                "status": progress.status,
                "time": datetime.now(),
            })
            return original_write(project, progress)

        monkeypatch.setattr(progress_module, "write_progress", track_write_progress)

        # Also patch invoke module's import
        import pilot_core.invoke as invoke_module
        monkeypatch.setattr(invoke_module, "write_progress", track_write_progress)

        # Mock the agent config loading
        monkeypatch.setattr(invoke_module, "load_agent_config", lambda x: mock_agent_config)

        # Mock SDK query to return simple response
        async def mock_query(*args, **kwargs):
            yield MockAssistantMessage()

        monkeypatch.setattr(invoke_module, "query", mock_query)

        # Run invoke_agent
        from pilot_core.invoke import invoke_agent
        result = run_async(invoke_agent(
            "test-agent",
            "Test prompt",
            project=test_project,
        ))

        # Verify progress was written
        assert len(progress_written) >= 1
        first_write = progress_written[0]
        assert first_write["status"] == ProgressStatus.RUNNING
        assert first_write["project"] == test_project

    def test_progress_marked_completed_on_success(self, test_project, tmp_path, mock_agent_config, monkeypatch):
        """Progress file is marked completed when agent succeeds."""
        import pilot_core.progress as progress_module
        import pilot_core.invoke as invoke_module

        # Patch progress dir
        def patched_get_progress_dir(project: str) -> Path:
            return tmp_path / "projects" / project / ".progress"

        monkeypatch.setattr(progress_module, "_get_progress_dir", patched_get_progress_dir)

        def patched_get_progress_path(project: str, run_id: str) -> Path:
            return patched_get_progress_dir(project) / f"{run_id}.yaml"

        monkeypatch.setattr(progress_module, "_get_progress_path", patched_get_progress_path)

        # Track mark_completed calls
        completed_calls = []
        original_mark = progress_module.mark_completed

        def track_mark_completed(project, run_id, summary, artifacts=None):
            completed_calls.append({
                "project": project,
                "run_id": run_id,
                "summary": summary,
            })
            return original_mark(project, run_id, summary, artifacts)

        monkeypatch.setattr(progress_module, "mark_completed", track_mark_completed)
        monkeypatch.setattr(invoke_module, "mark_completed", track_mark_completed)

        # Mock dependencies
        monkeypatch.setattr(invoke_module, "load_agent_config", lambda x: mock_agent_config)

        async def mock_query(*args, **kwargs):
            yield MockAssistantMessage(content=[MockTextBlock(text="Task completed successfully")])

        monkeypatch.setattr(invoke_module, "query", mock_query)

        # Run invoke_agent
        from pilot_core.invoke import invoke_agent
        result = run_async(invoke_agent(
            "test-agent",
            "Test prompt",
            project=test_project,
        ))

        # Verify completion was called
        assert len(completed_calls) >= 1
        assert completed_calls[0]["project"] == test_project

    def test_progress_marked_failed_on_exception(self, test_project, tmp_path, mock_agent_config, monkeypatch):
        """Progress file is marked failed when agent raises exception."""
        import pilot_core.progress as progress_module
        import pilot_core.invoke as invoke_module

        # Patch progress dir
        def patched_get_progress_dir(project: str) -> Path:
            return tmp_path / "projects" / project / ".progress"

        monkeypatch.setattr(progress_module, "_get_progress_dir", patched_get_progress_dir)

        def patched_get_progress_path(project: str, run_id: str) -> Path:
            return patched_get_progress_dir(project) / f"{run_id}.yaml"

        monkeypatch.setattr(progress_module, "_get_progress_path", patched_get_progress_path)

        # Track mark_failed calls
        failed_calls = []
        original_mark = progress_module.mark_failed

        def track_mark_failed(project, run_id, error):
            failed_calls.append({
                "project": project,
                "run_id": run_id,
                "error": error,
            })
            return original_mark(project, run_id, error)

        monkeypatch.setattr(progress_module, "mark_failed", track_mark_failed)
        monkeypatch.setattr(invoke_module, "mark_failed", track_mark_failed)

        # Mock dependencies
        monkeypatch.setattr(invoke_module, "load_agent_config", lambda x: mock_agent_config)

        async def mock_query_error(*args, **kwargs):
            yield MockAssistantMessage()
            raise RuntimeError("Simulated API error")

        monkeypatch.setattr(invoke_module, "query", mock_query_error)

        # Run invoke_agent - should handle the error
        from pilot_core.invoke import invoke_agent
        try:
            result = run_async(invoke_agent(
                "test-agent",
                "Test prompt",
                project=test_project,
            ))
        except RuntimeError:
            pass  # Expected

        # Verify failure was called
        assert len(failed_calls) >= 1
        assert failed_calls[0]["project"] == test_project
        assert "error" in failed_calls[0]["error"].lower() or "Simulated" in failed_calls[0]["error"]

    def test_heartbeat_function_exists_and_callable(self):
        """Verify update_heartbeat function exists and is callable."""
        from pilot_core.progress import update_heartbeat
        from pilot_core.invoke import update_heartbeat as invoke_heartbeat

        # Both modules should have access to update_heartbeat
        assert callable(update_heartbeat)
        assert callable(invoke_heartbeat)


class TestProgressFileLifecycle:
    """Tests for the complete progress file lifecycle."""

    def test_progress_status_transitions(self):
        """Test that ProgressStatus has all expected transition states."""
        from pilot_core.progress import ProgressStatus

        # Verify all lifecycle states exist
        assert ProgressStatus.PENDING.value == "pending"
        assert ProgressStatus.RUNNING.value == "running"
        assert ProgressStatus.COMPLETED.value == "completed"
        assert ProgressStatus.FAILED.value == "failed"
        assert ProgressStatus.STALLED.value == "stalled"

    def test_progress_functions_imported_in_invoke(self):
        """Verify invoke module has all progress functions imported."""
        import pilot_core.invoke as invoke_module

        # All progress functions should be available in invoke module
        assert hasattr(invoke_module, "write_progress")
        assert hasattr(invoke_module, "update_heartbeat")
        assert hasattr(invoke_module, "mark_completed")
        assert hasattr(invoke_module, "mark_failed")


class TestBackgroundModeProgress:
    """Tests for background mode progress tracking."""

    def test_invoke_agent_supports_background_parameter(self):
        """Verify invoke_agent accepts background parameter."""
        import inspect
        from pilot_core.invoke import invoke_agent

        # Check that invoke_agent has a background parameter
        sig = inspect.signature(invoke_agent)
        params = list(sig.parameters.keys())
        assert "background" in params

    def test_progress_pending_status_for_background_mode(self):
        """PENDING status should be used for background agents."""
        from pilot_core.progress import ProgressStatus

        # PENDING status is used when agent is queued but not yet running
        # This is used in background mode before subprocess starts
        assert ProgressStatus.PENDING.value == "pending"
        assert ProgressStatus.RUNNING.value == "running"


# Run with: uv run pytest tests/test_invoke_progress.py -v
if __name__ == "__main__":
    pytest.main([__file__, "-v"])

"""Progress tracking module for non-blocking agent invocation.

This module provides filesystem-based progress tracking for agent invocations.
Every agent invocation writes progress to .progress/{run_id}.yaml during execution.
Pilot can check these files to monitor progress without blocking.

Progress file location: projects/{project}/.progress/{run_id}.yaml
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Optional
import yaml


class ProgressStatus(Enum):
    """Status of an agent invocation."""
    PENDING = 'pending'
    RUNNING = 'running'
    COMPLETED = 'completed'
    FAILED = 'failed'
    STALLED = 'stalled'


@dataclass
class ProgressFile:
    """Progress tracking data for an agent invocation.

    Attributes:
        run_id: Unique identifier for this invocation
        agent: Agent name (e.g., 'git-reviewer', 'builder')
        project: Project name
        started_at: When the invocation started
        status: Current status of the invocation
        last_heartbeat: Last time the agent updated progress
        phase: Human-readable current activity
        messages_processed: Count of messages streamed
        estimated_remaining: Optional time estimate string
        error: Error message if failed
        result_summary: Brief summary when completed
        artifacts_created: Files created during execution
    """
    run_id: str
    agent: str
    project: str
    started_at: datetime
    status: ProgressStatus
    last_heartbeat: datetime
    phase: str = ''
    messages_processed: int = 0
    estimated_remaining: str = ''
    error: str = ''
    result_summary: str = ''
    artifacts_created: list[str] = field(default_factory=list)


def _get_progress_dir(project: str) -> Path:
    """Get the .progress directory path for a project."""
    return Path('projects') / project / '.progress'


def _get_progress_path(project: str, run_id: str) -> Path:
    """Get the progress file path for a specific run."""
    return _get_progress_dir(project) / f'{run_id}.yaml'


def _progress_to_dict(progress: ProgressFile) -> dict:
    """Convert ProgressFile to a dictionary for YAML serialization."""
    return {
        'run_id': progress.run_id,
        'agent': progress.agent,
        'project': progress.project,
        'started_at': progress.started_at.isoformat(),
        'status': progress.status.value,
        'last_heartbeat': progress.last_heartbeat.isoformat(),
        'phase': progress.phase,
        'messages_processed': progress.messages_processed,
        'estimated_remaining': progress.estimated_remaining,
        'error': progress.error,
        'result_summary': progress.result_summary,
        'artifacts_created': progress.artifacts_created,
    }


def _dict_to_progress(data: dict) -> ProgressFile:
    """Convert a dictionary from YAML to ProgressFile."""
    return ProgressFile(
        run_id=data['run_id'],
        agent=data['agent'],
        project=data['project'],
        started_at=datetime.fromisoformat(data['started_at']),
        status=ProgressStatus(data['status']),
        last_heartbeat=datetime.fromisoformat(data['last_heartbeat']),
        phase=data.get('phase', ''),
        messages_processed=data.get('messages_processed', 0),
        estimated_remaining=data.get('estimated_remaining', ''),
        error=data.get('error', ''),
        result_summary=data.get('result_summary', ''),
        artifacts_created=data.get('artifacts_created', []),
    )


def write_progress(project: str, progress: ProgressFile) -> Path:
    """Write progress file to projects/{project}/.progress/{run_id}.yaml.

    Creates .progress/ directory if it doesn't exist.

    Args:
        project: Project name
        progress: ProgressFile to write

    Returns:
        Path to the written file
    """
    progress_dir = _get_progress_dir(project)
    progress_dir.mkdir(parents=True, exist_ok=True)

    path = _get_progress_path(project, progress.run_id)

    data = _progress_to_dict(progress)
    with open(path, 'w') as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)

    return path


def read_progress(project: str, run_id: str) -> Optional[ProgressFile]:
    """Read progress file for a specific run.

    Args:
        project: Project name
        run_id: Run identifier

    Returns:
        ProgressFile if found, None if file doesn't exist
    """
    path = _get_progress_path(project, run_id)

    if not path.exists():
        return None

    try:
        with open(path, 'r') as f:
            data = yaml.safe_load(f)
        return _dict_to_progress(data)
    except (yaml.YAMLError, KeyError, ValueError):
        # Return None for invalid/corrupted files
        return None


def list_progress(project: str) -> list[ProgressFile]:
    """List all progress files for a project.

    Args:
        project: Project name

    Returns:
        List of ProgressFile objects, empty list if .progress/ doesn't exist
    """
    progress_dir = _get_progress_dir(project)

    if not progress_dir.exists():
        return []

    progress_files = []
    for path in progress_dir.glob('*.yaml'):
        try:
            with open(path, 'r') as f:
                data = yaml.safe_load(f)
            progress_files.append(_dict_to_progress(data))
        except (yaml.YAMLError, KeyError, ValueError):
            # Skip invalid/corrupted files
            continue

    return progress_files


def update_progress(project: str, run_id: str, **updates) -> Optional[ProgressFile]:
    """Update specific fields in an existing progress file.

    Reads the existing progress, merges updates, and writes back.
    All updates preserve existing fields not being updated.

    Args:
        project: Project name
        run_id: Run identifier
        **updates: Fields to update (e.g., phase='Reading files', messages_processed=10)

    Returns:
        Updated ProgressFile, or None if original file doesn't exist
    """
    progress = read_progress(project, run_id)
    if progress is None:
        return None

    # Handle status as string or ProgressStatus
    if 'status' in updates:
        status_val = updates['status']
        if isinstance(status_val, str):
            updates['status'] = ProgressStatus(status_val)

    # Apply updates to a dict representation
    data = _progress_to_dict(progress)
    for key, value in updates.items():
        if key == 'status' and isinstance(value, ProgressStatus):
            data[key] = value.value
        elif key in ('started_at', 'last_heartbeat') and isinstance(value, datetime):
            data[key] = value.isoformat()
        else:
            data[key] = value

    # Convert back and write
    updated = _dict_to_progress(data)
    write_progress(project, updated)
    return updated


def update_heartbeat(
    project: str,
    run_id: str,
    phase: Optional[str] = None,
    messages: Optional[int] = None
) -> Optional[ProgressFile]:
    """Quick heartbeat update - updates last_heartbeat and optionally phase/messages.

    Args:
        project: Project name
        run_id: Run identifier
        phase: Optional new phase string
        messages: Optional new message count

    Returns:
        Updated ProgressFile, or None if original file doesn't exist
    """
    updates: dict = {'last_heartbeat': datetime.now().isoformat()}

    if phase is not None:
        updates['phase'] = phase
    if messages is not None:
        updates['messages_processed'] = messages

    return update_progress(project, run_id, **updates)


def mark_completed(
    project: str,
    run_id: str,
    result_summary: str,
    artifacts: Optional[list[str]] = None
) -> Optional[ProgressFile]:
    """Mark an agent invocation as completed.

    Args:
        project: Project name
        run_id: Run identifier
        result_summary: Brief summary of what was accomplished
        artifacts: Optional list of files created during execution

    Returns:
        Updated ProgressFile, or None if original file doesn't exist
    """
    updates: dict = {
        'status': ProgressStatus.COMPLETED.value,
        'last_heartbeat': datetime.now().isoformat(),
        'result_summary': result_summary,
    }

    if artifacts is not None:
        updates['artifacts_created'] = artifacts

    return update_progress(project, run_id, **updates)


def mark_failed(project: str, run_id: str, error: str) -> Optional[ProgressFile]:
    """Mark an agent invocation as failed.

    Args:
        project: Project name
        run_id: Run identifier
        error: Error message describing the failure

    Returns:
        Updated ProgressFile, or None if original file doesn't exist
    """
    return update_progress(
        project,
        run_id,
        status=ProgressStatus.FAILED.value,
        last_heartbeat=datetime.now().isoformat(),
        error=error
    )


def is_stale(progress: ProgressFile, threshold_minutes: int = 5) -> bool:
    """Check if a progress file is stale (no heartbeat within threshold).

    Args:
        progress: ProgressFile to check
        threshold_minutes: Minutes without heartbeat to consider stale (default 5)

    Returns:
        True if last_heartbeat is older than threshold_minutes ago
    """
    now = datetime.now()
    elapsed = now - progress.last_heartbeat
    return elapsed.total_seconds() > (threshold_minutes * 60)


class StaleAgentError(Exception):
    """Raised when an agent appears to be stuck (no recent heartbeat)."""
    pass


class AgentNotFoundError(Exception):
    """Raised when a progress file cannot be found for an agent."""
    pass


def wait_for_agent(
    project: str,
    run_id: str,
    timeout: int = 600,
    poll_interval: int = 5,
    stale_threshold: int = 5,
) -> ProgressFile:
    """Wait for a background agent to complete.

    Polls the progress file until the agent completes, fails, or times out.
    Detects stale agents that have stopped updating their heartbeat.

    Args:
        project: Project name
        run_id: Run identifier
        timeout: Maximum seconds to wait (default 600 = 10 minutes)
        poll_interval: Seconds between polls (default 5)
        stale_threshold: Minutes without heartbeat to consider stale (default 5)

    Returns:
        Final ProgressFile when agent completes or fails

    Raises:
        TimeoutError: If timeout exceeded before completion
        StaleAgentError: If agent appears stuck (no heartbeat updates)
        AgentNotFoundError: If progress file doesn't exist
    """
    import time

    start_time = time.time()
    terminal_statuses = {ProgressStatus.COMPLETED, ProgressStatus.FAILED}

    while True:
        elapsed = time.time() - start_time

        # Read progress
        progress = read_progress(project, run_id)
        if progress is None:
            # Give some grace period for file creation
            if elapsed < poll_interval * 2:
                time.sleep(poll_interval)
                continue
            raise AgentNotFoundError(f"Progress file not found for run_id: {run_id}")

        # Check timeout (only after we've confirmed file exists)
        if elapsed > timeout:
            raise TimeoutError(
                f"Agent {run_id} did not complete within {timeout}s. "
                f"Last status: {progress.status.value if progress else 'unknown'}"
            )

        # Check if completed or failed
        if progress.status in terminal_statuses:
            return progress

        # Check for stale agent
        if is_stale(progress, stale_threshold):
            raise StaleAgentError(
                f"Agent {run_id} appears stuck. No heartbeat in {stale_threshold} minutes. "
                f"Last phase: {progress.phase}"
            )

        # Wait before next poll
        time.sleep(poll_interval)


def cleanup_progress(
    project: str,
    max_age_hours: int = 24,
    keep_failed: bool = True,
) -> dict:
    """Clean up old progress files for a project.

    Deletes completed progress files older than max_age_hours.
    Optionally keeps failed progress for debugging.

    Args:
        project: Project name
        max_age_hours: Delete completed files older than this (default 24)
        keep_failed: If True, don't delete failed progress (default True)

    Returns:
        Dict with cleanup statistics:
            - deleted_count: Number of files deleted
            - deleted_run_ids: List of deleted run IDs
            - kept_count: Number of files kept
            - kept_failed: Number of failed files preserved
    """
    import shutil

    progress_dir = _get_progress_dir(project)
    if not progress_dir.exists():
        return {
            'deleted_count': 0,
            'deleted_run_ids': [],
            'kept_count': 0,
            'kept_failed': 0,
        }

    now = datetime.now()
    cutoff = now - timedelta(hours=max_age_hours)

    deleted_count = 0
    deleted_run_ids = []
    kept_count = 0
    kept_failed = 0

    for path in progress_dir.glob('*.yaml'):
        # Skip archive directory
        if path.parent.name == 'archive':
            continue

        progress = read_progress(project, path.stem)
        if progress is None:
            # Corrupted file - delete it
            path.unlink()
            deleted_count += 1
            deleted_run_ids.append(path.stem)
            continue

        # Check if file is old enough to consider for deletion
        is_old = progress.last_heartbeat < cutoff

        # Keep failed files if requested
        if progress.status == ProgressStatus.FAILED and keep_failed:
            kept_count += 1
            kept_failed += 1
            continue

        # Only delete completed files that are old enough
        if progress.status == ProgressStatus.COMPLETED and is_old:
            path.unlink()
            deleted_count += 1
            deleted_run_ids.append(progress.run_id)
        else:
            kept_count += 1

    return {
        'deleted_count': deleted_count,
        'deleted_run_ids': deleted_run_ids,
        'kept_count': kept_count,
        'kept_failed': kept_failed,
    }


def archive_progress(project: str, run_id: str) -> Optional[Path]:
    """Archive a progress file instead of deleting it.

    Moves progress file to .progress/archive/ subdirectory.
    Useful for preserving records while cleaning up.

    Args:
        project: Project name
        run_id: Run identifier to archive

    Returns:
        Path to archived file, or None if original file doesn't exist
    """
    progress_dir = _get_progress_dir(project)
    source_path = _get_progress_path(project, run_id)

    if not source_path.exists():
        return None

    # Create archive directory
    archive_dir = progress_dir / 'archive'
    archive_dir.mkdir(parents=True, exist_ok=True)

    # Move file to archive
    dest_path = archive_dir / f'{run_id}.yaml'
    source_path.rename(dest_path)

    return dest_path


def list_archived_progress(project: str) -> list[ProgressFile]:
    """List all archived progress files for a project.

    Args:
        project: Project name

    Returns:
        List of ProgressFile objects from archive, empty if no archive exists
    """
    archive_dir = _get_progress_dir(project) / 'archive'

    if not archive_dir.exists():
        return []

    progress_files = []
    for path in archive_dir.glob('*.yaml'):
        try:
            with open(path, 'r') as f:
                data = yaml.safe_load(f)
            progress_files.append(_dict_to_progress(data))
        except (yaml.YAMLError, KeyError, ValueError):
            # Skip invalid/corrupted files
            continue

    return progress_files

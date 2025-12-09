"""Agent status checking tool for batch status queries.

This tool allows checking status of multiple agents efficiently in one call.
Critical for token efficiency when monitoring background agents.

Usage:
    uv run python -m tools agent_status '{"project": "my-project"}'
    uv run python -m tools agent_status '{"run_ids": ["abc123", "def456"]}'
    uv run python -m tools agent_status '{"project": "my-project", "include_completed": true}'
"""

from pilot_core.progress import (
    ProgressFile,
    ProgressStatus,
    read_progress,
    list_progress,
    is_stale,
)


def _progress_to_summary(progress: ProgressFile) -> dict:
    """Convert ProgressFile to a concise summary dict."""
    summary = {
        'status': progress.status.value,
        'agent': progress.agent,
        'project': progress.project,
        'phase': progress.phase,
        'last_heartbeat': progress.last_heartbeat.isoformat(),
        'is_stale': is_stale(progress),
        'messages_processed': progress.messages_processed,
    }

    # Include extra fields for completed/failed status
    if progress.status == ProgressStatus.COMPLETED:
        summary['result_summary'] = progress.result_summary
        if progress.artifacts_created:
            summary['artifacts_created'] = progress.artifacts_created

    if progress.status == ProgressStatus.FAILED:
        summary['error'] = progress.error

    return summary


def agent_status(
    run_ids: list[str] | None = None,
    project: str | None = None,
    include_completed: bool = False,
    list_all: bool = False,
) -> dict:
    """Check status of multiple agents efficiently in one call.

    Args:
        run_ids: List of specific run IDs to check (requires project to be set)
        project: Project name to check. Required if run_ids is set,
                 or used to list all progress files for that project.
        include_completed: If True, include completed status in results.
                          Default False to focus on active agents.
        list_all: If True, scan all projects for active agents.

    Returns:
        Dict mapping run_id to progress summary (or grouped by project if list_all=True):
        {
            'run_abc123': {
                'status': 'running',
                'agent': 'git-reviewer',
                'phase': 'Reviewing lib/invoke.py',
                'last_heartbeat': '2025-12-07T10:05:32Z',
                'is_stale': false,
                'messages_processed': 42
            },
            ...
        }
    """
    # Handle list_all mode first
    if list_all:
        return list_all_active(include_completed)

    result: dict[str, dict] = {}

    # If specific run_ids provided, look them up
    if run_ids is not None:
        if project is None:
            return {'error': 'project parameter required when using run_ids'}

        for run_id in run_ids:
            progress = read_progress(project, run_id)
            if progress is None:
                result[run_id] = {'status': 'not_found'}
            elif not include_completed and progress.status == ProgressStatus.COMPLETED:
                continue  # Skip completed unless explicitly requested
            else:
                result[run_id] = _progress_to_summary(progress)

        return result

    # If project provided, list all progress files
    if project is not None:
        all_progress = list_progress(project)

        for progress in all_progress:
            if not include_completed and progress.status == ProgressStatus.COMPLETED:
                continue
            result[progress.run_id] = _progress_to_summary(progress)

        return result

    # No parameters - return error with usage
    return {
        'error': 'Either project or run_ids parameter required',
        'usage': {
            'project': 'Check all progress files for a project',
            'run_ids': 'Check specific run IDs (requires project)',
            'include_completed': 'Include completed status (default: false)',
            'list_all': 'Use list_all=true to see all projects',
        }
    }


def list_all_active(include_completed: bool = False) -> dict:
    """List all active agents across all projects.

    Scans all projects/.progress/ directories and returns a summary
    of all running/pending agents grouped by project.

    Args:
        include_completed: If True, include completed agents in results.

    Returns:
        Dict grouped by project:
        {
            'projects': {
                'my-project': {
                    'run_abc123': {...},
                    'run_def456': {...}
                },
                'other-project': {...}
            },
            'summary': {
                'total_active': 5,
                'stale_count': 1,
                'projects_with_agents': ['my-project', 'other-project']
            }
        }
    """
    from pathlib import Path

    projects_dir = Path('projects')
    if not projects_dir.exists():
        return {
            'projects': {},
            'summary': {
                'total_active': 0,
                'stale_count': 0,
                'projects_with_agents': []
            }
        }

    result: dict[str, dict] = {}
    total_active = 0
    stale_count = 0
    projects_with_agents = []

    # Scan all project directories
    for project_dir in projects_dir.iterdir():
        if not project_dir.is_dir():
            continue

        progress_dir = project_dir / '.progress'
        if not progress_dir.exists():
            continue

        project_name = project_dir.name
        all_progress = list_progress(project_name)

        project_agents = {}
        for progress in all_progress:
            if not include_completed and progress.status == ProgressStatus.COMPLETED:
                continue

            summary = _progress_to_summary(progress)
            project_agents[progress.run_id] = summary
            total_active += 1

            if summary.get('is_stale'):
                stale_count += 1

        if project_agents:
            result[project_name] = project_agents
            projects_with_agents.append(project_name)

    return {
        'projects': result,
        'summary': {
            'total_active': total_active,
            'stale_count': stale_count,
            'projects_with_agents': projects_with_agents
        }
    }

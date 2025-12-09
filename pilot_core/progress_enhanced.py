"""Enhanced progress tracking with adaptive polling based on historical data.

This module extends lib.progress with smarter polling strategies that:
1. Use historical agent latencies to set expectations
2. Implement exponential backoff for polling intervals
3. Provide better progress reporting
"""

import time
import yaml
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, Dict, Any

from pilot_core.progress import (
    ProgressFile,
    ProgressStatus,
    read_progress,
    update_heartbeat,
    is_stale,
    StaleAgentError,
    AgentNotFoundError,
)


def load_polling_config() -> Dict[str, Any]:
    """Load agent polling configuration with historical latency data."""
    config_path = Path("system/agent_polling_config.yaml")
    if not config_path.exists():
        # Default config if historical data not available
        return {
            "_default": {
                "initial_poll_interval": 10,
                "backoff_multiplier": 1.5,
                "max_poll_interval": 60,
                "expected_median_sec": 120,
                "expected_95_percentile_sec": 600,
                "stale_threshold_min": 10,
            }
        }

    with open(config_path) as f:
        return yaml.safe_load(f)


def wait_for_agent_adaptive(
    project: str,
    run_id: str,
    agent_name: Optional[str] = None,
    timeout: Optional[int] = None,
    verbose: bool = True,
) -> ProgressFile:
    """Wait for a background agent with adaptive polling based on historical data.

    This enhanced version:
    - Uses historical latency data to set realistic expectations
    - Implements exponential backoff for polling intervals
    - Provides better progress feedback
    - Adjusts timeout based on historical 95th percentile

    Args:
        project: Project name
        run_id: Run identifier
        agent_name: Optional agent name for better config lookup
        timeout: Optional timeout override (defaults to 2x historical 95th percentile)
        verbose: If True, print progress updates

    Returns:
        Final ProgressFile when agent completes or fails

    Raises:
        TimeoutError: If timeout exceeded before completion
        StaleAgentError: If agent appears stuck (no heartbeat updates)
        AgentNotFoundError: If progress file doesn't exist
    """
    start_time = time.time()
    terminal_statuses = {ProgressStatus.COMPLETED, ProgressStatus.FAILED}

    # Load polling config
    config = load_polling_config()

    # Get agent-specific config or use defaults
    if agent_name and agent_name in config:
        agent_config = config[agent_name]
    else:
        agent_config = config.get("_default", {
            "initial_poll_interval": 10,
            "backoff_multiplier": 1.5,
            "max_poll_interval": 60,
            "expected_median_sec": 120,
            "expected_95_percentile_sec": 600,
            "stale_threshold_min": 10,
        })

    # Set timeout based on historical data if not provided
    if timeout is None:
        # Use 2x the 95th percentile as timeout
        timeout = agent_config["expected_95_percentile_sec"] * 2

    # Extract config values
    poll_interval = agent_config["initial_poll_interval"]
    backoff_multiplier = agent_config["backoff_multiplier"]
    max_poll_interval = agent_config["max_poll_interval"]
    expected_median = agent_config["expected_median_sec"]
    expected_95 = agent_config["expected_95_percentile_sec"]
    stale_threshold = agent_config["stale_threshold_min"]

    if verbose:
        print(f"⏳ Waiting for {agent_name or 'agent'} ({run_id})")
        print(f"   Expected completion: {expected_median}s (typical), {expected_95}s (95%)")
        print(f"   Timeout: {timeout}s, Initial poll: {poll_interval}s")
        print()

    last_phase = ""
    last_message_count = 0
    poll_count = 0

    while True:
        elapsed = time.time() - start_time
        poll_count += 1

        # Read progress
        progress = read_progress(project, run_id)

        if progress is None:
            # Give grace period for file creation (2 poll intervals)
            if elapsed < poll_interval * 2:
                if verbose and poll_count == 1:
                    print(f"   ⏳ Waiting for progress file creation...")
                time.sleep(poll_interval)
                continue
            raise AgentNotFoundError(f"Progress file not found for run_id: {run_id}")

        # Check timeout
        if elapsed > timeout:
            raise TimeoutError(
                f"Agent {run_id} did not complete within {timeout}s. "
                f"Last status: {progress.status.value}, phase: {progress.phase}"
            )

        # Check if completed or failed
        if progress.status in terminal_statuses:
            if verbose:
                if progress.status == ProgressStatus.COMPLETED:
                    print(f"✅ Completed in {elapsed:.1f}s: {progress.result_summary}")
                else:
                    print(f"❌ Failed in {elapsed:.1f}s: {progress.error}")
            return progress

        # Check for stale agent
        if is_stale(progress, stale_threshold):
            raise StaleAgentError(
                f"Agent {run_id} appears stuck. No heartbeat in {stale_threshold} minutes. "
                f"Last phase: {progress.phase}"
            )

        # Print progress updates if phase or message count changed
        if verbose:
            phase_changed = progress.phase != last_phase
            messages_changed = progress.messages_processed > last_message_count

            if phase_changed or messages_changed:
                # Calculate progress percentage based on historical data
                progress_pct = min(100, (elapsed / expected_median) * 100)

                status_line = f"   [{elapsed:.0f}s] "

                if phase_changed and progress.phase:
                    status_line += f"📍 {progress.phase}"

                if messages_changed:
                    if phase_changed:
                        status_line += f" | "
                    status_line += f"📝 {progress.messages_processed} messages"

                # Add progress estimate
                status_line += f" (~{progress_pct:.0f}% based on typical duration)"

                print(status_line)

                last_phase = progress.phase
                last_message_count = progress.messages_processed

        # Adaptive polling interval with exponential backoff
        if elapsed < 30:
            # First 30 seconds: use initial interval
            current_interval = poll_interval
        elif elapsed < 120:
            # 30s-2m: gradually increase interval
            current_interval = min(max_poll_interval, poll_interval * backoff_multiplier)
            poll_interval = current_interval  # Update for next iteration
        else:
            # After 2m: use max interval
            current_interval = max_poll_interval

        # If we're past expected median time, poll more frequently again
        if elapsed > expected_median:
            current_interval = min(current_interval, 10)

        time.sleep(current_interval)


def auto_track_progress(func):
    """Decorator to automatically track progress for long-running functions.

    Usage:
        @auto_track_progress
        async def my_long_task(project: str, run_id: str, **kwargs):
            # Your code here
            # Progress will be automatically initialized and updated

    The decorated function must accept 'project' and 'run_id' parameters.
    """
    import functools
    import asyncio
    from pilot_core.progress import (
        ProgressFile,
        ProgressStatus,
        write_progress,
        mark_completed,
        mark_failed,
    )

    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        # Extract project and run_id from kwargs
        project = kwargs.get('project')
        run_id = kwargs.get('run_id')

        if not project or not run_id:
            # Can't track without these parameters
            return await func(*args, **kwargs)

        # Initialize progress
        agent_name = kwargs.get('agent_name', func.__name__)
        initial_progress = ProgressFile(
            run_id=run_id,
            agent=agent_name,
            project=project,
            started_at=datetime.now(),
            status=ProgressStatus.RUNNING,
            last_heartbeat=datetime.now(),
            phase=f'Starting {func.__name__}',
            messages_processed=0,
        )
        write_progress(project, initial_progress)

        try:
            # Run the actual function
            result = await func(*args, **kwargs)

            # Mark as completed
            mark_completed(
                project,
                run_id,
                result_summary=f"{func.__name__} completed successfully",
                artifacts=None,
            )

            return result

        except Exception as e:
            # Mark as failed
            mark_failed(project, run_id, str(e))
            raise

    return wrapper


def create_progress_context(project: str, agent_name: str):
    """Create a context manager for automatic progress tracking.

    Usage:
        with create_progress_context("my-project", "my-agent") as progress:
            # Your code here
            progress.update_phase("Processing files")
            # More code
            progress.add_artifact("output.txt")

    The context manager handles initialization, updates, and completion.
    """
    import uuid

    class ProgressContext:
        def __init__(self, project: str, agent_name: str):
            self.project = project
            self.agent_name = agent_name
            self.run_id = f"run_{uuid.uuid4().hex[:12]}"
            self.artifacts = []
            self.start_time = None

        def __enter__(self):
            from pilot_core.progress import ProgressFile, ProgressStatus, write_progress

            self.start_time = datetime.now()
            initial = ProgressFile(
                run_id=self.run_id,
                agent=self.agent_name,
                project=self.project,
                started_at=self.start_time,
                status=ProgressStatus.RUNNING,
                last_heartbeat=self.start_time,
                phase='Initializing',
                messages_processed=0,
            )
            write_progress(self.project, initial)
            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            from pilot_core.progress import mark_completed, mark_failed

            if exc_type is None:
                # Success
                mark_completed(
                    self.project,
                    self.run_id,
                    result_summary="Task completed",
                    artifacts=self.artifacts or None,
                )
            else:
                # Failure
                mark_failed(
                    self.project,
                    self.run_id,
                    error=f"{exc_type.__name__}: {exc_val}",
                )

        def update_phase(self, phase: str, messages: Optional[int] = None):
            """Update the current phase and optionally message count."""
            update_heartbeat(self.project, self.run_id, phase, messages)

        def add_artifact(self, file_path: str):
            """Track an artifact created during execution."""
            self.artifacts.append(file_path)

    return ProgressContext(project, agent_name)


# Export enhanced functions
__all__ = [
    'wait_for_agent_adaptive',
    'auto_track_progress',
    'create_progress_context',
    'load_polling_config',
]
"""
Enforcement telemetry - event recording API for tracking enforcement actions.

Records enforcement events from guards.py, violation_watcher.py, and precommit.py
to a JSON Lines file for analysis and monitoring.

Usage:
    from pilot_core.telemetry import record_event, EventType, get_event_counts

    # Record an enforcement event
    record_event(EventType.IMPORT_BLOCKED, "guards.py", {"module": "requests"})

    # Get event statistics
    counts = get_event_counts(since_days=7)
"""

import fcntl
import json
import os
import threading
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Optional

# Default storage path
DEFAULT_EVENTS_FILE = "data/enforcement_events.jsonl"

# Thread lock for safe concurrent access
_write_lock = threading.Lock()


class EventType(str, Enum):
    """Enforcement event types."""

    # Import guards (guards.py)
    IMPORT_BLOCKED = "import_blocked"
    IMPORT_ALLOWED = "import_allowed"

    # Violation watcher (violation_watcher.py)
    VIOLATION_DETECTED = "violation_detected"

    # Pre-commit hook (precommit.py)
    COMMIT_REVIEW_REQUIRED = "commit_review_required"
    COMMIT_REVIEW_BYPASSED = "commit_review_bypassed"
    COMMIT_GITIGNORE_ONLY = "commit_gitignore_only"

    # Bypass events (git hooks)
    BYPASS_REVIEW = "bypass_review"
    BYPASS_AGENT_TRAILER = "bypass_agent_trailer"

    # Commit metadata (post-commit hook)
    COMMIT_COMPLETED = "commit_completed"


def _get_events_path(events_file: Optional[str] = None) -> Path:
    """Get the path to the events file, creating parent directories if needed."""
    path = Path(events_file or DEFAULT_EVENTS_FILE)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def record_event(
    event_type: EventType,
    source: str,
    details: Optional[dict] = None,
    events_file: Optional[str] = None,
) -> dict:
    """
    Record an enforcement event.

    Thread-safe and uses atomic file operations to prevent corruption.

    Args:
        event_type: Type of enforcement event (from EventType enum)
        source: Source module/file that generated the event (e.g., 'guards.py')
        details: Optional dict with additional event details
        events_file: Optional path to events file (default: data/enforcement_events.jsonl)

    Returns:
        The recorded event dict (for testing/verification)

    Example:
        >>> record_event(EventType.IMPORT_BLOCKED, "guards.py", {"module": "requests"})
        {'timestamp': '2025-01-15T10:30:00.123456', 'event_type': 'import_blocked', ...}
    """
    event = {
        "timestamp": datetime.now().isoformat(),
        "event_type": event_type.value if isinstance(event_type, EventType) else event_type,
        "source": source,
    }
    if details:
        event["details"] = details

    events_path = _get_events_path(events_file)

    # Thread-safe write with file locking
    with _write_lock:
        # Open file for append, create if doesn't exist
        fd = os.open(
            str(events_path),
            os.O_WRONLY | os.O_CREAT | os.O_APPEND,
            0o644,
        )
        try:
            # Acquire exclusive lock for atomic append
            fcntl.flock(fd, fcntl.LOCK_EX)
            try:
                # Write event as single JSON line
                line = json.dumps(event) + "\n"
                os.write(fd, line.encode("utf-8"))
            finally:
                fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)

    return event


def cleanup_old_events(
    days: int = 30,
    events_file: Optional[str] = None,
) -> int:
    """
    Remove events older than the specified number of days.

    This is a separate function from record_event to avoid expensive cleanup
    on every event recording. Call this periodically (e.g., daily via cron).

    Args:
        days: Number of days to retain (default: 30)
        events_file: Optional path to events file

    Returns:
        Number of events removed

    Example:
        >>> removed = cleanup_old_events(days=30)
        >>> print(f"Removed {removed} old events")
    """
    events_path = _get_events_path(events_file)

    if not events_path.exists():
        return 0

    cutoff = datetime.now() - timedelta(days=days)
    kept_events = []
    removed_count = 0

    # Read all events and filter
    with _write_lock:
        # Acquire exclusive lock for read-modify-write
        fd = os.open(str(events_path), os.O_RDWR)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            try:
                # Read existing content
                with open(events_path, "r") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            event = json.loads(line)
                            event_time = datetime.fromisoformat(event.get("timestamp", ""))
                            if event_time >= cutoff:
                                kept_events.append(event)
                            else:
                                removed_count += 1
                        except (json.JSONDecodeError, ValueError):
                            # Keep malformed lines (don't lose data)
                            kept_events.append({"_raw": line})

                # Write back kept events (truncate and rewrite)
                with open(events_path, "w") as f:
                    for event in kept_events:
                        if "_raw" in event:
                            f.write(event["_raw"] + "\n")
                        else:
                            f.write(json.dumps(event) + "\n")
            finally:
                fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)

    return removed_count


def get_event_counts(
    since_days: int = 7,
    events_file: Optional[str] = None,
) -> dict[str, int]:
    """
    Get counts of events by type within the specified time window.

    Args:
        since_days: Number of days to look back (default: 7)
        events_file: Optional path to events file

    Returns:
        Dict mapping event_type to count

    Example:
        >>> counts = get_event_counts(since_days=7)
        >>> print(counts)
        {'import_blocked': 5, 'violation_detected': 2, ...}
    """
    events_path = _get_events_path(events_file)

    if not events_path.exists():
        return {}

    cutoff = datetime.now() - timedelta(days=since_days)
    counts: dict[str, int] = {}

    try:
        with open(events_path, "r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                    event_time = datetime.fromisoformat(event.get("timestamp", ""))
                    if event_time >= cutoff:
                        event_type = event.get("event_type", "unknown")
                        counts[event_type] = counts.get(event_type, 0) + 1
                except (json.JSONDecodeError, ValueError):
                    # Skip malformed lines for stats
                    pass
    except IOError:
        return {}

    return counts


def get_events(
    since_days: Optional[int] = None,
    event_type: Optional[EventType] = None,
    events_file: Optional[str] = None,
) -> list[dict]:
    """
    Retrieve events with optional filtering.

    Args:
        since_days: Optional number of days to look back (None = all events)
        event_type: Optional filter by event type
        events_file: Optional path to events file

    Returns:
        List of event dicts matching the filters

    Example:
        >>> events = get_events(since_days=1, event_type=EventType.IMPORT_BLOCKED)
    """
    events_path = _get_events_path(events_file)

    if not events_path.exists():
        return []

    cutoff = None
    if since_days is not None:
        cutoff = datetime.now() - timedelta(days=since_days)

    type_filter = None
    if event_type is not None:
        type_filter = event_type.value if isinstance(event_type, EventType) else event_type

    results = []
    try:
        with open(events_path, "r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)

                    # Apply time filter
                    if cutoff:
                        event_time = datetime.fromisoformat(event.get("timestamp", ""))
                        if event_time < cutoff:
                            continue

                    # Apply type filter
                    if type_filter and event.get("event_type") != type_filter:
                        continue

                    results.append(event)
                except (json.JSONDecodeError, ValueError):
                    pass
    except IOError:
        return []

    return results


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Enforcement telemetry utilities")
    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # stats command
    stats_parser = subparsers.add_parser("stats", help="Show event statistics")
    stats_parser.add_argument(
        "--days", type=int, default=7, help="Days to look back (default: 7)"
    )

    # cleanup command
    cleanup_parser = subparsers.add_parser("cleanup", help="Remove old events")
    cleanup_parser.add_argument(
        "--days", type=int, default=30, help="Days to retain (default: 30)"
    )

    # test command
    test_parser = subparsers.add_parser("test", help="Record a test event")

    args = parser.parse_args()

    if args.command == "stats":
        counts = get_event_counts(since_days=args.days)
        if counts:
            print(f"Event counts (last {args.days} days):")
            for event_type, count in sorted(counts.items()):
                print(f"  {event_type}: {count}")
        else:
            print("No events recorded")

    elif args.command == "cleanup":
        removed = cleanup_old_events(days=args.days)
        print(f"Removed {removed} events older than {args.days} days")

    elif args.command == "test":
        event = record_event(
            EventType.IMPORT_BLOCKED,
            "telemetry.py",
            {"module": "test", "reason": "CLI test"},
        )
        print(f"Recorded test event: {json.dumps(event, indent=2)}")

    else:
        parser.print_help()

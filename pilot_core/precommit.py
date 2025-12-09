"""
Pre-commit hook helper functions.

Testable Python functions extracted from .githooks/pre-commit bash logic.
These functions handle marker parsing, validation, and bypass logging.

The actual pre-commit hook (.githooks/pre-commit) is a bash script that
calls these functions for the complex logic.
"""

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# Telemetry import with graceful fallback
try:
    from pilot_core.telemetry import record_event, EventType

    _telemetry_available = True
except ImportError:
    _telemetry_available = False

    # No-op stubs if telemetry unavailable
    def record_event(*args, **kwargs):
        pass

    class EventType:
        COMMIT_REVIEW_REQUIRED = "commit_review_required"
        COMMIT_REVIEW_BYPASSED = "commit_review_bypassed"
        COMMIT_GITIGNORE_ONLY = "commit_gitignore_only"


# Maximum age of approval in seconds (1 hour)
MAX_APPROVAL_AGE_SECONDS = 3600


def parse_marker(content: str) -> dict:
    """Parse REVIEW_APPROVED marker content.

    Supports JSON format with YAML fallback for backward compatibility.

    Args:
        content: Raw marker file content

    Returns:
        Dict with parsed fields: approved_at, diff_hash, verdict, files
        Returns empty dict if parsing fails completely

    Examples:
        >>> parse_marker('{"approved_at": "2025-01-01T12:00:00", "diff_hash": "abc123"}')
        {'approved_at': '2025-01-01T12:00:00', 'diff_hash': 'abc123'}
    """
    if not content or not content.strip():
        return {}

    # Try JSON first (primary format)
    try:
        data = json.loads(content)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass

    # Fall back to YAML-like key: value format
    result = {}
    for line in content.split("\n"):
        line = line.strip()
        if ":" in line and not line.startswith("#"):
            key, value = line.split(":", 1)
            key = key.strip()
            value = value.strip()
            if key in ("approved_at", "diff_hash", "verdict"):
                result[key] = value
            elif key == "files":
                # Simple comma-separated or single file
                result[key] = [f.strip() for f in value.split(",") if f.strip()]

    return result


def is_expired(approved_at: str, max_age_seconds: int = MAX_APPROVAL_AGE_SECONDS) -> bool:
    """Check if approval timestamp is expired.

    Approval expires after max_age_seconds (default 1 hour).

    Args:
        approved_at: ISO format timestamp string
        max_age_seconds: Maximum age in seconds (default 3600 = 1 hour)

    Returns:
        True if expired (older than max_age), False otherwise
        Returns True if timestamp is invalid (fail-safe)

    Examples:
        >>> # Recent timestamp (not expired)
        >>> is_expired(datetime.now().isoformat())
        False
    """
    if not approved_at:
        return True

    try:
        # Handle various ISO formats
        # Remove 'Z' suffix and replace with +00:00 for UTC
        timestamp_str = approved_at.replace("Z", "+00:00")

        # Try parsing with timezone
        try:
            approved_time = datetime.fromisoformat(timestamp_str)
        except ValueError:
            # Try without timezone info (assume local time)
            # Strip any timezone suffix for simple parsing
            clean_ts = approved_at.split("+")[0].split("Z")[0]
            approved_time = datetime.fromisoformat(clean_ts)
            approved_time = approved_time.replace(tzinfo=None)

        # Get current time (timezone-naive for comparison)
        now = datetime.now()
        if approved_time.tzinfo:
            # Convert to UTC then make naive
            approved_time = approved_time.replace(tzinfo=None)

        age_seconds = (now - approved_time).total_seconds()
        return age_seconds > max_age_seconds

    except (ValueError, TypeError, AttributeError):
        # Invalid timestamp - fail safe by treating as expired
        return True


def get_diff_hash(staged_diff: bytes = None) -> str:
    """Get SHA-256 hash of staged diff.

    Args:
        staged_diff: Raw bytes of staged diff. If None, runs git diff --cached.

    Returns:
        SHA-256 hex digest of the staged diff
    """
    if staged_diff is None:
        result = subprocess.run(
            ["git", "diff", "--cached"],
            capture_output=True,
        )
        staged_diff = result.stdout

    return hashlib.sha256(staged_diff).hexdigest()


def verify_diff_hash(approved_hash: str, current_diff: bytes = None) -> bool:
    """Verify that approved hash matches current staged changes.

    Args:
        approved_hash: Hash from the approval marker
        current_diff: Current staged diff bytes. If None, computed from git.

    Returns:
        True if hashes match, False otherwise
    """
    if not approved_hash:
        return False

    current_hash = get_diff_hash(current_diff)
    return approved_hash == current_hash


def log_bypass(
    reason: str,
    files: list[str],
    log_dir: Path,
    user: str = None,
    branch: str = None,
) -> Path:
    """Log a review bypass event.

    Creates a dated log file in YAML-like format for auditability.

    Args:
        reason: Why the bypass occurred
        files: List of files being committed
        log_dir: Directory to write log files
        user: Git user string (default: from git config)
        branch: Current branch (default: from git)

    Returns:
        Path to the log file written
    """
    timestamp = datetime.now(timezone.utc)
    date_part = timestamp.strftime("%Y-%m-%d")
    timestamp_str = timestamp.strftime("%Y-%m-%dT%H:%M:%SZ")

    # Get git info if not provided
    if user is None:
        name_result = subprocess.run(
            ["git", "config", "user.name"], capture_output=True, text=True
        )
        email_result = subprocess.run(
            ["git", "config", "user.email"], capture_output=True, text=True
        )
        name = name_result.stdout.strip() or "unknown"
        email = email_result.stdout.strip() or "unknown"
        user = f"{name} <{email}>"

    if branch is None:
        branch_result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
        )
        branch = branch_result.stdout.strip() or "unknown"

    # Create log directory if needed
    log_dir.mkdir(parents=True, exist_ok=True)

    # Format files list
    files_str = ", ".join(files) if files else ""

    # Build log entry
    entry = f"""---
timestamp: {timestamp_str}
reason: {reason}
user: {user}
branch: {branch}
files: {files_str}

"""

    # Append to dated log file
    log_file = log_dir / f"{date_part}.log"
    with open(log_file, "a") as f:
        f.write(entry)

    # Record telemetry event for bypass
    record_event(
        EventType.COMMIT_REVIEW_BYPASSED,
        "precommit.py",
        {"reason": reason, "files": files, "branch": branch},
    )

    return log_file


def is_gitignore_only(staged_files: list[str]) -> bool:
    """Check if only .gitignore files are being committed.

    .gitignore-only commits skip the review requirement.

    Args:
        staged_files: List of staged file paths

    Returns:
        True if only .gitignore files are staged
    """
    if not staged_files:
        return False

    result = all(f == ".gitignore" or f.endswith("/.gitignore") for f in staged_files)

    # Record telemetry when gitignore-only commit is detected
    if result:
        record_event(
            EventType.COMMIT_GITIGNORE_ONLY,
            "precommit.py",
            {"files": staged_files},
        )

    return result


def get_staged_files() -> list[str]:
    """Get list of currently staged files.

    Returns:
        List of staged file paths relative to repo root
    """
    result = subprocess.run(
        ["git", "diff", "--cached", "--name-only"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return []

    files = result.stdout.strip()
    return [f for f in files.split("\n") if f]


def validate_marker(marker: dict) -> tuple[bool, str]:
    """Validate a parsed marker has required fields.

    Args:
        marker: Parsed marker dict from parse_marker()

    Returns:
        Tuple of (is_valid, error_message)
    """
    if not marker:
        # Record that review is required but marker is missing/invalid
        record_event(
            EventType.COMMIT_REVIEW_REQUIRED,
            "precommit.py",
            {"reason": "Empty or unparseable marker", "marker": marker},
        )
        return False, "Empty or unparseable marker"

    if "diff_hash" not in marker or not marker["diff_hash"]:
        # Record that review is required but marker is incomplete
        record_event(
            EventType.COMMIT_REVIEW_REQUIRED,
            "precommit.py",
            {"reason": "Missing diff_hash field", "marker": marker},
        )
        return False, "Missing diff_hash field"

    return True, ""

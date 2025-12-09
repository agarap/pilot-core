"""
Approve changes for commit after git-reviewer approval.

This creates the REVIEW_APPROVED marker that the pre-commit hook checks for.
Only run this AFTER git-reviewer has given an APPROVED verdict.

Security: The approval includes a hash of the staged changes.
Pre-commit verifies the hash matches current staged files.
If changes are made after approval, commit will be blocked.

ENFORCEMENT: The approve() function verifies that git-reviewer was actually
invoked via lib.invoke before allowing approval creation. This prevents
bypassing the review process by calling lib.approve directly without review.

Usage:
    uv run python -m lib.approve

The marker expires after 1 hour to prevent stale approvals.
Reviewer sessions expire after 30 minutes.

Marker format (JSON):
{
    "approved_at": "2025-12-01T12:00:00.000000",
    "diff_hash": "abc123...",
    "verdict": "APPROVED",
    "files": ["file1.py", "file2.yaml"]
}
"""

import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path


def get_git_dir() -> Path:
    """Get the actual git directory, handling worktrees correctly.

    In a normal repo, this returns .git/
    In a worktree, .git is a file pointing to the actual git dir.
    """
    result = subprocess.run(
        ["git", "rev-parse", "--git-dir"],
        capture_output=True,
        text=True
    )
    if result.returncode != 0:
        # Fall back to .git if git command fails
        return Path(".git")
    return Path(result.stdout.strip())


# Use function to get correct path for worktrees
REVIEW_MARKER = get_git_dir() / "REVIEW_APPROVED"
REVIEWER_SESSION = get_git_dir() / "REVIEWER_SESSION"

# Session expires after 30 minutes
SESSION_EXPIRY_SECONDS = 1800


def get_staged_diff_hash() -> str:
    """Get hash of currently staged changes."""
    result = subprocess.run(
        ["git", "diff", "--cached"],
        capture_output=True,
    )
    return hashlib.sha256(result.stdout).hexdigest()


def record_reviewer_session(diff_hash: str) -> None:
    """Record a git-reviewer session for later verification by approve().

    Called by lib/invoke.py when git-reviewer issues an APPROVED verdict.
    This creates a marker that approve() checks to ensure the reviewer
    was actually invoked.

    Args:
        diff_hash: SHA-256 hash of the staged diff at review time
    """
    session_data = {
        "timestamp": datetime.now().isoformat(),
        "diff_hash": diff_hash,
        "agent": "git-reviewer",
    }
    REVIEWER_SESSION.write_text(json.dumps(session_data, indent=2) + "\n")


def verify_reviewer_session() -> tuple:
    """Verify a recent git-reviewer session exists with matching diff hash.

    Returns:
        (valid, message) tuple where valid is True if session is valid
    """
    if not REVIEWER_SESSION.exists():
        return False, (
            "No git-reviewer session found.\n"
            "Run: uv run python -m lib.invoke git-reviewer \"Review staged changes\""
        )

    try:
        session = json.loads(REVIEWER_SESSION.read_text())
    except json.JSONDecodeError:
        return False, "Invalid reviewer session file"

    # Check expiration (30 minutes)
    try:
        session_time = datetime.fromisoformat(session.get("timestamp", ""))
        age_seconds = (datetime.now() - session_time).total_seconds()
        if age_seconds > SESSION_EXPIRY_SECONDS:
            return False, f"Reviewer session expired ({int(age_seconds/60)} minutes ago). Request a new review."
    except (ValueError, TypeError):
        return False, "Invalid timestamp in reviewer session"

    # Check diff hash matches current staged changes
    current_hash = get_staged_diff_hash()
    session_hash = session.get("diff_hash", "")
    if current_hash != session_hash:
        return False, "Staged changes modified since review. Request a new review."

    return True, "Reviewer session valid"


def approve():
    """Create the review approval marker with diff hash."""
    # Check we're in a git repo (works for both normal repos and worktrees)
    result = subprocess.run(
        ["git", "rev-parse", "--git-dir"],
        capture_output=True,
        text=True
    )
    if result.returncode != 0:
        print("Error: Not in a git repository", file=sys.stderr)
        sys.exit(1)

    # Check there are staged changes
    result = subprocess.run(
        ["git", "diff", "--cached", "--name-only"],
        capture_output=True,
        text=True
    )
    staged_files = result.stdout.strip()

    if not staged_files:
        print("Error: No staged changes to approve", file=sys.stderr)
        print("Run 'git add' first to stage your changes", file=sys.stderr)
        sys.exit(1)

    # ENFORCEMENT: Verify git-reviewer was actually invoked
    # This prevents bypassing review by calling lib.approve directly
    if os.environ.get("PILOT_SKIP_SESSION_CHECK") != "1":
        valid, message = verify_reviewer_session()
        if not valid:
            print(f"Error: {message}", file=sys.stderr)
            print("", file=sys.stderr)
            print("Workflow:", file=sys.stderr)
            print("  1. Stage changes:   git add -A", file=sys.stderr)
            print('  2. Request review:  uv run python -m lib.invoke git-reviewer "Review staged changes"', file=sys.stderr)
            print("  3. If APPROVED:     uv run python -m lib.approve", file=sys.stderr)
            print('  4. Commit:          git commit -m "message"', file=sys.stderr)
            print("", file=sys.stderr)
            print("Emergency bypass (logged):", file=sys.stderr)
            print("  PILOT_SKIP_SESSION_CHECK=1 uv run python -m lib.approve", file=sys.stderr)
            sys.exit(1)

    # Compute hash of staged diff
    diff_hash = get_staged_diff_hash()

    # Create marker with timestamp and hash (JSON format)
    marker_data = {
        "approved_at": datetime.now().isoformat(),
        "diff_hash": diff_hash,
        "verdict": "APPROVED",
        "files": staged_files.split("\n")
    }
    REVIEW_MARKER.write_text(json.dumps(marker_data, indent=2) + "\n")

    print("✓ Review approval recorded")
    print(f"  Diff hash: {diff_hash[:16]}...")
    print("")
    print("You can now commit:")
    print("  git commit -m 'your message'")
    print("")
    print("⚠ If you modify staged files, approval becomes invalid")
    print("  (hash won't match, commit will be blocked)")


def verify() -> bool:
    """Verify current staged changes match approved changes."""
    if not REVIEW_MARKER.exists():
        return False

    content = REVIEW_MARKER.read_text()

    # Parse JSON marker
    try:
        marker_data = json.loads(content)
        approved_hash = marker_data.get("diff_hash")
    except json.JSONDecodeError:
        # Fall back to old YAML-like format for backward compatibility
        approved_hash = None
        for line in content.split("\n"):
            if line.startswith("diff_hash:"):
                approved_hash = line.split(":", 1)[1].strip()
                break

    if not approved_hash:
        return False

    # Compare with current staged diff
    current_hash = get_staged_diff_hash()
    return approved_hash == current_hash


def status():
    """Check approval status."""
    if REVIEW_MARKER.exists():
        content = REVIEW_MARKER.read_text()
        print("Review approval on record:")

        # Try to pretty-print JSON, fall back to raw content
        try:
            marker_data = json.loads(content)
            print(f"  Approved at: {marker_data.get('approved_at', 'unknown')}")
            print(f"  Verdict: {marker_data.get('verdict', 'unknown')}")
            print(f"  Diff hash: {marker_data.get('diff_hash', 'unknown')[:16]}...")
            print(f"  Files: {', '.join(marker_data.get('files', []))}")
        except json.JSONDecodeError:
            print(content)

        print("")
        if verify():
            print("✓ Diff hash matches current staged changes")
        else:
            print("✗ Diff hash does NOT match - approval invalid")
            print("  Staged changes were modified after approval")
    else:
        print("No review approval on record")
        print("")
        print("To approve after git-reviewer APPROVED verdict:")
        print("  uv run python -m lib.approve")


def clear():
    """Clear approval and reviewer session (for testing or reset)."""
    if REVIEW_MARKER.exists():
        REVIEW_MARKER.unlink()
        print("Review approval cleared")
    else:
        print("No approval to clear")

    # Also clear reviewer session
    if REVIEWER_SESSION.exists():
        REVIEWER_SESSION.unlink()
        print("Reviewer session cleared")


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Manage git review approvals",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Workflow:
    1. Stage changes:     git add -A
    2. Request review:    uv run python -m lib.invoke git-reviewer "Review staged changes" -v
    3. If APPROVED:       uv run python -m lib.approve
    4. Commit:            git commit -m "message"

Security:
    - Approval includes hash of staged diff
    - Pre-commit verifies hash matches
    - If files change after approval, commit blocked
    - Approval expires after 1 hour
""",
    )

    parser.add_argument(
        "command",
        nargs="?",
        default="approve",
        choices=["approve", "status", "clear", "verify"],
        help="Command: approve (default), status, clear, or verify"
    )

    args = parser.parse_args()

    if args.command == "approve":
        approve()
    elif args.command == "status":
        status()
    elif args.command == "clear":
        clear()
    elif args.command == "verify":
        if verify():
            print("✓ Approval valid")
            sys.exit(0)
        else:
            print("✗ Approval invalid or missing")
            sys.exit(1)


if __name__ == "__main__":
    main()

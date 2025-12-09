"""
Simple git branch utilities for VM-based pilot sessions.

In the new VM model:
- Each pilot invocation runs in a fresh VM
- Git remote handles persistence between invocations
- No need for worktrees, session registries, or cross-session coordination

This module provides simple branch helpers for the simplified workflow.
"""

import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).parent.parent


def get_current_branch() -> str:
    """Get current git branch name."""
    result = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    return result.stdout.strip() if result.returncode == 0 else ""


def is_on_main() -> bool:
    """Check if currently on main branch."""
    return get_current_branch() == "main"


def create_feature_branch(name: str, base: str = "main") -> dict:
    """
    Create a feature branch for working on a task.

    Args:
        name: Branch name (will be prefixed with 'feature/')
        base: Base branch to create from (default: main)

    Returns:
        Dict with success status and branch info
    """
    branch_name = f"feature/{name}" if not name.startswith("feature/") else name

    # Fetch latest from remote first
    subprocess.run(
        ["git", "fetch", "origin", base],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )

    # Create and checkout the branch
    result = subprocess.run(
        ["git", "checkout", "-b", branch_name, f"origin/{base}"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )

    if result.returncode != 0:
        # Branch might already exist, try to check it out
        result = subprocess.run(
            ["git", "checkout", branch_name],
            capture_output=True,
            text=True,
            cwd=REPO_ROOT,
        )
        if result.returncode != 0:
            return {
                "success": False,
                "error": result.stderr,
            }

    return {
        "success": True,
        "branch": branch_name,
        "message": f"On branch {branch_name}",
    }


def push_branch(branch: str = None) -> dict:
    """
    Push current branch to remote.

    Args:
        branch: Branch name (default: current branch)

    Returns:
        Dict with success status
    """
    if branch is None:
        branch = get_current_branch()

    result = subprocess.run(
        ["git", "push", "-u", "origin", branch],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )

    return {
        "success": result.returncode == 0,
        "branch": branch,
        "error": result.stderr if result.returncode != 0 else None,
    }


def pull_latest(branch: str = "main") -> dict:
    """
    Pull latest changes from remote.

    Args:
        branch: Branch to pull (default: main)

    Returns:
        Dict with success status
    """
    result = subprocess.run(
        ["git", "pull", "origin", branch],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )

    return {
        "success": result.returncode == 0,
        "error": result.stderr if result.returncode != 0 else None,
    }


def get_branch_status() -> dict:
    """
    Get current branch status for display.

    Returns:
        Dict with branch info and status
    """
    branch = get_current_branch()

    # Check if there are uncommitted changes
    status_result = subprocess.run(
        ["git", "status", "--porcelain"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    has_changes = bool(status_result.stdout.strip())

    # Check commits ahead/behind
    subprocess.run(
        ["git", "fetch", "origin"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )

    ahead_result = subprocess.run(
        ["git", "rev-list", "--count", f"origin/{branch}..HEAD"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    ahead = int(ahead_result.stdout.strip()) if ahead_result.returncode == 0 else 0

    behind_result = subprocess.run(
        ["git", "rev-list", "--count", f"HEAD..origin/{branch}"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    behind = int(behind_result.stdout.strip()) if behind_result.returncode == 0 else 0

    return {
        "branch": branch,
        "is_main": branch == "main",
        "has_uncommitted_changes": has_changes,
        "commits_ahead": ahead,
        "commits_behind": behind,
    }


# CLI interface
def main():
    import argparse
    import json

    parser = argparse.ArgumentParser(
        description="Simple git branch utilities",
    )

    subparsers = parser.add_subparsers(dest="command", help="Command")

    # status
    subparsers.add_parser("status", help="Get branch status")

    # create
    create_parser = subparsers.add_parser("create", help="Create feature branch")
    create_parser.add_argument("name", help="Branch name")
    create_parser.add_argument("--base", "-b", default="main", help="Base branch")

    # push
    subparsers.add_parser("push", help="Push current branch to remote")

    # pull
    pull_parser = subparsers.add_parser("pull", help="Pull latest from remote")
    pull_parser.add_argument("--branch", "-b", default="main", help="Branch to pull")

    args = parser.parse_args()

    if args.command == "status":
        result = get_branch_status()
        print(json.dumps(result, indent=2))

    elif args.command == "create":
        result = create_feature_branch(args.name, args.base)
        if result["success"]:
            print(f"Created/switched to branch: {result['branch']}")
        else:
            print(f"Error: {result['error']}")
            return 1

    elif args.command == "push":
        result = push_branch()
        if result["success"]:
            print(f"Pushed branch: {result['branch']}")
        else:
            print(f"Error: {result['error']}")
            return 1

    elif args.command == "pull":
        result = pull_latest(args.branch)
        if result["success"]:
            print(f"Pulled latest from {args.branch}")
        else:
            print(f"Error: {result['error']}")
            return 1

    else:
        parser.print_help()

    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())

"""
Unified startup check for Pilot.

At conversation start, Pilot should run this to:
1. Check current branch status
2. Detect stuck sessions that may need resumption
3. Identify active projects with feature lists
4. Provide recommendations for what to do next

Usage:
    # At conversation start
    uv run python -m lib.startup

    # JSON output for programmatic use
    uv run python -m lib.startup --json

    # Check specific project
    uv run python -m lib.startup --project myproject
"""

import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

from lib.resume import check_for_stuck_sessions
from lib.telemetry import record_event, EventType


def get_branch_status() -> dict:
    """Get current branch status."""
    result = {
        "current_branch": "",
        "is_main": False,
        "repo_path": "",
    }

    # Get current branch
    branch_result = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        capture_output=True,
        text=True,
    )
    if branch_result.returncode == 0:
        result["current_branch"] = branch_result.stdout.strip()
        result["is_main"] = result["current_branch"] == "main"

    # Get repo path
    path_result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
    )
    if path_result.returncode == 0:
        result["repo_path"] = path_result.stdout.strip()

    return result


def get_active_projects() -> list[dict]:
    """Find projects with feature_list.json files."""
    projects = []
    projects_dir = Path("projects")

    if not projects_dir.exists():
        return projects

    for project_dir in projects_dir.iterdir():
        if not project_dir.is_dir():
            continue

        feature_list = project_dir / "feature_list.json"
        if not feature_list.exists():
            continue

        try:
            with open(feature_list) as f:
                data = json.load(f)

            features = data.get("features", [])
            total = len(features)
            passing = sum(1 for f in features if f.get("passes", False))

            projects.append({
                "name": project_dir.name,
                "total_features": total,
                "passing_features": passing,
                "progress_pct": round(passing / total * 100, 1) if total > 0 else 0,
                "complete": passing == total and total > 0,
            })
        except (json.JSONDecodeError, IOError):
            continue

    # Sort by progress (least complete first = most likely to work on)
    projects.sort(key=lambda p: p["progress_pct"])
    return projects


def generate_recommendations(
    branch_status: dict,
    stuck_sessions: list[dict],
    active_projects: list[dict],
    task_description: Optional[str] = None,
) -> list[dict]:
    """Generate recommendations based on current state."""
    recommendations = []

    # Priority 1: Stuck sessions
    if stuck_sessions:
        for session in stuck_sessions[:2]:  # Top 2 stuck sessions
            recommendations.append({
                "priority": 1,
                "type": "resume_session",
                "message": f"Resume stuck session: {session['task'][:60]}...",
                "action": f"uv run python -m lib.resume {session['session_id']} --clipboard",
                "session_id": session["session_id"],
            })

    # Priority 2: Continue incomplete projects
    incomplete_projects = [p for p in active_projects if not p["complete"]]
    if incomplete_projects:
        project = incomplete_projects[0]  # Least complete
        recommendations.append({
            "priority": 2,
            "type": "continue_project",
            "message": f"Continue project '{project['name']}' ({project['progress_pct']}% complete)",
            "action": f"uv run python -m tools feature_tracker '{{\"action\": \"next\", \"project\": \"{project['name']}\"}}'"
        })

    # Sort by priority
    recommendations.sort(key=lambda r: r["priority"])
    return recommendations


def startup_check(
    task_description: Optional[str] = None,
    project: Optional[str] = None,
    max_stuck_age_hours: float = 24,
) -> dict:
    """
    Comprehensive startup check for Pilot.

    Run this at the START of every conversation to:
    - Detect stuck sessions that may need resumption
    - Check branch status
    - Identify active projects
    - Generate recommendations

    Args:
        task_description: Optional description of what user wants to do
        project: Optional specific project to check
        max_stuck_age_hours: Only consider sessions from last N hours

    Returns:
        Dict with branch_status, stuck_sessions, active_projects, recommendations
    """
    # Get branch status
    branch_status = get_branch_status()

    # Check for stuck sessions
    project_path = str(Path.cwd())
    stuck_sessions = check_for_stuck_sessions(
        project_path=project_path,
        max_age_hours=max_stuck_age_hours,
    )

    # Get active projects
    active_projects = get_active_projects()

    # Filter to specific project if requested
    if project:
        active_projects = [p for p in active_projects if p["name"] == project]

    # Generate recommendations
    recommendations = generate_recommendations(
        branch_status=branch_status,
        stuck_sessions=stuck_sessions,
        active_projects=active_projects,
        task_description=task_description,
    )

    # Record telemetry
    try:
        record_event(
            EventType.IMPORT_ALLOWED,  # Reuse as generic "system event"
            "startup.py",
            {
                "event": "startup_check",
                "stuck_sessions_found": len(stuck_sessions),
                "active_projects": len(active_projects),
                "recommendations": len(recommendations),
                "branch": branch_status.get("current_branch", ""),
            },
        )
    except Exception:
        pass  # Don't fail startup on telemetry errors

    return {
        "timestamp": datetime.now().isoformat(),
        "branch_status": branch_status,
        "stuck_sessions": stuck_sessions,
        "active_projects": active_projects,
        "recommendations": recommendations,
        "has_stuck_sessions": len(stuck_sessions) > 0,
        "has_active_projects": len(active_projects) > 0,
    }


def format_startup_report(result: dict) -> str:
    """Format startup check result as human-readable text."""
    lines = []

    # Header
    lines.append("=" * 60)
    lines.append("PILOT STARTUP CHECK")
    lines.append("=" * 60)

    # Branch status
    bs = result["branch_status"]
    lines.append(f"\nBranch: {bs['current_branch']}")

    # Stuck sessions
    stuck = result["stuck_sessions"]
    if stuck:
        lines.append(f"\n{'─' * 40}")
        lines.append("STUCK SESSIONS DETECTED")
        lines.append(f"{'─' * 40}")
        for s in stuck[:3]:
            status_marker = "!" if s.get("has_error") else "?"
            lines.append(f"  [{status_marker}] {s['short_id']}: {s['task'][:50]}...")
            if s.get("pending_todos", 0) > 0:
                lines.append(f"      {s['pending_todos']} pending todos")
        lines.append("")
        lines.append("  To resume: uv run python -m lib.resume <session-id> --clipboard")

    # Active projects
    projects = result["active_projects"]
    if projects:
        lines.append(f"\n{'─' * 40}")
        lines.append("ACTIVE PROJECTS")
        lines.append(f"{'─' * 40}")
        for p in projects[:5]:
            status = "✓" if p["complete"] else "○"
            lines.append(f"  [{status}] {p['name']}: {p['passing_features']}/{p['total_features']} ({p['progress_pct']}%)")

    # Recommendations
    recs = result["recommendations"]
    if recs:
        lines.append(f"\n{'─' * 40}")
        lines.append("RECOMMENDATIONS")
        lines.append(f"{'─' * 40}")
        for r in recs[:5]:
            lines.append(f"  → {r['message']}")
            lines.append(f"    {r['action']}")

    # Footer
    lines.append("\n" + "=" * 60)

    return "\n".join(lines)


def main():
    """CLI entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Run Pilot startup checks",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Run startup check
    uv run python -m lib.startup

    # JSON output
    uv run python -m lib.startup --json

    # Check with task context
    uv run python -m lib.startup --task "continue the enforcement-telemetry project"

    # Check specific project
    uv run python -m lib.startup --project enforcement-telemetry
""",
    )

    parser.add_argument("--json", "-j", action="store_true", help="Output as JSON")
    parser.add_argument("--task", "-t", help="Task description for context-aware recommendations")
    parser.add_argument("--project", "-p", help="Specific project to check")
    parser.add_argument("--max-age", type=float, default=24, help="Max age in hours for stuck sessions")

    args = parser.parse_args()

    result = startup_check(
        task_description=args.task,
        project=args.project,
        max_stuck_age_hours=args.max_age,
    )

    if args.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        print(format_startup_report(result))

    # Exit with code 1 if stuck sessions found (for scripting)
    if result["has_stuck_sessions"]:
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()

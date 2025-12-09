"""
tool: feature_tracker
description: Manage feature_list.json files for long-running projects (backward-compatible wrapper for project_tracker)
parameters:
  action: Action to perform (list, mark_passing, mark_failing, add, next)
  project: Project name (directory under projects/)
  feature_id: Feature ID for mark/get actions (optional)
  feature_data: Feature data for add action (optional)
  quiet: Silence lesson suggestion prompt on mark_passing (optional, default false)
returns: Feature information or operation result

NOTE: This tool is now a backward-compatible wrapper around project_tracker.
For new projects, consider using project_tracker directly which supports
additional project types (research, planning, knowledge, investigation).
"""

import json
import sys
from typing import Optional, Dict, Any

# Import from project_tracker for all core functionality
from pilot_tools.project_tracker import project_tracker


def feature_tracker(
    action: str,
    project: str,
    feature_id: Optional[str] = None,
    feature_data: Optional[Dict[str, Any]] = None,
    quiet: bool = False,
) -> Dict[str, Any]:
    """
    Manage feature_list.json for projects.

    This is a backward-compatible wrapper around project_tracker.
    For feature-type projects, all existing functionality is preserved.

    Actions:
    - list: Show all features with summary
    - mark_passing: Mark a feature as passing
    - mark_failing: Mark a feature as failing
    - add: Add a new feature
    - next: Get next priority feature to work on

    Uses JSON format because models are less likely to
    inappropriately modify JSON files compared to YAML/Markdown.
    """
    # Map feature_tracker parameters to project_tracker parameters
    return project_tracker(
        action=action,
        project=project,
        item_id=feature_id,
        item_data=feature_data,
        quiet=quiet,
    )


if __name__ == "__main__":
    # Backward-compatible CLI
    if len(sys.argv) < 2:
        print("Usage: python -m tools feature_tracker '<json_args>'")
        print("Or:    python -m tools feature_tracker <action> <project> [options]")
        sys.exit(1)

    # Try JSON format first
    try:
        args = json.loads(sys.argv[1])
        result = feature_tracker(**args)
    except json.JSONDecodeError:
        # Fall back to positional args (legacy)
        if len(sys.argv) < 3:
            print("Usage: python -m tools feature_tracker <action> <project> [options]")
            sys.exit(1)
        action = sys.argv[1]
        project = sys.argv[2]
        result = feature_tracker(action=action, project=project)

    print(json.dumps(result, indent=2))

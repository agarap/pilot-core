"""
tool: detect_task_tool
description: Scan agent logs for banned Task tool usage (Claude Code's built-in Task tool)
parameters:
  logs_dir: Directory containing agent logs (default: logs/agents)
  since: Only check logs after this timestamp (ISO format or hours ago)
returns: JSON report with violations including agent name, timestamp, task type, and context
"""

import argparse
import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional


# Banned subagent types from Claude Code's built-in Task tool
BANNED_SUBAGENT_TYPES = {
    "general-purpose",
    "Explore",
    "Plan",
    "code-architect-reviewer",
    "statusline-setup",
}


def parse_timestamp(ts: str) -> Optional[datetime]:
    """Parse a timestamp string into datetime, handling various formats."""
    if not ts:
        return None

    # Try common formats
    formats = [
        "%Y-%m-%dT%H:%M:%S.%f",  # ISO with microseconds
        "%Y-%m-%dT%H:%M:%S",      # ISO without microseconds
        "%Y-%m-%d %H:%M:%S.%f",   # Space-separated with microseconds
        "%Y-%m-%d %H:%M:%S",      # Space-separated
    ]

    for fmt in formats:
        try:
            return datetime.strptime(ts, fmt)
        except ValueError:
            continue

    # Try fromisoformat as fallback (handles timezone-aware strings)
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None


def detect_task_tool(logs_dir: str = "logs/agents", since: Optional[datetime] = None) -> dict:
    """
    Scan agent logs for Task tool violations.

    Args:
        logs_dir: Directory containing agent logs (default: logs/agents)
        since: Only check logs after this timestamp (default: None, check all)

    Returns:
        dict with scan results and any violations found
    """
    logs_path = Path(logs_dir)

    if not logs_path.exists():
        return {
            "error": f"Logs directory not found: {logs_dir}",
            "scan_time": datetime.now().isoformat(),
            "since": since.isoformat() if since else None,
        }

    violations = []
    total_logs_scanned = 0
    logs_skipped_by_time = 0

    # Iterate through each agent's directory
    for agent_dir in logs_path.iterdir():
        if not agent_dir.is_dir():
            continue

        agent_name = agent_dir.name

        # Scan all JSON log files for this agent
        for log_file in agent_dir.glob("*.json"):
            try:
                data = json.loads(log_file.read_text())
            except (json.JSONDecodeError, IOError) as e:
                # Skip malformed files
                continue

            # Extract timestamp from log data
            log_timestamp = data.get("timestamp", "")

            # Filter by since timestamp if provided
            if since:
                parsed_ts = parse_timestamp(log_timestamp)
                if parsed_ts is None or parsed_ts < since:
                    logs_skipped_by_time += 1
                    continue

            total_logs_scanned += 1

            # Get tool uses from output
            tool_uses = data.get("output", {}).get("tool_uses", [])

            for tool_use in tool_uses:
                if tool_use.get("tool") != "Task":
                    continue

                # Found a Task tool usage - this is a violation
                input_data = tool_use.get("input", {})
                subagent_type = input_data.get("subagent_type", "unknown")
                description = input_data.get("description", "")
                prompt = input_data.get("prompt", "")

                # Extract context: first 200 chars of prompt
                context = prompt[:200] + "..." if len(prompt) > 200 else prompt

                violation = {
                    "log_file": str(log_file),
                    "timestamp": log_timestamp,
                    "agent": agent_name,
                    "task_type": subagent_type,
                    "context": context or description,
                }

                violations.append(violation)

    # Sort violations by timestamp (newest first)
    violations.sort(key=lambda v: v.get("timestamp", ""), reverse=True)

    return {
        "scan_time": datetime.now().isoformat(),
        "since": since.isoformat() if since else None,
        "total_logs_scanned": total_logs_scanned,
        "logs_skipped_by_time": logs_skipped_by_time,
        "violation_count": len(violations),
        "violations": violations,
    }


if __name__ == "__main__":
    import sys

    parser = argparse.ArgumentParser(
        description="Detect banned Task tool usage in agent logs"
    )
    parser.add_argument(
        "--logs-dir",
        default="logs/agents",
        help="Directory containing agent logs (default: logs/agents)",
    )
    parser.add_argument(
        "--since",
        type=str,
        default=None,
        help="Only check logs after this ISO timestamp (e.g., 2024-12-03T10:00:00)",
    )
    parser.add_argument(
        "--hours",
        type=float,
        default=None,
        help="Only check logs from the last N hours (alternative to --since)",
    )

    args = parser.parse_args()

    # Determine the 'since' datetime
    since = None
    if args.hours is not None:
        since = datetime.now() - timedelta(hours=args.hours)
    elif args.since is not None:
        since = parse_timestamp(args.since)
        if since is None:
            print(f"Error: Could not parse timestamp: {args.since}", file=sys.stderr)
            sys.exit(2)

    result = detect_task_tool(args.logs_dir, since=since)
    print(json.dumps(result, indent=2))

    # Exit with code 1 if violations found (for pre-commit hook compatibility)
    if result.get("violation_count", 0) > 0:
        sys.exit(1)

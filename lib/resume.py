"""
Generate resume prompts for stuck/interrupted Claude Code sessions.

This module takes a parsed Session and generates a prompt that can be used
to resume work in a new Claude Code session. The prompt includes:
- Original task description
- Summary of work completed
- Files that were modified
- Pending todos
- Last error (if any)
- Instructions to continue

Usage:
    # List stuck sessions
    uv run python -m lib.resume --list

    # Generate resume prompt for a session
    uv run python -m lib.resume <session-id>

    # Copy to clipboard (macOS)
    uv run python -m lib.resume <session-id> --clipboard

    # Resume with full context
    uv run python -m lib.resume <session-id> --full
"""

import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional


def _utcnow() -> datetime:
    """Get current UTC time as naive datetime."""
    return datetime.now(timezone.utc).replace(tzinfo=None)

from lib.session import (
    Session,
    load_session,
    find_stuck_sessions,
    get_recent_sessions,
    list_project_sessions,
    ToolCall,
)


def _summarize_tool_calls(tool_calls: list[ToolCall], max_items: int = 20) -> str:
    """Summarize tool calls into a readable format."""
    if not tool_calls:
        return "  (none)"

    # Group by tool type
    by_tool = {}
    for tc in tool_calls:
        if tc.name not in by_tool:
            by_tool[tc.name] = []
        by_tool[tc.name].append(tc)

    lines = []
    for tool_name, calls in sorted(by_tool.items()):
        if tool_name == "Read":
            files = [c.input.get("file_path", "?") for c in calls]
            unique_files = list(set(files))[:5]
            lines.append(f"  - Read: {len(files)} files ({', '.join(Path(f).name for f in unique_files)}{'...' if len(unique_files) < len(files) else ''})")

        elif tool_name == "Write":
            files = [c.input.get("file_path", "?") for c in calls]
            lines.append(f"  - Write: {', '.join(Path(f).name for f in files)}")

        elif tool_name == "Edit":
            files = [c.input.get("file_path", "?") for c in calls]
            unique_files = list(set(files))[:5]
            lines.append(f"  - Edit: {len(calls)} edits to {', '.join(Path(f).name for f in unique_files)}")

        elif tool_name == "Bash":
            cmds = [c.input.get("command", "")[:50] for c in calls[:5]]
            lines.append(f"  - Bash: {len(calls)} commands")
            for cmd in cmds:
                lines.append(f"      {cmd}...")

        elif tool_name == "Task":
            descriptions = [c.input.get("description", "?") for c in calls]
            lines.append(f"  - Task (subagents): {', '.join(descriptions[:3])}")

        elif tool_name in ("Grep", "Glob"):
            lines.append(f"  - {tool_name}: {len(calls)} searches")

        else:
            lines.append(f"  - {tool_name}: {len(calls)} calls")

    return "\n".join(lines[:max_items])


def _format_todos(todos: list[dict]) -> str:
    """Format todos for the resume prompt."""
    if not todos:
        return "  (none)"

    lines = []
    for t in todos:
        status = t.get("status", "?")
        content = t.get("content", "?")
        marker = "x" if status == "completed" else " " if status == "pending" else ">"
        lines.append(f"  [{marker}] {content}")

    return "\n".join(lines)


def _truncate_middle(text: str, max_length: int = 2000) -> str:
    """Truncate text in the middle if too long."""
    if len(text) <= max_length:
        return text

    half = max_length // 2 - 20
    return text[:half] + "\n\n... [truncated] ...\n\n" + text[-half:]


def generate_resume_prompt(
    session: Session,
    include_full_messages: bool = False,
    max_message_length: int = 500,
) -> str:
    """
    Generate a resume prompt for a stuck session.

    Args:
        session: The session to resume
        include_full_messages: Include full message history (vs summary)
        max_message_length: Max length per message in summary

    Returns:
        A prompt string that can be used to resume the session
    """
    lines = []

    # Header
    lines.append("# RESUME SESSION")
    lines.append("")
    lines.append("This is a CONTINUATION of a previous Claude Code session that was interrupted.")
    lines.append("Please review the context below and continue where it left off.")
    lines.append("")

    # Session metadata
    lines.append("## Session Info")
    lines.append(f"- **Session ID**: `{session.session_id}`")
    lines.append(f"- **Project**: `{session.project_path}`")
    lines.append(f"- **Started**: {session.started_at.strftime('%Y-%m-%d %H:%M')}")
    lines.append(f"- **Last Activity**: {session.last_activity.strftime('%Y-%m-%d %H:%M')}")
    lines.append(f"- **Status**: {session.status}")
    lines.append(f"- **Duration**: {session.duration_minutes:.1f} minutes")
    lines.append("")

    # Original task
    lines.append("## Original Task")
    lines.append("```")
    lines.append(_truncate_middle(session.initial_prompt, 2000))
    lines.append("```")
    lines.append("")

    # Work completed
    lines.append("## Work Completed")
    lines.append("")
    lines.append("### Tool Usage Summary")
    lines.append(_summarize_tool_calls(session.tool_calls))
    lines.append("")

    # Files modified
    if session.files_written:
        lines.append("### Files Created/Modified")
        for f in session.files_written[:20]:
            lines.append(f"  - `{f}`")
        if len(session.files_written) > 20:
            lines.append(f"  - ... and {len(session.files_written) - 20} more")
        lines.append("")

    # Bash commands
    recent_commands = session.bash_commands[-5:]
    if recent_commands:
        lines.append("### Recent Commands")
        for cmd in recent_commands:
            lines.append(f"  - `{cmd[:80]}{'...' if len(cmd) > 80 else ''}`")
        lines.append("")

    # Current state (todos)
    lines.append("## Current State")
    lines.append("")
    lines.append("### Todo List")
    lines.append(_format_todos(session.todos))
    lines.append("")

    # Error info
    if session.last_error:
        lines.append("## Last Error")
        lines.append("```")
        lines.append(_truncate_middle(session.last_error, 1000))
        lines.append("```")
        lines.append("")

    # Message history (condensed)
    if include_full_messages:
        lines.append("## Message History")
        lines.append("")
        for i, msg in enumerate(session.messages[-10:]):  # Last 10 messages
            role_marker = "USER" if msg.role == "user" else "ASSISTANT"
            lines.append(f"### [{role_marker}] ({msg.timestamp.strftime('%H:%M')})")
            content = _truncate_middle(msg.content, max_message_length)
            lines.append(content)
            if msg.tool_calls:
                lines.append(f"  *Tools used: {', '.join(tc.name for tc in msg.tool_calls)}*")
            lines.append("")

    # Instructions for continuation
    lines.append("## Instructions")
    lines.append("")
    lines.append("Please continue this session:")
    lines.append("")

    if session.pending_todos:
        lines.append("1. **Complete pending todos** - The todo list above shows remaining work")
    else:
        lines.append("1. **Review the original task** - Determine if it was fully completed")

    if session.last_error:
        lines.append("2. **Investigate the error** - The session stopped due to an error")
    else:
        lines.append("2. **Continue from where work stopped** - Resume the last action")

    lines.append("3. **Update the todo list** - Mark completed items and add new ones as needed")
    lines.append("4. **Verify completion** - Ensure the original task is fully addressed")
    lines.append("")

    # Helpful context
    if session.files_written:
        lines.append("### Key Files to Review")
        lines.append("These files were modified in the previous session and may need review:")
        for f in session.files_written[:5]:
            lines.append(f"  - `{f}`")
        lines.append("")

    return "\n".join(lines)


def generate_minimal_resume(session: Session) -> str:
    """Generate a minimal one-paragraph resume prompt."""
    pending = [t.get("content", "?") for t in session.pending_todos]
    pending_str = ", ".join(pending[:3]) if pending else "none"

    files_str = ", ".join(Path(f).name for f in session.files_written[:3]) if session.files_written else "none"

    error_str = f" Last error: {session.last_error[:100]}..." if session.last_error else ""

    # Only add ellipsis if we actually truncated
    task_preview = session.initial_prompt[:200]
    if len(session.initial_prompt) > 200:
        task_preview += "..."

    prompt = f"""RESUME: Continue previous session (ID: {session.session_id[:8]}).

Original task: {task_preview}

Work done: {len(session.tool_calls)} tool calls, modified files: {files_str}.

Pending todos: {pending_str}.{error_str}

Please review and continue where the previous session left off. Check the todo list and complete any pending items."""

    return prompt


def copy_to_clipboard(text: str) -> bool:
    """Copy text to clipboard (macOS only)."""
    try:
        process = subprocess.Popen(
            ["pbcopy"],
            stdin=subprocess.PIPE,
            env={"LANG": "en_US.UTF-8"},
        )
        process.communicate(text.encode("utf-8"))
        return process.returncode == 0
    except Exception:
        return False


def check_for_stuck_sessions(
    project_path: Optional[str] = None,
    max_age_hours: float = 24,
) -> list[dict]:
    """
    Check for stuck sessions that may need to be resumed.

    This function is designed to be called proactively (e.g., at Pilot startup)
    to help users resume interrupted work.

    Args:
        project_path: Project path to check (default: current directory)
        max_age_hours: Only consider sessions from the last N hours

    Returns:
        List of dicts with session info for stuck sessions, empty if none found
    """
    project = project_path or str(Path.cwd())
    stuck = find_stuck_sessions(project)

    # Filter by age
    cutoff = _utcnow() - timedelta(hours=max_age_hours)
    recent_stuck = [s for s in stuck if s.last_activity > cutoff]

    # Return summary info for each
    return [
        {
            "session_id": s.session_id,
            "short_id": s.session_id[:8],
            "status": s.status,
            "task": s.initial_prompt[:100],
            "pending_todos": len(s.pending_todos),
            "last_activity": s.last_activity.isoformat(),
            "has_error": s.last_error is not None,
            "files_modified": len(s.files_written),
        }
        for s in recent_stuck[:5]  # Limit to 5 most recent
    ]


def format_stuck_sessions_alert(sessions: list[dict]) -> str:
    """
    Format an alert message about stuck sessions for display to the user.

    Args:
        sessions: List of session dicts from check_for_stuck_sessions

    Returns:
        Formatted alert message string
    """
    if not sessions:
        return ""

    lines = [
        "## Stuck Sessions Detected",
        "",
        "The following previous sessions appear to be stuck or errored:",
        "",
    ]

    for s in sessions:
        status_emoji = "!" if s["has_error"] else "?"
        task_preview = s["task"][:60].replace("\n", " ")
        lines.append(f"  [{status_emoji}] `{s['short_id']}` - {task_preview}...")
        if s["pending_todos"] > 0:
            lines.append(f"      {s['pending_todos']} pending todos")

    lines.extend([
        "",
        "To resume a session:",
        "```bash",
        "uv run python -m lib.resume <session-id> --clipboard",
        "```",
        "",
        "Or ask me to resume a specific session.",
    ])

    return "\n".join(lines)


def main():
    """CLI entry point for resume prompt generation."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Generate resume prompts for Claude Code sessions",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # List stuck sessions for current project
    uv run python -m lib.resume --list

    # Generate resume prompt for a session
    uv run python -m lib.resume abc12345

    # Copy resume prompt to clipboard
    uv run python -m lib.resume abc12345 --clipboard

    # Generate full resume with message history
    uv run python -m lib.resume abc12345 --full

    # Generate minimal one-paragraph resume
    uv run python -m lib.resume abc12345 --minimal
""",
    )

    parser.add_argument("session_id", nargs="?", help="Session ID (or prefix) to resume")
    parser.add_argument("--project", "-p", help="Project path (default: current directory)")
    parser.add_argument("--list", "-l", action="store_true", help="List stuck/recent sessions")
    parser.add_argument("--all", "-a", action="store_true", help="List all sessions (not just stuck)")
    parser.add_argument("--clipboard", "-c", action="store_true", help="Copy to clipboard (macOS)")
    parser.add_argument("--full", "-f", action="store_true", help="Include full message history")
    parser.add_argument("--minimal", "-m", action="store_true", help="Generate minimal one-paragraph resume")
    parser.add_argument("--json", "-j", action="store_true", help="Output session data as JSON")
    parser.add_argument("--limit", "-n", type=int, default=10, help="Number of sessions to list")

    args = parser.parse_args()

    project = args.project or str(Path.cwd())

    if args.list or args.all or not args.session_id:
        # List sessions
        if args.all:
            sessions = get_recent_sessions(project, limit=args.limit)
            title = "All Recent Sessions"
        else:
            sessions = find_stuck_sessions(project)
            if not sessions:
                sessions = get_recent_sessions(project, limit=args.limit)
                title = "Recent Sessions (no stuck sessions found)"
            else:
                title = "Stuck/Errored Sessions"

        print(f"\n{title} ({project}):\n")

        if not sessions:
            print("  No sessions found.")
            print(f"\n  Tip: Make sure the project path is correct.")
            print(f"       Current path: {project}")
            return

        for s in sessions:
            age_mins = (_utcnow() - s.last_activity).total_seconds() / 60
            if age_mins < 60:
                age_str = f"{int(age_mins)}m"
            elif age_mins < 1440:
                age_str = f"{int(age_mins/60)}h"
            else:
                age_str = f"{int(age_mins/1440)}d"

            status_colors = {
                "stuck": "\033[93m",      # Yellow
                "error": "\033[91m",      # Red
                "abandoned": "\033[90m",  # Gray
                "completed": "\033[92m",  # Green
                "in_progress": "\033[94m", # Blue
            }
            color = status_colors.get(s.status, "")
            reset = "\033[0m" if color else ""

            prompt_preview = s.initial_prompt[:50].replace("\n", " ")
            print(f"  {s.session_id[:8]}  {color}[{s.status:10}]{reset}  {age_str:>4} ago  {prompt_preview}...")

        print(f"\nTo resume a session:")
        print(f"  uv run python -m lib.resume <session-id> --clipboard")
        print(f"  uv run python -m lib.resume <session-id> | pbcopy")
        return

    # Generate resume prompt for a specific session
    session_id = args.session_id

    # Find matching session
    session_ids = list_project_sessions(project)
    matching = [sid for sid in session_ids if sid.startswith(session_id)]

    if not matching:
        print(f"No session found matching: {session_id}")
        print(f"Project: {project}")
        print(f"\nAvailable sessions:")
        for sid in session_ids[:10]:
            print(f"  {sid[:8]}")
        sys.exit(1)

    if len(matching) > 1:
        print(f"Multiple sessions match '{session_id}':")
        for sid in matching[:10]:
            print(f"  {sid}")
        print("\nPlease provide a more specific session ID.")
        sys.exit(1)

    full_session_id = matching[0]
    session = load_session(project, full_session_id)

    if not session:
        print(f"Failed to load session: {full_session_id}")
        sys.exit(1)

    # Output
    if args.json:
        data = {
            "session_id": session.session_id,
            "project_path": session.project_path,
            "status": session.status,
            "started_at": session.started_at.isoformat(),
            "last_activity": session.last_activity.isoformat(),
            "initial_prompt": session.initial_prompt,
            "tool_call_count": len(session.tool_calls),
            "files_written": session.files_written,
            "pending_todos": session.pending_todos,
            "last_error": session.last_error,
        }
        print(json.dumps(data, indent=2))

    elif args.minimal:
        prompt = generate_minimal_resume(session)
        if args.clipboard:
            if copy_to_clipboard(prompt):
                print("Minimal resume prompt copied to clipboard!")
                print(f"\n{prompt}")
            else:
                print("Failed to copy to clipboard. Here's the prompt:")
                print(f"\n{prompt}")
        else:
            print(prompt)

    else:
        prompt = generate_resume_prompt(
            session,
            include_full_messages=args.full,
        )

        if args.clipboard:
            if copy_to_clipboard(prompt):
                print("Resume prompt copied to clipboard!")
                print(f"\nSession: {session.session_id[:8]} ({session.status})")
                print(f"Task: {session.initial_prompt[:80]}...")
                print(f"\nPaste this prompt into a new Claude Code session to continue.")
            else:
                print("Failed to copy to clipboard. Here's the prompt:\n")
                print(prompt)
        else:
            print(prompt)


if __name__ == "__main__":
    main()

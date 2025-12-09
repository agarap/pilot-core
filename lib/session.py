"""
Parse and analyze Claude Code sessions for resume/recovery.

Claude Code stores conversations in:
- ~/.claude/projects/<encoded-path>/<session-id>.jsonl  - Main conversation
- ~/.claude/projects/<encoded-path>/agent-<id>.jsonl    - Subagent conversations
- ~/.claude/todos/<session-id>.json                     - Todo state
- ~/.claude/history.jsonl                               - Prompt history

Each JSONL line contains:
- type: "user" | "assistant" | "file-history-snapshot"
- message: The actual message content
- uuid: Unique ID
- parentUuid: Parent message ID (for threading)
- sessionId: Session identifier
- timestamp: ISO timestamp
- toolUseResult: Tool call results (if type="user" with tool result)
- todos: Current todo state
"""

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

CLAUDE_DIR = Path.home() / ".claude"
PROJECTS_DIR = CLAUDE_DIR / "projects"

# Environment variable that Claude Code sets for the current session
CURRENT_SESSION_ENV = "CLAUDE_SESSION_ID"


@dataclass
class ToolCall:
    """A tool invocation."""
    name: str
    input: dict
    result: Optional[str] = None
    is_error: bool = False
    timestamp: Optional[datetime] = None


# Tools whose errors are typically non-fatal (expected failures during exploration)
NON_FATAL_ERROR_TOOLS = {
    "Read",      # File not found during exploration
    "Grep",      # No matches found
    "Glob",      # No matches found
    "Bash",      # Command failures are often expected (e.g., test failures, grep no match)
}

# Error patterns that indicate non-fatal/expected errors
NON_FATAL_ERROR_PATTERNS = [
    "No such file or directory",
    "No matches found",
    "Pattern not found",
    "does not exist",
    "ENOENT",
    "exit code 1",  # Often just "no matches" for grep
    "requested permissions",  # User approval pending
    "haven't granted",  # Permission not yet granted
    "permission request",
    "modified since read",  # File changed externally, just re-read
    "read it again",  # Retry hint
    "tool_use_error",  # Often recoverable tool errors
    "is not running",  # Shell already completed
    "cannot be killed",  # Shell cleanup issue
    "status: completed",  # Shell already done
]


def _is_fatal_error(tool_name: str, error_content: str) -> bool:
    """
    Determine if a tool error is fatal (session-blocking) vs non-fatal (expected).

    Non-fatal errors include:
    - File not found during Read (exploration)
    - No matches in Grep/Glob
    - Expected command failures in Bash
    - Permission requests (waiting for user approval)

    Fatal errors include:
    - Permission denied (OS-level, not Claude approval)
    - Syntax errors
    - Rate limits
    - Explicit failures from Write/Edit (except permission requests)
    """
    if not error_content:
        return False

    error_lower = error_content.lower()

    # Check for non-fatal patterns FIRST (these override everything)
    # Permission requests from Claude Code are NOT fatal - they're waiting for user
    for pattern in NON_FATAL_ERROR_PATTERNS:
        if pattern.lower() in error_lower:
            return False

    # Always fatal: OS permission issues, rate limits, syntax errors
    fatal_patterns = [
        "permission denied",  # OS-level permission denied (not Claude approval)
        "rate limit",
        "syntax error",
        "authentication failed",
        "unauthorized",
        "forbidden",
        "access denied",
    ]
    for pattern in fatal_patterns:
        if pattern in error_lower:
            return True

    # Write/Edit errors are usually fatal (the operation failed)
    # But we already checked for non-fatal patterns above
    if tool_name in ("Write", "Edit"):
        return True

    # For non-fatal tools, most errors are expected during exploration
    if tool_name in NON_FATAL_ERROR_TOOLS:
        return False

    # Default: errors from unknown tools or unrecognized patterns are considered fatal
    # unless they're very short (often just status codes)
    if len(error_content) < 50:
        return False

    return True


@dataclass
class Message:
    """A conversation message."""
    role: str  # "user" or "assistant"
    content: str
    uuid: str
    timestamp: datetime
    tool_calls: list[ToolCall] = field(default_factory=list)
    thinking: Optional[str] = None


@dataclass
class Session:
    """A Claude Code session."""
    session_id: str
    project_path: str
    started_at: datetime
    last_activity: datetime
    messages: list[Message]
    tool_calls: list[ToolCall]
    todos: list[dict]
    status: str  # "in_progress", "completed", "stuck", "error"
    initial_prompt: str
    last_error: Optional[str] = None
    agent_sessions: list[str] = field(default_factory=list)

    @property
    def duration_minutes(self) -> float:
        """Duration from start to last activity in minutes."""
        delta = self.last_activity - self.started_at
        return delta.total_seconds() / 60

    @property
    def files_read(self) -> list[str]:
        """Files that were read during session."""
        files = []
        for tc in self.tool_calls:
            if tc.name == "Read" and "file_path" in tc.input:
                files.append(tc.input["file_path"])
        return list(set(files))

    @property
    def files_written(self) -> list[str]:
        """Files that were written/edited during session."""
        files = []
        for tc in self.tool_calls:
            if tc.name in ("Write", "Edit") and "file_path" in tc.input:
                files.append(tc.input["file_path"])
        return list(set(files))

    @property
    def bash_commands(self) -> list[str]:
        """Bash commands that were run."""
        commands = []
        for tc in self.tool_calls:
            if tc.name == "Bash" and "command" in tc.input:
                commands.append(tc.input["command"])
        return commands

    @property
    def pending_todos(self) -> list[dict]:
        """Todos that are not completed."""
        return [t for t in self.todos if t.get("status") != "completed"]

    @property
    def summary(self) -> str:
        """One-line summary of the session."""
        prompt_preview = self.initial_prompt[:80].replace("\n", " ")
        if len(self.initial_prompt) > 80:
            prompt_preview += "..."
        return f"[{self.status}] {prompt_preview}"


def _encode_project_path(path: str) -> str:
    """Encode a project path to match Claude's directory naming."""
    # Claude uses path with / replaced by -
    return path.replace("/", "-")


def _decode_project_path(encoded: str) -> str:
    """Decode an encoded project path back to real path."""
    # Remove leading dash and replace - with /
    if encoded.startswith("-"):
        encoded = encoded[1:]
    return "/" + encoded.replace("-", "/")


def _utcnow() -> datetime:
    """Get current UTC time as naive datetime."""
    from datetime import timezone
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _parse_timestamp(ts: str) -> Optional[datetime]:
    """Parse an ISO timestamp to naive UTC datetime.

    Returns None if timestamp is empty or invalid, rather than current time.
    This prevents records without timestamps from polluting activity tracking.
    """
    if not ts:
        return None
    try:
        # Parse the timestamp
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        # Strip timezone info - we work with naive UTC datetimes
        return dt.replace(tzinfo=None)
    except ValueError:
        return None


def _extract_text_from_content(content) -> str:
    """Extract text from message content (which may be a list or string)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        texts = []
        for block in content:
            if isinstance(block, dict):
                if block.get("type") == "text":
                    texts.append(block.get("text", ""))
                elif "text" in block:
                    texts.append(block["text"])
        return "\n".join(texts)
    return str(content)


def _extract_tool_calls_from_message(msg_data: dict) -> list[tuple[str, ToolCall]]:
    """Extract tool calls from an assistant message.

    Returns:
        List of (tool_use_id, ToolCall) tuples for linking with results.
    """
    tool_calls = []
    message = msg_data.get("message", {})
    content = message.get("content", [])
    msg_timestamp = _parse_timestamp(msg_data.get("timestamp", ""))

    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_use":
                tool_id = block.get("id", "")
                tc = ToolCall(
                    name=block.get("name", "unknown"),
                    input=block.get("input", {}),
                    timestamp=msg_timestamp,  # May be None
                )
                tool_calls.append((tool_id, tc))

    return tool_calls


def _extract_thinking_from_message(msg_data: dict) -> Optional[str]:
    """Extract thinking/reasoning from an assistant message."""
    message = msg_data.get("message", {})
    content = message.get("content", [])

    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "thinking":
                return block.get("thinking", "")

    return None


def list_project_sessions(project_path: str) -> list[str]:
    """List all session IDs for a given project path."""
    encoded = _encode_project_path(project_path)
    project_dir = PROJECTS_DIR / encoded

    if not project_dir.exists():
        return []

    sessions = []
    for f in project_dir.glob("*.jsonl"):
        # Skip agent sessions (they're linked from main sessions)
        if not f.name.startswith("agent-"):
            sessions.append(f.stem)

    return sessions


def list_all_projects() -> list[tuple[str, str]]:
    """List all projects with encoded and decoded paths."""
    if not PROJECTS_DIR.exists():
        return []

    projects = []
    for d in PROJECTS_DIR.iterdir():
        if d.is_dir() and d.name not in (".", ".."):
            decoded = _decode_project_path(d.name)
            projects.append((d.name, decoded))

    return projects


def load_session(project_path: str, session_id: str) -> Optional[Session]:
    """Load a session by project path and session ID."""
    encoded = _encode_project_path(project_path)
    session_file = PROJECTS_DIR / encoded / f"{session_id}.jsonl"

    if not session_file.exists():
        return None

    messages = []
    tool_calls = []
    todos = []
    initial_prompt = ""
    last_fatal_error = None  # Only fatal errors that block progress
    agent_sessions = []
    timestamps = []

    # Track tool calls by ID to link with results
    tool_calls_by_id = {}  # tool_use_id -> ToolCall

    # Parse the JSONL file
    with open(session_file, "r") as f:
        pending_tool_results = {}  # tool_use_id -> result

        for line in f:
            line = line.strip()
            if not line:
                continue

            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue

            msg_type = data.get("type")
            ts = _parse_timestamp(data.get("timestamp", ""))
            if ts is not None:
                timestamps.append(ts)

            if msg_type == "user":
                message = data.get("message", {})
                content = message.get("content", "")

                # Check if this is a tool result
                tool_result = data.get("toolUseResult")
                if tool_result:
                    # This is a tool result message
                    if isinstance(content, list):
                        for block in content:
                            if isinstance(block, dict) and block.get("type") == "tool_result":
                                tool_id = block.get("tool_use_id")
                                result_content = block.get("content", "")
                                is_error = block.get("is_error", False)
                                result_str = result_content if isinstance(result_content, str) else str(result_content)

                                pending_tool_results[tool_id] = {
                                    "result": result_str,
                                    "is_error": is_error,
                                }

                                # Link result back to tool call and check if fatal
                                if is_error and tool_id in tool_calls_by_id:
                                    tc = tool_calls_by_id[tool_id]
                                    tc.result = result_str
                                    tc.is_error = True

                                    # Only track fatal errors
                                    if _is_fatal_error(tc.name, result_str):
                                        last_fatal_error = result_str[:500]
                else:
                    # Regular user message
                    text = _extract_text_from_content(content)
                    if text and not initial_prompt:
                        initial_prompt = text

                    if text:
                        msg = Message(
                            role="user",
                            content=text,
                            uuid=data.get("uuid", ""),
                            timestamp=ts or _utcnow(),
                        )
                        messages.append(msg)

                # Update todos from user messages
                if "todos" in data and data["todos"]:
                    todos = data["todos"]

            elif msg_type == "assistant":
                message = data.get("message", {})
                content = message.get("content", [])

                # Extract tool calls (returns list of (id, ToolCall) tuples)
                msg_tool_calls_with_ids = _extract_tool_calls_from_message(data)

                # Store for linking with results, and extract just the ToolCalls
                msg_tool_calls = []
                for tool_id, tc in msg_tool_calls_with_ids:
                    tool_calls_by_id[tool_id] = tc
                    msg_tool_calls.append(tc)

                tool_calls.extend(msg_tool_calls)

                # Extract thinking
                thinking = _extract_thinking_from_message(data)

                # Extract text content
                text = _extract_text_from_content(content)

                if text or msg_tool_calls:
                    msg = Message(
                        role="assistant",
                        content=text,
                        uuid=data.get("uuid", ""),
                        timestamp=ts or _utcnow(),
                        tool_calls=msg_tool_calls,
                        thinking=thinking,
                    )
                    messages.append(msg)

                # Check for agent invocations (Task tool)
                for tc in msg_tool_calls:
                    if tc.name == "Task":
                        agent_id = tc.input.get("agentId") or tc.input.get("description", "")[:8]
                        if agent_id:
                            agent_sessions.append(agent_id)

    # Determine timestamps
    if not timestamps:
        started_at = _utcnow()
        last_activity = _utcnow()
        status = "empty"
    else:
        started_at = min(timestamps)
        last_activity = max(timestamps)

        # Check for stuck conditions (using UTC for comparison)
        minutes_since_activity = (_utcnow() - last_activity).total_seconds() / 60

        has_pending_todos = any(t.get("status") == "pending" for t in todos)
        has_in_progress_todos = any(t.get("status") == "in_progress" for t in todos)
        has_fatal_error = last_fatal_error is not None

        # Status determination priority:
        # 1. Fatal error = "error" (only if truly blocking)
        # 2. Has incomplete todos + stale = "stuck"
        # 3. Has incomplete todos + active = "in_progress"
        # 4. All todos done = "completed"
        # 5. No todos + very stale = "abandoned"
        # 6. Otherwise = "in_progress"

        if has_fatal_error and minutes_since_activity > 2:
            # Only mark as error if session stopped after the error
            # (not if it recovered and continued)
            status = "error"
        elif has_pending_todos or has_in_progress_todos:
            # Increased threshold: 15 minutes without activity = stuck
            # (was 5 minutes, which is too aggressive)
            if minutes_since_activity > 15:
                status = "stuck"
            else:
                status = "in_progress"
        else:
            # Check if it looks complete
            all_todos_done = todos and all(t.get("status") == "completed" for t in todos)
            if all_todos_done:
                status = "completed"
            # Increased threshold: 2 hours without activity = abandoned
            # (was 30 minutes, which is too aggressive)
            elif minutes_since_activity > 120:
                status = "abandoned"
            else:
                status = "in_progress"

    return Session(
        session_id=session_id,
        project_path=project_path,
        started_at=started_at,
        last_activity=last_activity,
        messages=messages,
        tool_calls=tool_calls,
        todos=todos,
        status=status,
        initial_prompt=initial_prompt,
        last_error=last_fatal_error,  # Only fatal errors
        agent_sessions=agent_sessions,
    )


def get_current_session_id() -> Optional[str]:
    """Get the current Claude Code session ID from environment, if available.

    Claude Code may set CLAUDE_SESSION_ID or similar env var.
    We also try to detect from the most recently modified session file.
    """
    # Try environment variable first
    session_id = os.environ.get(CURRENT_SESSION_ENV)
    if session_id:
        return session_id

    # Claude Code doesn't seem to set an env var, so we can't reliably
    # detect the current session. Return None.
    return None


def get_recent_sessions(
    project_path: Optional[str] = None,
    limit: int = 10,
    status_filter: Optional[list[str]] = None,
    exclude_current: bool = True,
) -> list[Session]:
    """
    Get recent sessions, optionally filtered by project and status.

    Args:
        project_path: Filter to specific project (None = all projects)
        limit: Maximum number of sessions to return
        status_filter: Only include sessions with these statuses
        exclude_current: Exclude the current session (if detectable)

    Returns:
        List of Sessions, sorted by last_activity descending
    """
    sessions = []
    current_session_id = get_current_session_id() if exclude_current else None

    if project_path:
        projects = [(project_path, project_path)]
    else:
        projects = [(decoded, decoded) for _, decoded in list_all_projects()]

    for _, proj_path in projects:
        session_ids = list_project_sessions(proj_path)
        for sid in session_ids:
            # Skip current session if we know it
            if current_session_id and sid == current_session_id:
                continue

            session = load_session(proj_path, sid)
            if session:
                if status_filter and session.status not in status_filter:
                    continue
                sessions.append(session)

    # Sort by last activity, most recent first
    sessions.sort(key=lambda s: s.last_activity, reverse=True)

    return sessions[:limit]


def find_stuck_sessions(project_path: Optional[str] = None) -> list[Session]:
    """Find sessions that appear stuck or errored."""
    return get_recent_sessions(
        project_path=project_path,
        limit=50,
        status_filter=["stuck", "error", "abandoned"],
    )


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Explore Claude Code sessions")
    parser.add_argument("--project", "-p", help="Project path to filter")
    parser.add_argument("--list", "-l", action="store_true", help="List sessions")
    parser.add_argument("--stuck", "-s", action="store_true", help="Show only stuck/errored sessions")
    parser.add_argument("--session", help="Show details for a specific session ID")
    parser.add_argument("--limit", "-n", type=int, default=10, help="Number of sessions to show")

    args = parser.parse_args()

    if args.session:
        # Show session details
        project = args.project or str(Path.cwd())
        session = load_session(project, args.session)
        if session:
            print(f"Session: {session.session_id}")
            print(f"Project: {session.project_path}")
            print(f"Status: {session.status}")
            print(f"Started: {session.started_at}")
            print(f"Last Activity: {session.last_activity}")
            print(f"Duration: {session.duration_minutes:.1f} minutes")
            print(f"\nInitial Prompt:\n{session.initial_prompt[:500]}")
            print(f"\nTool Calls: {len(session.tool_calls)}")
            print(f"Messages: {len(session.messages)}")
            print(f"Files Read: {len(session.files_read)}")
            print(f"Files Written: {len(session.files_written)}")
            if session.pending_todos:
                print(f"\nPending Todos:")
                for t in session.pending_todos:
                    print(f"  - [{t.get('status')}] {t.get('content')}")
            if session.last_error:
                print(f"\nLast Error:\n{session.last_error}")
        else:
            print(f"Session not found: {args.session}")

    elif args.list or args.stuck:
        # List sessions
        project = args.project or str(Path.cwd())

        if args.stuck:
            sessions = find_stuck_sessions(project)
            print(f"Stuck/Errored Sessions (project: {project}):\n")
        else:
            sessions = get_recent_sessions(project, limit=args.limit)
            print(f"Recent Sessions (project: {project}):\n")

        for s in sessions:
            age_mins = (_utcnow() - s.last_activity).total_seconds() / 60
            if age_mins < 60:
                age_str = f"{int(age_mins)}m ago"
            elif age_mins < 1440:
                age_str = f"{int(age_mins/60)}h ago"
            else:
                age_str = f"{int(age_mins/1440)}d ago"

            print(f"  {s.session_id[:8]}  [{s.status:10}]  {age_str:8}  {s.summary[:60]}")

    else:
        # Default: show projects
        print("Claude Code Projects:\n")
        for encoded, decoded in list_all_projects():
            sessions = list_project_sessions(decoded)
            print(f"  {decoded}: {len(sessions)} sessions")

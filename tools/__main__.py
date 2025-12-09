"""
Tool dispatcher CLI with filesystem logging.

Usage:
    uv run python -m tools <tool_name> '<json_args>'
    uv run python -m tools web_search '{"objective": "Claude API docs"}'

    # Or pipe JSON via stdin:
    echo '{"objective": "test"}' | uv run python -m tools web_search

    # With explicit run ID:
    PILOT_RUN_ID=20250126_143022_abc uv run python -m tools web_search '{...}'

All invocations are logged to logs/tools/<tool_name>/<timestamp>_<id>.json
Logs include run_id if set, linking tool calls to their parent run.
"""

import importlib
import json
import os
import sys
import uuid
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv


def generate_invocation_id() -> str:
    """Generate unique ID: YYYYMMDD_HHMMSS_shortuid"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    short_id = uuid.uuid4().hex[:8]
    return f"{timestamp}_{short_id}"


def get_run_id() -> str | None:
    """Get current run ID from environment, if any."""
    return os.environ.get("PILOT_RUN_ID")


def get_log_path(tool_name: str, invocation_id: str) -> Path:
    """Get path for log file."""
    log_dir = Path("logs/tools") / tool_name
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir / f"{invocation_id}.json"


def run_tool(tool_name: str, args: dict) -> dict:
    """
    Run a tool and log the invocation.

    Args:
        tool_name: Name of tool module in tools/
        args: Dict of arguments to pass to tool function

    Returns:
        Tool result dict
    """
    invocation_id = generate_invocation_id()
    log_path = get_log_path(tool_name, invocation_id)

    run_id = get_run_id()

    record = {
        "id": invocation_id,
        "run_id": run_id,  # Links to parent run, if any
        "tool": tool_name,
        "started": datetime.now().isoformat(),
        "input": args,
    }

    try:
        # Import tool module
        module = importlib.import_module(f"tools.{tool_name}")

        # Get function (convention: function name matches module name)
        func = getattr(module, tool_name)

        # Execute
        result = func(**args)

        record["output"] = result
        record["success"] = True

    except ImportError as e:
        result = {"error": f"Tool not found: {tool_name}", "details": str(e)}
        record["output"] = result
        record["success"] = False

    except AttributeError as e:
        result = {"error": f"Tool function not found: {tool_name}", "details": str(e)}
        record["output"] = result
        record["success"] = False

    except TypeError as e:
        result = {"error": f"Invalid arguments for {tool_name}", "details": str(e)}
        record["output"] = result
        record["success"] = False

    except Exception as e:
        result = {"error": f"Tool execution failed: {type(e).__name__}", "details": str(e)}
        record["output"] = result
        record["success"] = False

    # Record completion time and duration
    completed = datetime.now()
    record["completed"] = completed.isoformat()
    started = datetime.fromisoformat(record["started"])
    record["duration_ms"] = int((completed - started).total_seconds() * 1000)

    # Write log
    log_path.write_text(json.dumps(record, indent=2, default=str))

    return result


def list_tools() -> list[str]:
    """List available tools."""
    tools_dir = Path(__file__).parent
    tools = []
    for f in tools_dir.glob("*.py"):
        if f.name.startswith("_"):
            continue
        tools.append(f.stem)
    return sorted(tools)


def main():
    load_dotenv()

    if len(sys.argv) < 2:
        print("Usage: uv run python -m tools <tool_name> [json_args]")
        print("\nAvailable tools:")
        for tool in list_tools():
            print(f"  - {tool}")
        sys.exit(1)

    tool_name = sys.argv[1]

    if tool_name in ("--list", "-l"):
        for tool in list_tools():
            print(tool)
        sys.exit(0)

    # Get args from argv or stdin
    if len(sys.argv) > 2:
        args_str = sys.argv[2]
    elif not sys.stdin.isatty():
        args_str = sys.stdin.read().strip()
    else:
        args_str = "{}"

    try:
        args = json.loads(args_str)
    except json.JSONDecodeError as e:
        print(json.dumps({"error": "Invalid JSON args", "details": str(e)}))
        sys.exit(1)

    result = run_tool(tool_name, args)
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()

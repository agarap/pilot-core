"""Logging utilities for agent and tool interactions."""

import json
import os
from datetime import datetime
from pathlib import Path
from uuid import uuid4


def _ensure_dir(path: Path) -> None:
    """Ensure directory exists."""
    path.mkdir(parents=True, exist_ok=True)


def _write_log(category: str, name: str, data: dict) -> str:
    """Write a log entry and return the log path."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_id = str(uuid4())[:8]

    log_dir = Path("logs") / category / name
    _ensure_dir(log_dir)

    filename = f"{timestamp}_{log_id}.json"
    log_path = log_dir / filename

    log_entry = {
        "id": f"{timestamp}_{log_id}",
        "timestamp": datetime.now().isoformat(),
        **data
    }

    with open(log_path, "w") as f:
        json.dump(log_entry, f, indent=2, default=str)

    return str(log_path)


def log_agent(agent: str, input: dict, output: dict, context: dict = None) -> str:
    """
    Log an agent interaction.

    Args:
        agent: Name of the agent
        input: Input to the agent
        output: Output from the agent
        context: Optional context information

    Returns:
        Path to the log file
    """
    data = {
        "agent": agent,
        "input": input,
        "output": output,
    }
    if context:
        data["context"] = context

    return _write_log("agents", agent, data)


def log_tool(tool: str, input: dict, output: dict, context: dict = None) -> str:
    """
    Log a tool invocation.

    Args:
        tool: Name of the tool
        input: Input to the tool
        output: Output from the tool
        context: Optional context information

    Returns:
        Path to the log file
    """
    data = {
        "tool": tool,
        "input": input,
        "output": output,
    }
    if context:
        data["context"] = context

    return _write_log("tools", tool, data)

"""Context builder for SDK-based agents.

This module builds context for agents running via the Claude Agent SDK harness.
Note: Pilot (top-level) uses CLAUDE.md natively via Claude Code.
"""

import json
import subprocess
from pathlib import Path
from typing import Optional

import yaml

from pilot_core.queries import execute_query, QueryError


def load_system_context() -> str:
    """Load system context from CLAUDE.md.

    For SDK-based agents that need system context.
    Note: Pilot already has CLAUDE.md loaded natively by Claude Code.
    """
    claude_path = Path("CLAUDE.md")
    if not claude_path.exists():
        return ""

    return claude_path.read_text()


def load_rules_for_agent(agent_name: str) -> str:
    """Load rules applicable to an agent using DuckDB."""
    index_path = Path("data/index.json")
    if not index_path.exists():
        return ""

    def normalize_priority(p):
        """Convert priority to integer for sorting. Handle string priorities."""
        if isinstance(p, int):
            return p
        if isinstance(p, str):
            priority_map = {"critical": 100, "high": 90, "medium": 50, "low": 10}
            return priority_map.get(p.lower(), 50)
        return 50

    try:
        # Use centralized query from lib/queries
        rows = execute_query('rules_for_agent', {'agent_name': agent_name})
        # Template returns 'rule' column, normalize priorities and convert to tuples
        result = [
            (row['name'], normalize_priority(row['priority']), row['rule'])
            for row in rows
        ]
        result.sort(key=lambda x: x[1], reverse=True)
    except QueryError:
        # Fallback to direct JSON parsing if query fails
        with open(index_path) as f:
            index = json.load(f)

        rules = []
        for item in index.get("items", []):
            if item.get("type") != "rule":
                continue
            applies_to = item.get("applies_to", ["*"])
            if agent_name in applies_to or "*" in applies_to:
                priority = normalize_priority(item.get("priority", 50))
                rules.append((item["name"], priority, item.get("rule_text", "")))

        rules.sort(key=lambda x: x[1], reverse=True)
        result = rules

    if not result:
        return ""

    rules_text = "## Active Rules\n\n"
    for name, priority, rule_text in result:
        rules_text += f"### {name} (priority: {priority})\n{rule_text}\n\n"

    return rules_text


def load_agent_prompt(agent_name: str) -> str:
    """Load the agent's prompt from its YAML file.

    Agents are stored in agents/*.yaml with a 'prompt' field.
    """
    agent_path = Path("agents") / f"{agent_name}.yaml"
    if not agent_path.exists():
        return ""

    with open(agent_path) as f:
        data = yaml.safe_load(f)

    return data.get("prompt", "")


def load_agent_config(agent_name: str) -> dict:
    """Load full agent configuration from YAML.

    Returns the complete agent definition including model, tools, etc.
    """
    agent_path = Path("agents") / f"{agent_name}.yaml"
    if not agent_path.exists():
        return {}

    with open(agent_path) as f:
        return yaml.safe_load(f) or {}


def load_project_context(project_id: str) -> str:
    """Load project-specific context from feature_list.json and progress.txt.

    Extracts useful context including:
    - Project description
    - Current feature status (next pending feature)
    - Recent progress notes (last session from progress.txt)

    Args:
        project_id: The project directory name under projects/

    Returns:
        Formatted context string, or empty string if project not found.
    """
    project_dir = Path("projects") / project_id
    if not project_dir.exists():
        return ""

    context_parts = []

    # 1. Load from feature_list.json
    feature_list_path = project_dir / "feature_list.json"
    if feature_list_path.exists():
        try:
            with open(feature_list_path) as f:
                data = json.load(f)

            # Project info
            if data.get("project"):
                context_parts.append(f"**Project**: {data['project']}")
            if data.get("description"):
                context_parts.append(f"**Description**: {data['description']}")

            # Feature status
            features = data.get("features", [])
            if features:
                passing = [f for f in features if f.get("passes")]
                pending = [f for f in features if not f.get("passes")]
                context_parts.append(
                    f"**Progress**: {len(passing)}/{len(features)} features complete"
                )

                # Show next pending feature
                if pending:
                    next_feat = pending[0]
                    context_parts.append(
                        f"**Next feature**: {next_feat.get('id')} - {next_feat.get('name')}"
                    )
                    if next_feat.get("description"):
                        context_parts.append(f"  {next_feat['description']}")

        except (json.JSONDecodeError, IOError):
            pass

    # 2. Load recent progress from progress.txt (first 40 lines = ~last session)
    progress_path = project_dir / "progress.txt"
    if progress_path.exists():
        try:
            with open(progress_path) as f:
                lines = f.readlines()[:40]

            if lines:
                # Find the first session header to get just the latest session
                progress_text = "".join(lines).strip()
                if progress_text:
                    context_parts.append("\n**Recent Progress**:\n" + progress_text)
        except IOError:
            pass

    if not context_parts:
        return ""

    return "\n".join(context_parts)


def get_current_branch() -> str:
    """Get the current git branch name."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return ""


def get_task_tool_ban_warning() -> str:
    """Return the Task tool ban warning to inject into agent context.

    This warning is injected into every agent's system prompt to prevent
    use of Claude Code's built-in Task tool, which bypasses pilot's
    observability and review processes.
    """
    return """# CRITICAL: Task Tool is BANNED

**DO NOT use Claude Code's built-in Task tool.** This is an absolute rule.

The Task tool launches subagents that:
- Don't follow pilot's rules and guidelines
- Break observability (not logged to logs/agents/)
- Bypass the git-reviewer process
- Cannot be tracked or audited

## Banned subagent_types

The Task tool's `subagent_type` parameter launches these BANNED agents:
- `general-purpose`
- `Explore`
- `Plan`
- `code-architect-reviewer`

**ALL of these are BANNED.** Do not invoke the Task tool with any subagent_type.

## Correct Approach

Use `lib.invoke` to delegate to proper subagents:

```bash
uv run python -m lib.invoke builder "task description"
uv run python -m lib.invoke web-researcher "research question"
uv run python -m lib.invoke verifier "verification task"
```

These invocations:
- Are logged to logs/agents/ for observability
- Follow pilot's rules and guidelines
- Integrate with the run tracking system
- Produce auditable outputs

## Violations

If you use the Task tool, your work will not be properly tracked and may need
to be redone. Always use lib.invoke for delegation."""


def build_context(agent_name: str, project_id: str = None) -> str:
    """
    Build complete context for an SDK-based agent.

    Combines:
    1. System context from CLAUDE.md
    2. Rules applicable to this agent (from DuckDB query)
    3. Task tool ban warning (critical - injected before agent instructions)
    4. Agent's own prompt (from agents/*.yaml)
    5. Project context (if project_id provided)

    Args:
        agent_name: Name of the agent to build context for
        project_id: Optional project identifier

    Returns:
        Complete context string for the agent
    """
    parts = []

    # 1. System context (for SDK agents that need it)
    system = load_system_context()
    if system:
        parts.append("# System Context\n\n" + system)

    # 2. Rules
    rules = load_rules_for_agent(agent_name)
    if rules:
        parts.append(rules)

    # 3. Task tool ban warning (before agent instructions)
    parts.append(get_task_tool_ban_warning())

    # 4. Agent prompt
    prompt = load_agent_prompt(agent_name)
    if prompt:
        parts.append("# Agent Instructions\n\n" + prompt)

    # 5. Project context
    if project_id:
        project = load_project_context(project_id)
        if project:
            parts.append("# Project Context\n\n" + project)

    return "\n\n---\n\n".join(parts)

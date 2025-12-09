"""
tool: prompt_analyzer
description: Analyze agent prompts for size and code enforcement coverage
parameters:
  format: Output format (json, summary, detailed). Default: summary
  agent: Analyze specific agent. Default: all agents
returns: Prompt analysis with line counts, token estimates, and rule enforcement mapping
"""

import json
import re
import sys
from pathlib import Path

import yaml


def load_enforcement_config() -> dict:
    """Load system/enforcement.yaml configuration."""
    config_path = Path(__file__).parent.parent / "system" / "enforcement.yaml"
    if not config_path.exists():
        return {}
    with open(config_path) as f:
        return yaml.safe_load(f)


def estimate_tokens(text: str) -> int:
    """
    Estimate token count for text.

    Rule of thumb: ~4 characters per token for English text.
    This is a rough estimate; actual tokenization varies by model.
    """
    return len(text) // 4


def extract_sections(prompt: str) -> list[dict]:
    """
    Extract sections from a prompt based on markdown headers.

    Returns list of {name, lines, tokens, level} dicts.
    """
    sections = []
    current_section = {"name": "_preamble", "lines": [], "level": 0}

    for line in prompt.split("\n"):
        # Match markdown headers (## Section Name)
        header_match = re.match(r'^(#{1,4})\s+(.+)$', line)
        if header_match:
            # Save previous section if it has content
            if current_section["lines"]:
                section_text = "\n".join(current_section["lines"])
                sections.append({
                    "name": current_section["name"],
                    "level": current_section["level"],
                    "lines": len(current_section["lines"]),
                    "tokens": estimate_tokens(section_text),
                })

            # Start new section
            current_section = {
                "name": header_match.group(2).strip(),
                "level": len(header_match.group(1)),
                "lines": [line],
            }
        else:
            current_section["lines"].append(line)

    # Don't forget the last section
    if current_section["lines"]:
        section_text = "\n".join(current_section["lines"])
        sections.append({
            "name": current_section["name"],
            "level": current_section["level"],
            "lines": len(current_section["lines"]),
            "tokens": estimate_tokens(section_text),
        })

    return sections


def identify_rules_in_prompt(prompt: str) -> list[str]:
    """
    Identify rules/policies mentioned in a prompt.

    Looks for common rule patterns and keywords.
    """
    rules = []

    # Patterns that indicate rules
    rule_patterns = [
        r"(?:MUST|NEVER|ALWAYS|CRITICAL|REQUIRED|PROHIBITED)\s*:?\s*(.+)",
        r"(?:DO NOT|CANNOT|SHOULD NOT)\s+(.+)",
        r"Rule:\s*(.+)",
        r"\*\*([^*]+)\*\*\s*-\s*",  # Bold text followed by dash
    ]

    # Keywords that indicate enforcement topics
    enforcement_keywords = [
        "git-reviewer", "pre-commit", "commit", "review",
        "web access", "http", "requests", "scraping",
        "Task tool", "subagent", "delegation",
        "feature_tracker", "feature_list", "one feature",
        "worktree", "parallel",
        "validation", "YAML",
    ]

    lines = prompt.split("\n")
    for line in lines:
        # Check patterns
        for pattern in rule_patterns:
            match = re.search(pattern, line, re.IGNORECASE)
            if match:
                # Get the full line for context
                rule_text = line.strip()
                if rule_text and rule_text not in rules:
                    rules.append(rule_text)
                break

        # Check keywords (for lines that aren't caught by patterns)
        for keyword in enforcement_keywords:
            if keyword.lower() in line.lower():
                rule_text = line.strip()
                if rule_text and rule_text not in rules and len(rule_text) < 200:
                    rules.append(rule_text)
                break

    return rules


def match_rules_to_enforcement(rules: list[str], enforcement: dict) -> dict:
    """
    Match identified prompt rules to enforcement mechanisms.

    Returns:
        {
            "code_enforced": [{"rule": str, "mechanism": str, "status": str}],
            "prompt_only": [str]
        }
    """
    code_enforced = []
    prompt_only = []

    # Build lookup of enforcement mechanisms
    mechanisms = {}

    for section in ["pre_commit", "runtime", "prompt_only"]:
        for item in enforcement.get(section, []):
            mechanisms[item["id"]] = {
                "description": item.get("description", ""),
                "mechanism": item.get("mechanism") or item.get("target_mechanism", ""),
                "status": item.get("status", "unknown"),
                "section": section,
            }

    # Keywords that map to enforcement IDs
    keyword_to_enforcement = {
        "git-reviewer": "git-reviewer-approval",
        "review": "git-reviewer-approval",
        "commit": "git-reviewer-approval",
        "logs/": "validation-no-logs",
        "workspaces/": "validation-no-logs",
        "yaml format": "validation-yaml-format",
        "agent yaml": "validation-agent-yaml",
        "web access": "web-access-policy",
        "http": "web-access-policy",
        "requests": "web-access-policy",
        "scraping": "web-access-policy",
        "Task tool": "task-tool-ban",
        "built-in Task": "task-tool-ban",
        "delegation": "mandatory-delegation",
        "worktree": "worktree-isolation",
        "feature_tracker": "worktree-isolation",
    }

    for rule in rules:
        rule_lower = rule.lower()
        matched = False

        for keyword, enforcement_id in keyword_to_enforcement.items():
            if keyword.lower() in rule_lower and enforcement_id in mechanisms:
                mech = mechanisms[enforcement_id]
                code_enforced.append({
                    "rule": rule[:100] + "..." if len(rule) > 100 else rule,
                    "enforcement_id": enforcement_id,
                    "mechanism": mech["mechanism"],
                    "status": mech["status"],
                })
                matched = True
                break

        if not matched:
            prompt_only.append(rule[:100] + "..." if len(rule) > 100 else rule)

    return {
        "code_enforced": code_enforced,
        "prompt_only": prompt_only,
    }


def analyze_agent(agent_path: Path, enforcement: dict) -> dict:
    """Analyze a single agent YAML file."""
    with open(agent_path) as f:
        agent_data = yaml.safe_load(f)

    prompt = agent_data.get("prompt", "")
    prompt_lines = prompt.split("\n") if prompt else []

    # Basic metrics
    metrics = {
        "name": agent_data.get("name", agent_path.stem),
        "path": str(agent_path),
        "model": agent_data.get("model", "unknown"),
        "tools_count": len(agent_data.get("tools", [])),
        "total_lines": len(prompt_lines),
        "total_tokens": estimate_tokens(prompt),
        "non_empty_lines": len([l for l in prompt_lines if l.strip()]),
    }

    # Section analysis
    metrics["sections"] = extract_sections(prompt)
    metrics["section_count"] = len(metrics["sections"])

    # Find largest sections
    if metrics["sections"]:
        sorted_sections = sorted(metrics["sections"], key=lambda s: s["lines"], reverse=True)
        metrics["largest_sections"] = sorted_sections[:5]
    else:
        metrics["largest_sections"] = []

    # Rule analysis
    rules = identify_rules_in_prompt(prompt)
    metrics["rules_mentioned"] = len(rules)

    # Map to enforcement
    rule_mapping = match_rules_to_enforcement(rules, enforcement)
    metrics["code_enforced_rules"] = rule_mapping["code_enforced"]
    metrics["prompt_only_rules"] = rule_mapping["prompt_only"]
    metrics["code_enforced_count"] = len(rule_mapping["code_enforced"])
    metrics["prompt_only_count"] = len(rule_mapping["prompt_only"])

    # Calculate potential reduction
    # Each code-enforced rule could be shortened to a single-line reference
    # Estimate: verbose explanation = ~10 lines, reference = ~1 line
    estimated_reduction = metrics["code_enforced_count"] * 9
    metrics["estimated_reduction_lines"] = min(estimated_reduction, metrics["total_lines"] // 2)
    metrics["reduction_potential_pct"] = round(
        (metrics["estimated_reduction_lines"] / max(metrics["total_lines"], 1)) * 100
    )

    return metrics


def analyze_all_agents(agent_name: str | None = None) -> list[dict]:
    """Analyze all agents or a specific agent."""
    agents_dir = Path(__file__).parent.parent / "agents"
    enforcement = load_enforcement_config()

    results = []

    if agent_name:
        # Specific agent
        agent_path = agents_dir / f"{agent_name}.yaml"
        if agent_path.exists():
            results.append(analyze_agent(agent_path, enforcement))
        else:
            return [{"error": f"Agent not found: {agent_name}"}]
    else:
        # All agents
        for agent_file in sorted(agents_dir.glob("*.yaml")):
            results.append(analyze_agent(agent_file, enforcement))

    return results


def format_summary(results: list[dict]) -> str:
    """Format results as human-readable summary."""
    if not results:
        return "No agents found."

    if "error" in results[0]:
        return f"Error: {results[0]['error']}"

    lines = [
        "# Prompt Analysis Report",
        "",
        "## Overview",
        "",
        f"| Agent | Lines | Tokens | Sections | Code-Enforced | Prompt-Only | Reduction % |",
        f"|-------|-------|--------|----------|---------------|-------------|-------------|",
    ]

    total_lines = 0
    total_tokens = 0
    total_code_enforced = 0
    total_prompt_only = 0

    for r in results:
        lines.append(
            f"| {r['name']} | {r['total_lines']} | {r['total_tokens']} | "
            f"{r['section_count']} | {r['code_enforced_count']} | "
            f"{r['prompt_only_count']} | {r['reduction_potential_pct']}% |"
        )
        total_lines += r['total_lines']
        total_tokens += r['total_tokens']
        total_code_enforced += r['code_enforced_count']
        total_prompt_only += r['prompt_only_count']

    lines.append(
        f"| **TOTAL** | **{total_lines}** | **{total_tokens}** | "
        f"- | **{total_code_enforced}** | **{total_prompt_only}** | - |"
    )

    lines.extend([
        "",
        "## Largest Agents (by line count)",
        "",
    ])

    sorted_by_size = sorted(results, key=lambda r: r['total_lines'], reverse=True)
    for i, r in enumerate(sorted_by_size[:5], 1):
        lines.append(f"{i}. **{r['name']}**: {r['total_lines']} lines, {r['total_tokens']} tokens")

    lines.extend([
        "",
        "## Code-Enforced Rules (can be shortened)",
        "",
        "These rules have code enforcement - prompt can reference instead of explain:",
        "",
    ])

    # Collect all code-enforced rules
    all_code_enforced = []
    for r in results:
        for rule in r.get("code_enforced_rules", []):
            all_code_enforced.append({
                "agent": r["name"],
                **rule
            })

    # Group by enforcement ID
    by_enforcement = {}
    for rule in all_code_enforced:
        eid = rule.get("enforcement_id", "unknown")
        if eid not in by_enforcement:
            by_enforcement[eid] = {
                "mechanism": rule.get("mechanism", ""),
                "status": rule.get("status", ""),
                "agents": set(),
            }
        by_enforcement[eid]["agents"].add(rule["agent"])

    for eid, info in sorted(by_enforcement.items()):
        agents_str = ", ".join(sorted(info["agents"]))
        lines.append(f"- **{eid}** [{info['status']}]")
        lines.append(f"  - Mechanism: {info['mechanism']}")
        lines.append(f"  - Agents: {agents_str}")
        lines.append("")

    return "\n".join(lines)


def format_detailed(results: list[dict]) -> str:
    """Format results with full detail for each agent."""
    if not results:
        return "No agents found."

    lines = ["# Detailed Prompt Analysis\n"]

    for r in results:
        lines.extend([
            f"## {r['name']}",
            "",
            f"- **Path**: {r['path']}",
            f"- **Model**: {r['model']}",
            f"- **Tools**: {r['tools_count']}",
            f"- **Total Lines**: {r['total_lines']}",
            f"- **Estimated Tokens**: {r['total_tokens']}",
            f"- **Sections**: {r['section_count']}",
            "",
            "### Largest Sections",
            "",
        ])

        for section in r.get("largest_sections", [])[:5]:
            lines.append(f"- **{section['name']}**: {section['lines']} lines, {section['tokens']} tokens")

        lines.extend([
            "",
            f"### Code-Enforced Rules ({r['code_enforced_count']})",
            "",
        ])

        for rule in r.get("code_enforced_rules", []):
            lines.append(f"- [{rule['status']}] {rule['enforcement_id']}: {rule['mechanism']}")

        lines.extend([
            "",
            f"### Prompt-Only Rules ({r['prompt_only_count']})",
            "",
        ])

        for rule in r.get("prompt_only_rules", [])[:10]:  # Limit to 10
            lines.append(f"- {rule}")

        if r['prompt_only_count'] > 10:
            lines.append(f"- ... and {r['prompt_only_count'] - 10} more")

        lines.extend([
            "",
            f"### Reduction Potential",
            "",
            f"- Estimated lines reducible: {r['estimated_reduction_lines']}",
            f"- Reduction potential: **{r['reduction_potential_pct']}%**",
            "",
            "---",
            "",
        ])

    return "\n".join(lines)


def prompt_analyzer(format: str = "summary", agent: str | None = None) -> dict | str:
    """
    Analyze agent prompts for size and code enforcement coverage.

    Args:
        format: Output format - 'json', 'summary', or 'detailed'
        agent: Optional specific agent name to analyze

    Returns:
        Analysis results as dict (json) or formatted string
    """
    results = analyze_all_agents(agent)

    if format == "json":
        return {"agents": results}
    elif format == "detailed":
        return format_detailed(results)
    else:
        return format_summary(results)


if __name__ == "__main__":
    # Parse CLI args
    fmt = "summary"
    agent_name = None

    args = sys.argv[1:]

    # Handle JSON input from tools dispatcher
    if args and args[0].startswith("{"):
        try:
            params = json.loads(args[0])
            fmt = params.get("format", "summary")
            agent_name = params.get("agent")
        except json.JSONDecodeError:
            pass
    else:
        # Handle direct CLI args
        if "--json" in args:
            fmt = "json"
        elif "--detailed" in args:
            fmt = "detailed"

        # Check for agent name
        for arg in args:
            if not arg.startswith("--"):
                agent_name = arg
                break

    result = prompt_analyzer(format=fmt, agent=agent_name)

    if isinstance(result, dict):
        print(json.dumps(result, indent=2, default=str))
    else:
        print(result)

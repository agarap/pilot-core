"""
tool: audit_rules
description: Audit rules for complete applies_to (when) coverage across agents
parameters:
  verbose: Show detailed output per rule (default: false)
  json_output: Return raw JSON structure (default: true)
returns: Audit report with coverage gaps and recommendations
"""

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml


# Rules that SHOULD apply to all agents (universal rules)
CRITICAL_UNIVERSAL_RULES = [
    "git-review-required",
    "web-access-policy",
    "context-first",
    "minimalism",
]


def audit_rules(
    verbose: bool = False,
    json_output: bool = True,
) -> dict[str, Any]:
    """
    Audit all rules in system/rules/*.yaml for complete agent coverage.

    Checks:
    1. Rules have a 'when' field specifying which agents they apply to
    2. Rules either use '*' (all agents) or list specific agents
    3. Critical universal rules apply to all agents
    4. No references to non-existent agents

    Returns audit report with gaps and recommendations.
    """
    # Load all agent names
    agents_dir = Path("agents")
    agents = []
    if agents_dir.exists():
        for agent_file in agents_dir.glob("*.yaml"):
            try:
                with open(agent_file, "r") as f:
                    agent_data = yaml.safe_load(f)
                    if agent_data and "name" in agent_data:
                        agents.append(agent_data["name"])
            except Exception:
                # Skip malformed agent files
                pass

    # Always include 'pilot' even if not in agents/ (it's the orchestrator)
    if "pilot" not in agents:
        agents.append("pilot")

    agents = sorted(agents)

    # Load all rules
    rules_dir = Path("system/rules")
    rules_data = {}

    if not rules_dir.exists():
        return {"error": f"Rules directory not found: {rules_dir}"}

    for rule_file in rules_dir.glob("*.yaml"):
        try:
            with open(rule_file, "r") as f:
                rule = yaml.safe_load(f)
                if rule and "name" in rule:
                    rules_data[rule["name"]] = {
                        "file": str(rule_file),
                        "description": rule.get("description", ""),
                        "priority": rule.get("priority", 50),
                        "when": rule.get("when", []),
                    }
        except Exception as e:
            rules_data[rule_file.stem] = {
                "file": str(rule_file),
                "error": f"Failed to parse: {e}",
            }

    # Analyze each rule
    rule_analysis = {}
    universal_count = 0
    partial_count = 0
    no_coverage_count = 0

    for rule_name, rule_info in rules_data.items():
        if "error" in rule_info:
            rule_analysis[rule_name] = {
                "error": rule_info["error"],
                "coverage": "error",
            }
            continue

        when_field = rule_info.get("when", [])

        # Check for wildcard
        if when_field == "*" or (isinstance(when_field, list) and "*" in when_field):
            rule_analysis[rule_name] = {
                "applies_to": ["*"],
                "coverage": "universal",
                "missing_agents": [],
                "unknown_agents": [],
            }
            universal_count += 1
            continue

        # Extract agent names from when field
        # Format: [{'agent': 'pilot'}, {'agent': 'builder'}]
        applies_to = []
        unknown_agents = []

        if isinstance(when_field, list):
            for entry in when_field:
                if isinstance(entry, dict) and "agent" in entry:
                    agent_name = entry["agent"]
                    applies_to.append(agent_name)
                    if agent_name not in agents and agent_name != "*":
                        unknown_agents.append(agent_name)
                elif isinstance(entry, str):
                    # Simple string format
                    applies_to.append(entry)
                    if entry not in agents and entry != "*":
                        unknown_agents.append(entry)

        # Determine coverage
        if not applies_to:
            coverage = "none"
            no_coverage_count += 1
            missing_agents = agents
        elif set(applies_to) >= set(agents):
            coverage = "universal"
            universal_count += 1
            missing_agents = []
        else:
            coverage = "partial"
            partial_count += 1
            missing_agents = [a for a in agents if a not in applies_to]

        rule_analysis[rule_name] = {
            "applies_to": sorted(applies_to),
            "coverage": coverage,
            "missing_agents": sorted(missing_agents),
            "unknown_agents": sorted(unknown_agents),
        }

    # Generate recommendations
    recommendations = []

    for rule_name, analysis in rule_analysis.items():
        if analysis.get("error"):
            recommendations.append(
                f"Rule '{rule_name}' has parse error - fix YAML syntax"
            )
            continue

        if analysis["unknown_agents"]:
            recommendations.append(
                f"Rule '{rule_name}' references unknown agents: {analysis['unknown_agents']}"
            )

        if rule_name in CRITICAL_UNIVERSAL_RULES:
            if analysis["coverage"] != "universal":
                if analysis["missing_agents"]:
                    recommendations.append(
                        f"CRITICAL: Rule '{rule_name}' should apply to all agents "
                        f"(missing: {analysis['missing_agents']}) - add '*' to when field"
                    )
                else:
                    recommendations.append(
                        f"CRITICAL: Rule '{rule_name}' should apply to all agents - add '*' to when field"
                    )

        if analysis["coverage"] == "none":
            recommendations.append(
                f"Rule '{rule_name}' has no 'when' specification - add agents or '*'"
            )

    # Build result
    result = {
        "audit_time": datetime.now().isoformat(),
        "total_rules": len(rules_data),
        "total_agents": len(agents),
        "agents": agents,
        "rules": rule_analysis,
        "summary": {
            "universal_rules": universal_count,
            "partial_coverage_rules": partial_count,
            "no_coverage_rules": no_coverage_count,
        },
        "recommendations": recommendations,
    }

    return result


def format_verbose_output(result: dict[str, Any]) -> str:
    """Format result for verbose human-readable output."""
    lines = []
    lines.append("=" * 60)
    lines.append("RULES AUDIT REPORT")
    lines.append("=" * 60)
    lines.append(f"Audit Time: {result['audit_time']}")
    lines.append(f"Total Rules: {result['total_rules']}")
    lines.append(f"Total Agents: {result['total_agents']}")
    lines.append(f"Agents: {', '.join(result['agents'])}")
    lines.append("")

    # Summary
    summary = result["summary"]
    lines.append("SUMMARY")
    lines.append("-" * 40)
    lines.append(f"  Universal coverage: {summary['universal_rules']}")
    lines.append(f"  Partial coverage:   {summary['partial_coverage_rules']}")
    lines.append(f"  No coverage:        {summary['no_coverage_rules']}")
    lines.append("")

    # Rules detail
    lines.append("RULES DETAIL")
    lines.append("-" * 40)

    for rule_name, analysis in sorted(result["rules"].items()):
        coverage = analysis.get("coverage", "unknown")
        icon = {"universal": "✓", "partial": "○", "none": "✗", "error": "!"}
        lines.append(f"\n{icon.get(coverage, '?')} {rule_name} [{coverage}]")

        if analysis.get("error"):
            lines.append(f"    ERROR: {analysis['error']}")
            continue

        applies_to = analysis.get("applies_to", [])
        if applies_to:
            lines.append(f"    Applies to: {', '.join(applies_to)}")

        missing = analysis.get("missing_agents", [])
        if missing:
            lines.append(f"    Missing: {', '.join(missing)}")

        unknown = analysis.get("unknown_agents", [])
        if unknown:
            lines.append(f"    Unknown agents: {', '.join(unknown)}")

    # Recommendations
    if result["recommendations"]:
        lines.append("")
        lines.append("RECOMMENDATIONS")
        lines.append("-" * 40)
        for rec in result["recommendations"]:
            lines.append(f"  • {rec}")

    lines.append("")
    lines.append("=" * 60)

    return "\n".join(lines)


def main():
    """CLI entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Audit rules for complete agent coverage"
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Show detailed human-readable output"
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Output as JSON (default)"
    )

    args = parser.parse_args()

    result = audit_rules(verbose=args.verbose)

    if args.verbose and not args.json_output:
        print(format_verbose_output(result))
    else:
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

"""
tool: rule_audit
description: Audit system rules for hierarchy, conflicts, and enforcement gaps
parameters:
  action: Action to perform (hierarchy, conflicts, gaps, agent, all)
  agent: Agent name (for action=agent)
returns: Rule audit results

Usage:
    # Show rule hierarchy
    uv run python -m tools rule_audit '{"action": "hierarchy"}'

    # Check for conflicts
    uv run python -m tools rule_audit '{"action": "conflicts"}'

    # Find enforcement gaps
    uv run python -m tools rule_audit '{"action": "gaps"}'

    # Rules for specific agent
    uv run python -m tools rule_audit '{"action": "agent", "agent": "builder"}'

    # Full audit
    uv run python -m tools rule_audit '{"action": "all"}'
"""

import json
import sys
from typing import Optional

from pilot_core.rule_registry import (
    RuleRegistry,
    EnforcementLevel,
    format_hierarchy_report,
    format_audit_report,
)


def rule_audit(
    action: str = "all",
    agent: Optional[str] = None,
) -> dict:
    """
    Audit system rules for hierarchy, conflicts, and enforcement gaps.

    Args:
        action: Action to perform
            - "hierarchy": Show priority-sorted rule hierarchy
            - "conflicts": Detect rule conflicts
            - "gaps": Find enforcement gaps
            - "agent": Show rules for specific agent
            - "all": Full audit report
        agent: Agent name (required for action="agent")

    Returns:
        Dict with audit results
    """
    registry = RuleRegistry()
    registry.load_rules()

    result = {
        "action": action,
        "total_rules": len(registry.rules),
    }

    if action == "hierarchy":
        result["hierarchy"] = registry.get_hierarchy()
        result["formatted"] = format_hierarchy_report(registry)

    elif action == "conflicts":
        conflicts = registry.detect_conflicts()
        result["conflicts"] = [{
            "rule1": c.rule1,
            "rule2": c.rule2,
            "type": c.conflict_type,
            "description": c.description,
            "severity": c.severity,
        } for c in conflicts]
        result["conflict_count"] = len(conflicts)

        # Format for display
        lines = ["RULE CONFLICTS", "=" * 40]
        if conflicts:
            for c in conflicts:
                marker = {"low": "○", "medium": "●", "high": "◉"}.get(c.severity, "?")
                lines.append(f"{marker} [{c.conflict_type}] {c.rule1} ↔ {c.rule2}")
                lines.append(f"  {c.description}")
        else:
            lines.append("No conflicts detected.")
        result["formatted"] = "\n".join(lines)

    elif action == "gaps":
        gaps = registry.audit_enforcement()
        result["gaps"] = [{
            "rule": g.rule_name,
            "current_level": g.current_level,
            "recommended_level": g.recommended_level,
            "reason": g.reason,
            "suggested_mechanism": g.suggested_mechanism,
        } for g in gaps]
        result["gap_count"] = len(gaps)

        # Format for display
        lines = ["ENFORCEMENT GAPS", "=" * 40]
        if gaps:
            for g in gaps:
                lines.append(f"• {g.rule_name}")
                lines.append(f"  Current: {g.current_level}")
                lines.append(f"  Suggestion: {g.suggested_mechanism}")
        else:
            lines.append("All rules have appropriate enforcement.")
        result["formatted"] = "\n".join(lines)

    elif action == "agent":
        if not agent:
            result["error"] = "Agent name required for action='agent'"
            result["formatted"] = "Error: Agent name required"
        else:
            rules = registry.get_rules_for_agent(agent)
            result["agent"] = agent
            result["rules"] = [{
                "name": r.name,
                "priority": r.priority,
                "description": r.description,
                "enforcement_level": r.enforcement_level,
            } for r in rules]
            result["rule_count"] = len(rules)

            # Format for display
            lines = [f"RULES FOR AGENT: {agent}", "=" * 40]
            for r in rules:
                level_marker = {
                    EnforcementLevel.CODE_ENFORCED: "[CODE]",
                    EnforcementLevel.CONTEXT_INJECTED: "[CTX]",
                    EnforcementLevel.PROMPT_ONLY: "[PROMPT]",
                }.get(r.enforcement_level, "[?]")
                lines.append(f"P{r.priority:3} {level_marker} {r.name}")
                lines.append(f"      {r.description[:60]}")
            result["formatted"] = "\n".join(lines)

    else:  # action == "all"
        result["hierarchy"] = registry.get_hierarchy()
        result["conflicts"] = [{
            "rule1": c.rule1,
            "rule2": c.rule2,
            "type": c.conflict_type,
            "severity": c.severity,
        } for c in registry.detect_conflicts()]
        result["gaps"] = [{
            "rule": g.rule_name,
            "suggestion": g.suggested_mechanism,
        } for g in registry.audit_enforcement()]

        result["formatted"] = (
            format_hierarchy_report(registry) + "\n\n" +
            format_audit_report(registry)
        )

    return result


# CLI support for direct invocation
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Audit system rules",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Show rule hierarchy
    uv run python -m tools rule_audit '{"action": "hierarchy"}'

    # Find conflicts
    uv run python -m tools rule_audit '{"action": "conflicts"}'

    # Find enforcement gaps
    uv run python -m tools rule_audit '{"action": "gaps"}'

    # Rules for builder agent
    uv run python -m tools rule_audit '{"action": "agent", "agent": "builder"}'

    # Full audit
    uv run python -m tools rule_audit
""",
    )
    parser.add_argument("json_input", nargs="?", help="JSON input")
    parser.add_argument("--action", "-a", default="all", help="Action to perform")
    parser.add_argument("--agent", help="Agent name")
    parser.add_argument("--json", "-j", action="store_true", help="Output as JSON")

    args = parser.parse_args()

    # Parse JSON input if provided
    if args.json_input and args.json_input.startswith("{"):
        try:
            json_args = json.loads(args.json_input)
            action = json_args.get("action", args.action)
            agent = json_args.get("agent", args.agent)
            output_json = json_args.get("json", args.json)
        except json.JSONDecodeError as e:
            print(f"Error parsing JSON: {e}", file=sys.stderr)
            sys.exit(1)
    else:
        action = args.action
        agent = args.agent
        output_json = args.json

    result = rule_audit(action=action, agent=agent)

    if output_json:
        # Remove formatted output for cleaner JSON
        output = {k: v for k, v in result.items() if k != "formatted"}
        print(json.dumps(output, indent=2, default=str))
    else:
        print(result.get("formatted", json.dumps(result, indent=2)))

"""
tool: rule_coverage
description: Analyze rule enforcement coverage and verify mechanisms exist
parameters:
  action: Action to perform (report, verify, orphans, opportunities)
  rule: Rule name (for action=verify)
returns: Coverage analysis results

Usage:
    # Full coverage report
    uv run python -m tools rule_coverage '{"action": "report"}'

    # Verify specific rule
    uv run python -m tools rule_coverage '{"action": "verify", "rule": "git-review-required"}'

    # Find orphaned enforcement code
    uv run python -m tools rule_coverage '{"action": "orphans"}'

    # List enforcement opportunities
    uv run python -m tools rule_coverage '{"action": "opportunities"}'
"""

import json
import sys
from typing import Optional

from lib.rule_coverage import (
    RuleCoverageAnalyzer,
    format_coverage_report,
)


def rule_coverage(
    action: str = "report",
    rule: Optional[str] = None,
) -> dict:
    """
    Analyze rule enforcement coverage.

    Args:
        action: Action to perform
            - "report": Full coverage analysis report
            - "verify": Verify specific rule's enforcement
            - "orphans": Find enforcement code without rules
            - "opportunities": List rules that could be code-enforced
        rule: Rule name (required for action="verify")

    Returns:
        Dict with coverage analysis results
    """
    analyzer = RuleCoverageAnalyzer()

    result = {
        "action": action,
    }

    if action == "verify":
        if not rule:
            result["error"] = "Rule name required for action='verify'"
            result["formatted"] = "Error: Rule name required"
        else:
            verification = analyzer.verify_enforcement(rule)
            result["rule"] = verification.rule_name
            result["mechanism"] = verification.mechanism
            result["files_exist"] = verification.files_exist
            result["files_missing"] = verification.files_missing
            result["patterns_found"] = verification.patterns_found
            result["is_verified"] = verification.is_verified
            result["notes"] = verification.verification_notes

            status = "VERIFIED" if verification.is_verified else "FAILED"
            lines = [
                f"Rule: {verification.rule_name} - {status}",
                f"Mechanism: {verification.mechanism}",
                f"Files exist: {', '.join(verification.files_exist)}",
                f"Files missing: {', '.join(verification.files_missing)}",
                f"Patterns found: {len(verification.patterns_found)}",
                f"Notes: {verification.verification_notes}",
            ]
            result["formatted"] = "\n".join(lines)

    elif action == "orphans":
        orphans = analyzer.find_orphaned_enforcement()
        result["orphans"] = [{
            "file": o.file,
            "line": o.line_number,
            "pattern": o.pattern,
            "suggested_rule": o.suggested_rule,
        } for o in orphans]
        result["count"] = len(orphans)

        lines = [f"ORPHANED ENFORCEMENT: {len(orphans)}", "=" * 40]
        for o in orphans:
            lines.append(f"  {o.file}:{o.line_number}")
            lines.append(f"    {o.pattern[:60]}...")
            if o.suggested_rule:
                lines.append(f"    Suggested: {o.suggested_rule}")
        result["formatted"] = "\n".join(lines)

    elif action == "opportunities":
        opportunities = analyzer.get_opportunities()
        result["opportunities"] = opportunities
        result["count"] = len(opportunities)

        lines = ["ENFORCEMENT OPPORTUNITIES", "=" * 40]
        for opp in opportunities:
            status = "✓" if opp["status"] == "implemented" else "○"
            lines.append(f"  {status} {opp['rule']} (P{opp.get('priority', '?')})")
            lines.append(f"    {opp['description']}")
        result["formatted"] = "\n".join(lines)

    else:  # action == "report"
        report = analyzer.analyze()
        result["timestamp"] = report.timestamp
        result["total_rules"] = report.total_rules
        result["code_enforced"] = report.rules_with_code_enforcement
        result["verified"] = report.rules_verified
        result["failed"] = report.rules_failed_verification
        result["coverage_pct"] = report.coverage_percentage
        result["summary"] = report.summary
        result["verifications"] = [{
            "rule": v.rule_name,
            "verified": v.is_verified,
            "mechanism": v.mechanism,
        } for v in report.verifications]
        result["orphan_count"] = len(report.orphaned_enforcement)
        result["opportunity_count"] = len(report.opportunities)
        result["formatted"] = format_coverage_report(report)

    return result


# CLI support
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Analyze rule enforcement coverage",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Full coverage report
    uv run python -m tools rule_coverage

    # Verify specific rule
    uv run python -m tools rule_coverage '{"action": "verify", "rule": "git-review-required"}'

    # Find orphaned enforcement
    uv run python -m tools rule_coverage '{"action": "orphans"}'
""",
    )
    parser.add_argument("json_input", nargs="?", help="JSON input")
    parser.add_argument("--action", "-a", default="report", help="Action to perform")
    parser.add_argument("--rule", "-r", help="Rule name for verify action")
    parser.add_argument("--json", "-j", action="store_true", help="Output as JSON")

    args = parser.parse_args()

    # Parse JSON input if provided
    if args.json_input and args.json_input.startswith("{"):
        try:
            json_args = json.loads(args.json_input)
            action = json_args.get("action", args.action)
            rule = json_args.get("rule", args.rule)
            output_json = json_args.get("json", args.json)
        except json.JSONDecodeError as e:
            print(f"Error parsing JSON: {e}", file=sys.stderr)
            sys.exit(1)
    else:
        action = args.action
        rule = args.rule
        output_json = args.json

    result = rule_coverage(action=action, rule=rule)

    if output_json:
        output = {k: v for k, v in result.items() if k != "formatted"}
        print(json.dumps(output, indent=2, default=str))
    else:
        print(result.get("formatted", json.dumps(result, indent=2)))

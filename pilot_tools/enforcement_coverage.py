"""
tool: enforcement_coverage
description: Report enforcement coverage from system/enforcement.yaml
parameters:
  format: Output format (json, summary). Default: summary
returns: Coverage report with percentage and gap analysis
"""

import json
import sys
from pathlib import Path

import yaml


def load_config() -> dict:
    """Load enforcement configuration."""
    config_path = Path(__file__).parent.parent / "system" / "enforcement.yaml"
    if not config_path.exists():
        return {"error": f"Config not found: {config_path}"}

    with open(config_path) as f:
        return yaml.safe_load(f)


def analyze_coverage(config: dict) -> dict:
    """Analyze enforcement coverage."""
    if "error" in config:
        return config

    # Count rules by status
    status_counts = {"enforced": 0, "pending": 0, "gap": 0, "warning": 0, "partial": 0}
    all_rules = []
    gaps = []

    # Collect all rules from each section
    for section in ["pre_commit", "runtime", "prompt_only"]:
        rules = config.get(section, [])
        for rule in rules:
            status = rule.get("status", "unknown")
            status_counts[status] = status_counts.get(status, 0) + 1
            all_rules.append({
                "section": section,
                "id": rule.get("id"),
                "description": rule.get("description"),
                "status": status,
            })

            # Track gaps and pending
            if status in ["gap", "pending", "partial", "warning"]:
                gaps.append({
                    "id": rule.get("id"),
                    "section": section,
                    "status": status,
                    "description": rule.get("description"),
                    "target": rule.get("target_mechanism") or rule.get("mechanism"),
                })

    total = sum(status_counts.values())
    enforced = status_counts.get("enforced", 0)
    coverage_pct = (enforced / total * 100) if total > 0 else 0

    return {
        "total_rules": total,
        "enforced": enforced,
        "pending": status_counts.get("pending", 0),
        "gap": status_counts.get("gap", 0),
        "warning": status_counts.get("warning", 0),
        "partial": status_counts.get("partial", 0),
        "coverage_percent": round(coverage_pct, 1),
        "gaps": gaps,
        "rules": all_rules,
    }


def format_summary(analysis: dict) -> str:
    """Format coverage as human-readable summary."""
    if "error" in analysis:
        return f"Error: {analysis['error']}"

    lines = [
        "# Enforcement Coverage Report",
        "",
        f"Coverage: {analysis['coverage_percent']}% ({analysis['enforced']}/{analysis['total_rules']} rules enforced)",
        "",
        "## Status Breakdown",
        f"- Enforced: {analysis['enforced']}",
        f"- Pending:  {analysis['pending']}",
        f"- Partial:  {analysis['partial']}",
        f"- Warning:  {analysis['warning']}",
        f"- Gap:      {analysis['gap']}",
        "",
    ]

    if analysis['gaps']:
        lines.append("## Gaps to Close")
        for gap in analysis['gaps']:
            lines.append(f"- [{gap['status']}] {gap['id']}: {gap['description']}")
        lines.append("")

    return "\n".join(lines)


def enforcement_coverage(format: str = "summary") -> dict | str:
    """
    Generate enforcement coverage report.

    Args:
        format: Output format ('json' or 'summary')

    Returns:
        Coverage analysis as dict (json) or formatted string (summary)
    """
    config = load_config()
    analysis = analyze_coverage(config)

    if format == "json":
        return analysis
    else:
        return format_summary(analysis)


if __name__ == "__main__":
    fmt = "json" if "--json" in sys.argv else "summary"
    result = enforcement_coverage(fmt)

    if isinstance(result, dict):
        print(json.dumps(result, indent=2))
    else:
        print(result)

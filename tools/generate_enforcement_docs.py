"""
tool: generate_enforcement_docs
description: Generate docs/enforcement.md from system/enforcement.yaml
parameters:
  output: Output file path (default: docs/enforcement.md)
returns: Path to generated documentation file
"""

import sys
from datetime import datetime
from pathlib import Path

import yaml


def load_config() -> dict:
    """Load enforcement configuration."""
    config_path = Path(__file__).parent.parent / "system" / "enforcement.yaml"
    if not config_path.exists():
        return {"error": f"Config not found: {config_path}"}

    with open(config_path) as f:
        return yaml.safe_load(f)


def status_emoji(status: str) -> str:
    """Return emoji for status."""
    return {
        "enforced": "✅",
        "pending": "🔄",
        "partial": "🟡",
        "warning": "⚠️",
        "gap": "❌",
    }.get(status, "❓")


def generate_markdown(config: dict) -> str:
    """Generate markdown documentation from config."""
    if "error" in config:
        return f"Error: {config['error']}"

    lines = [
        "# Code Enforcement Rules",
        "",
        f"*Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}*",
        "",
        "> **Principle**: Prompts inform; code enforces.",
        "",
        "## Summary",
        "",
    ]

    # Count statuses
    status_counts = {}
    total = 0
    for section in ["pre_commit", "runtime", "prompt_only"]:
        for rule in config.get(section, []):
            status = rule.get("status", "unknown")
            status_counts[status] = status_counts.get(status, 0) + 1
            total += 1

    enforced = status_counts.get("enforced", 0)
    coverage = (enforced / total * 100) if total > 0 else 0

    lines.extend([
        f"**Coverage**: {coverage:.1f}% ({enforced}/{total} rules enforced)",
        "",
        "| Status | Count |",
        "|--------|------:|",
    ])

    for status in ["enforced", "pending", "partial", "warning", "gap"]:
        count = status_counts.get(status, 0)
        if count > 0:
            lines.append(f"| {status_emoji(status)} {status.title()} | {count} |")

    lines.append("")

    # Pre-commit rules
    if config.get("pre_commit"):
        lines.extend([
            "## Pre-Commit Rules",
            "",
            "These rules are enforced at commit time via pre-commit hook.",
            "",
            "| Status | Rule | Description | Mechanism | Bypass |",
            "|:------:|------|-------------|-----------|--------|",
        ])

        for rule in config["pre_commit"]:
            status = rule.get("status", "unknown")
            lines.append(
                f"| {status_emoji(status)} | {rule.get('id', '')} | {rule.get('description', '')} | `{rule.get('mechanism', '')}` | {rule.get('bypass', 'none')} |"
            )

        lines.append("")

    # Runtime rules
    if config.get("runtime"):
        lines.extend([
            "## Runtime Rules",
            "",
            "These rules are enforced at runtime during code execution.",
            "",
            "| Status | Rule | Description | Mechanism | Bypass |",
            "|:------:|------|-------------|-----------|--------|",
        ])

        for rule in config["runtime"]:
            status = rule.get("status", "unknown")
            lines.append(
                f"| {status_emoji(status)} | {rule.get('id', '')} | {rule.get('description', '')} | `{rule.get('mechanism', '')}` | {rule.get('bypass', 'none')} |"
            )

        lines.append("")

    # Prompt-only rules (gaps)
    if config.get("prompt_only"):
        lines.extend([
            "## Prompt-Only Rules (Gaps)",
            "",
            "These rules exist only as CLAUDE.md instructions and need code enforcement.",
            "",
            "| Status | Rule | Description | Target Mechanism | Current |",
            "|:------:|------|-------------|------------------|--------|",
        ])

        for rule in config["prompt_only"]:
            status = rule.get("status", "unknown")
            lines.append(
                f"| {status_emoji(status)} | {rule.get('id', '')} | {rule.get('description', '')} | {rule.get('target_mechanism', '')} | {rule.get('current', '')} |"
            )

        lines.append("")

    # Reference lists
    lines.extend([
        "## Reference",
        "",
        "### Forbidden Libraries",
        "",
        "These libraries must not be imported directly (use Parallel API tools instead):",
        "",
    ])

    for lib in config.get("forbidden_libraries", []):
        lines.append(f"- `{lib}`")

    lines.extend([
        "",
        "### Banned Task Subagent Types",
        "",
        "These Claude Code Task tool subagent types are banned:",
        "",
    ])

    for subagent in config.get("banned_task_subagent_types", []):
        lines.append(f"- `{subagent}`")

    lines.extend([
        "",
        "### Known Agents",
        "",
        "Valid agents for delegation:",
        "",
    ])

    for agent in config.get("known_agents", []):
        lines.append(f"- `@{agent}`")

    lines.append("")

    return "\n".join(lines)


def generate_enforcement_docs(output: str = "docs/enforcement.md") -> str:
    """
    Generate enforcement documentation.

    Args:
        output: Output file path (default: docs/enforcement.md)

    Returns:
        Path to generated file or error message
    """
    config = load_config()
    markdown = generate_markdown(config)

    if markdown.startswith("Error:"):
        return markdown

    output_path = Path(__file__).parent.parent / output
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(markdown)

    return str(output_path)


if __name__ == "__main__":
    output = sys.argv[1] if len(sys.argv) > 1 else "docs/enforcement.md"
    result = generate_enforcement_docs(output)
    print(f"Generated: {result}")

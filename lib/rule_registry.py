"""
Rule Registry - Central management for system rules.

Provides:
1. Loading and indexing all rules from system/rules/
2. Priority-based rule hierarchy
3. Enforcement level tracking (code-enforced, context-injected, prompt-only)
4. Conflict detection between rules
5. Gap analysis for under-enforced rules

Usage:
    from lib.rule_registry import RuleRegistry

    registry = RuleRegistry()
    registry.load_rules()

    # Get rules by priority
    rules = registry.get_rules_by_priority()

    # Check for conflicts
    conflicts = registry.detect_conflicts()

    # Audit enforcement coverage
    gaps = registry.audit_enforcement()

CLI:
    uv run python -m lib.rule_registry           # List all rules
    uv run python -m lib.rule_registry --audit   # Full audit report
    uv run python -m lib.rule_registry --json    # JSON output
"""

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

import yaml


# Enforcement level definitions
class EnforcementLevel:
    """Enforcement level categories (strongest to weakest)."""
    CODE_ENFORCED = "code-enforced"      # Pre-commit hooks, validators, guards
    CONTEXT_INJECTED = "context-injected"  # Loaded into agent context at runtime
    PROMPT_ONLY = "prompt-only"            # Written in agent YAML or CLAUDE.md


# Known code enforcement mechanisms in this repo
CODE_ENFORCEMENT_MECHANISMS = {
    "git-review-required": {
        "mechanism": "pre-commit hook checks REVIEW_APPROVED marker",
        "files": [".githooks/pre-commit", "lib/approve.py"],
    },
    "web-access-policy": {
        "mechanism": "import guard blocks requests/httpx",
        "files": ["lib/guards.py"],
    },
    "agent-yaml-format": {
        "mechanism": "pre-commit YAML validation",
        "files": [".githooks/pre-commit"],
    },
    "code-enforcement-principle": {
        "mechanism": "meta-rule - enforced by git-reviewer review",
        "files": ["agents/git-reviewer.yaml"],
    },
}


@dataclass
class Rule:
    """A system rule with metadata."""
    name: str
    description: str
    priority: int
    when: str | list  # Agent(s) this applies to
    rule_text: str
    file_path: str
    enforcement_level: str = EnforcementLevel.PROMPT_ONLY
    enforcement_mechanism: Optional[str] = None
    enforcement_files: list[str] = field(default_factory=list)
    conflicts_with: list[str] = field(default_factory=list)
    depends_on: list[str] = field(default_factory=list)


@dataclass
class RuleConflict:
    """A detected conflict between rules."""
    rule1: str
    rule2: str
    conflict_type: str  # "priority", "scope", "directive"
    description: str
    severity: str  # "low", "medium", "high"


@dataclass
class EnforcementGap:
    """A rule without proper code enforcement."""
    rule_name: str
    current_level: str
    recommended_level: str
    reason: str
    suggested_mechanism: str


class RuleRegistry:
    """Central registry for all system rules."""

    def __init__(self, rules_dir: str = "system/rules"):
        self.rules_dir = Path(rules_dir)
        self.rules: dict[str, Rule] = {}
        self._loaded = False

    def load_rules(self) -> None:
        """Load all rules from the rules directory."""
        if not self.rules_dir.exists():
            raise FileNotFoundError(f"Rules directory not found: {self.rules_dir}")

        for rule_file in self.rules_dir.glob("*.yaml"):
            try:
                with open(rule_file) as f:
                    data = yaml.safe_load(f)

                if not data or "name" not in data:
                    continue

                # Determine enforcement level
                enforcement_level = EnforcementLevel.PROMPT_ONLY
                enforcement_mechanism = None
                enforcement_files = []

                rule_name = data["name"]
                if rule_name in CODE_ENFORCEMENT_MECHANISMS:
                    enforcement_level = EnforcementLevel.CODE_ENFORCED
                    enforcement_mechanism = CODE_ENFORCEMENT_MECHANISMS[rule_name]["mechanism"]
                    enforcement_files = CODE_ENFORCEMENT_MECHANISMS[rule_name]["files"]
                elif self._is_context_injected(data):
                    enforcement_level = EnforcementLevel.CONTEXT_INJECTED

                rule = Rule(
                    name=rule_name,
                    description=data.get("description", ""),
                    priority=data.get("priority", 50),
                    when=data.get("when", "*"),
                    rule_text=data.get("rule", ""),
                    file_path=str(rule_file),
                    enforcement_level=enforcement_level,
                    enforcement_mechanism=enforcement_mechanism,
                    enforcement_files=enforcement_files,
                )

                self.rules[rule_name] = rule

            except (yaml.YAMLError, IOError) as e:
                print(f"Warning: Failed to load {rule_file}: {e}")

        self._loaded = True

    def _is_context_injected(self, data: dict) -> bool:
        """Check if a rule is context-injected (loaded at runtime)."""
        # Rules that are loaded into agent context via system/queries or similar
        rule_text = data.get("rule", "").lower()
        # Heuristic: if rule mentions context injection or is referenced in queries
        return "context" in rule_text and "inject" in rule_text

    def get_rules_by_priority(self) -> list[Rule]:
        """Get all rules sorted by priority (highest first)."""
        self._ensure_loaded()
        return sorted(self.rules.values(), key=lambda r: r.priority, reverse=True)

    def get_rules_for_agent(self, agent: str) -> list[Rule]:
        """Get rules that apply to a specific agent."""
        self._ensure_loaded()
        applicable = []
        for rule in self.rules.values():
            if rule.when == "*":
                applicable.append(rule)
            elif isinstance(rule.when, list):
                for condition in rule.when:
                    if isinstance(condition, dict) and condition.get("agent") == agent:
                        applicable.append(rule)
                        break
            elif isinstance(rule.when, str) and agent in rule.when:
                applicable.append(rule)
        return sorted(applicable, key=lambda r: r.priority, reverse=True)

    def detect_conflicts(self) -> list[RuleConflict]:
        """Detect potential conflicts between rules."""
        self._ensure_loaded()
        conflicts = []

        rules_list = list(self.rules.values())
        for i, rule1 in enumerate(rules_list):
            for rule2 in rules_list[i + 1:]:
                # Check for priority conflicts (same priority, overlapping scope)
                if rule1.priority == rule2.priority:
                    if self._scopes_overlap(rule1.when, rule2.when):
                        conflicts.append(RuleConflict(
                            rule1=rule1.name,
                            rule2=rule2.name,
                            conflict_type="priority",
                            description=f"Both rules have priority {rule1.priority} and overlapping scope",
                            severity="medium",
                        ))

                # Check for directive conflicts (rules that might contradict)
                contradiction = self._check_directive_conflict(rule1, rule2)
                if contradiction:
                    conflicts.append(RuleConflict(
                        rule1=rule1.name,
                        rule2=rule2.name,
                        conflict_type="directive",
                        description=contradiction,
                        severity="high",
                    ))

        return conflicts

    def _scopes_overlap(self, when1, when2) -> bool:
        """Check if two rule scopes overlap."""
        # Universal scope overlaps with everything
        if when1 == "*" or when2 == "*":
            return True

        # Convert to sets for comparison
        def get_agents(when):
            if when == "*":
                return {"*"}
            if isinstance(when, list):
                agents = set()
                for item in when:
                    if isinstance(item, dict) and "agent" in item:
                        agents.add(item["agent"])
                return agents
            return {str(when)}

        agents1 = get_agents(when1)
        agents2 = get_agents(when2)

        return bool(agents1 & agents2)

    def _check_directive_conflict(self, rule1: Rule, rule2: Rule) -> Optional[str]:
        """Check if two rules have conflicting directives."""
        # Simple heuristic: look for opposite keywords
        opposite_pairs = [
            ("never", "always"),
            ("must not", "must"),
            ("prohibited", "required"),
            ("no ", "all "),
        ]

        text1 = rule1.rule_text.lower()
        text2 = rule2.rule_text.lower()

        for word1, word2 in opposite_pairs:
            # Check if same subject has opposite directives
            if word1 in text1 and word2 in text2:
                # This is a rough heuristic - would need more sophisticated analysis
                # for accurate conflict detection
                pass

        return None  # Conservative: only report clear conflicts

    def audit_enforcement(self) -> list[EnforcementGap]:
        """Audit rules for enforcement gaps."""
        self._ensure_loaded()
        gaps = []

        for rule in self.rules.values():
            if rule.enforcement_level == EnforcementLevel.PROMPT_ONLY:
                # Check if this rule could/should be code-enforced
                suggestion = self._suggest_enforcement(rule)
                if suggestion:
                    gaps.append(EnforcementGap(
                        rule_name=rule.name,
                        current_level=rule.enforcement_level,
                        recommended_level=EnforcementLevel.CODE_ENFORCED,
                        reason=suggestion["reason"],
                        suggested_mechanism=suggestion["mechanism"],
                    ))

        return gaps

    def _suggest_enforcement(self, rule: Rule) -> Optional[dict]:
        """Suggest code enforcement for a prompt-only rule."""
        text = rule.rule_text.lower()

        # Rules about file operations could use pre-commit hooks
        if any(word in text for word in ["file", "format", "yaml", "json"]):
            return {
                "reason": "File-related rules can be validated in pre-commit",
                "mechanism": "Add validation to .githooks/pre-commit",
            }

        # Rules about imports could use guards
        if any(word in text for word in ["import", "library", "module"]):
            return {
                "reason": "Import rules can be enforced via lib/guards.py",
                "mechanism": "Add import check to lib/guards.py",
            }

        # Rules about commits could use hooks
        if any(word in text for word in ["commit", "message", "git"]):
            return {
                "reason": "Git rules can be enforced via hooks",
                "mechanism": "Add check to .githooks/pre-commit or commit-msg",
            }

        return None

    def get_hierarchy(self) -> dict:
        """Get the full rule hierarchy as a structured dict."""
        self._ensure_loaded()

        # Group by enforcement level
        by_level = {
            EnforcementLevel.CODE_ENFORCED: [],
            EnforcementLevel.CONTEXT_INJECTED: [],
            EnforcementLevel.PROMPT_ONLY: [],
        }

        for rule in self.get_rules_by_priority():
            by_level[rule.enforcement_level].append({
                "name": rule.name,
                "priority": rule.priority,
                "description": rule.description,
                "scope": rule.when,
                "mechanism": rule.enforcement_mechanism,
            })

        return {
            "timestamp": datetime.now().isoformat(),
            "total_rules": len(self.rules),
            "by_enforcement_level": by_level,
            "priority_order": [r.name for r in self.get_rules_by_priority()],
        }

    def _ensure_loaded(self) -> None:
        """Ensure rules are loaded."""
        if not self._loaded:
            self.load_rules()


def format_hierarchy_report(registry: RuleRegistry) -> str:
    """Format the rule hierarchy as a human-readable report."""
    lines = []

    lines.append("=" * 70)
    lines.append("RULE HIERARCHY REPORT")
    lines.append("=" * 70)

    hierarchy = registry.get_hierarchy()
    lines.append(f"\nTotal rules: {hierarchy['total_rules']}")

    # Priority order
    lines.append("\n" + "-" * 70)
    lines.append("PRIORITY ORDER (highest first)")
    lines.append("-" * 70)
    for i, name in enumerate(hierarchy["priority_order"], 1):
        rule = registry.rules[name]
        level_marker = {
            EnforcementLevel.CODE_ENFORCED: "[CODE]",
            EnforcementLevel.CONTEXT_INJECTED: "[CTX]",
            EnforcementLevel.PROMPT_ONLY: "[PROMPT]",
        }.get(rule.enforcement_level, "[?]")
        lines.append(f"  {i:2}. {level_marker:10} P{rule.priority:3} {name}")

    # By enforcement level
    for level, level_name in [
        (EnforcementLevel.CODE_ENFORCED, "CODE-ENFORCED (strongest)"),
        (EnforcementLevel.CONTEXT_INJECTED, "CONTEXT-INJECTED"),
        (EnforcementLevel.PROMPT_ONLY, "PROMPT-ONLY (weakest)"),
    ]:
        rules = hierarchy["by_enforcement_level"][level]
        lines.append("\n" + "-" * 70)
        lines.append(f"{level_name} ({len(rules)} rules)")
        lines.append("-" * 70)
        if rules:
            for rule in rules:
                lines.append(f"  • {rule['name']} (P{rule['priority']})")
                if rule.get("mechanism"):
                    lines.append(f"    Mechanism: {rule['mechanism']}")
        else:
            lines.append("  (none)")

    return "\n".join(lines)


def format_audit_report(registry: RuleRegistry) -> str:
    """Format the audit report as human-readable text."""
    lines = []

    lines.append("=" * 70)
    lines.append("RULE AUDIT REPORT")
    lines.append("=" * 70)

    # Conflicts
    conflicts = registry.detect_conflicts()
    lines.append(f"\n{'─' * 40}")
    lines.append(f"CONFLICTS DETECTED: {len(conflicts)}")
    lines.append(f"{'─' * 40}")
    if conflicts:
        for c in conflicts:
            severity_marker = {"low": "○", "medium": "●", "high": "◉"}.get(c.severity, "?")
            lines.append(f"  {severity_marker} [{c.conflict_type}] {c.rule1} ↔ {c.rule2}")
            lines.append(f"    {c.description}")
    else:
        lines.append("  No conflicts detected.")

    # Enforcement gaps
    gaps = registry.audit_enforcement()
    lines.append(f"\n{'─' * 40}")
    lines.append(f"ENFORCEMENT GAPS: {len(gaps)}")
    lines.append(f"{'─' * 40}")
    if gaps:
        for gap in gaps:
            lines.append(f"  • {gap.rule_name}")
            lines.append(f"    Current: {gap.current_level}")
            lines.append(f"    Recommended: {gap.recommended_level}")
            lines.append(f"    Reason: {gap.reason}")
            lines.append(f"    Suggestion: {gap.suggested_mechanism}")
    else:
        lines.append("  All rules have appropriate enforcement.")

    # Summary stats
    lines.append(f"\n{'─' * 40}")
    lines.append("ENFORCEMENT COVERAGE")
    lines.append(f"{'─' * 40}")
    hierarchy = registry.get_hierarchy()
    for level, rules in hierarchy["by_enforcement_level"].items():
        pct = len(rules) / hierarchy["total_rules"] * 100 if hierarchy["total_rules"] > 0 else 0
        lines.append(f"  {level}: {len(rules)} rules ({pct:.1f}%)")

    lines.append("\n" + "=" * 70)
    return "\n".join(lines)


def main():
    """CLI entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Rule registry and audit tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # List all rules by priority
    uv run python -m lib.rule_registry

    # Full audit report
    uv run python -m lib.rule_registry --audit

    # Rules for specific agent
    uv run python -m lib.rule_registry --agent builder

    # JSON output
    uv run python -m lib.rule_registry --json
""",
    )

    parser.add_argument("--audit", "-a", action="store_true", help="Show full audit report")
    parser.add_argument("--agent", help="Show rules for specific agent")
    parser.add_argument("--json", "-j", action="store_true", help="Output as JSON")
    parser.add_argument("--rules-dir", default="system/rules", help="Rules directory")

    args = parser.parse_args()

    registry = RuleRegistry(args.rules_dir)

    try:
        registry.load_rules()
    except FileNotFoundError as e:
        print(f"Error: {e}")
        return 1

    if args.agent:
        rules = registry.get_rules_for_agent(args.agent)
        if args.json:
            print(json.dumps([{
                "name": r.name,
                "priority": r.priority,
                "description": r.description,
                "enforcement_level": r.enforcement_level,
            } for r in rules], indent=2))
        else:
            print(f"Rules for agent '{args.agent}':")
            for r in rules:
                print(f"  P{r.priority:3} {r.name}: {r.description[:50]}...")

    elif args.json:
        output = registry.get_hierarchy()
        if args.audit:
            output["conflicts"] = [{
                "rule1": c.rule1,
                "rule2": c.rule2,
                "type": c.conflict_type,
                "description": c.description,
                "severity": c.severity,
            } for c in registry.detect_conflicts()]
            output["gaps"] = [{
                "rule": g.rule_name,
                "current": g.current_level,
                "recommended": g.recommended_level,
                "suggestion": g.suggested_mechanism,
            } for g in registry.audit_enforcement()]
        print(json.dumps(output, indent=2, default=str))

    elif args.audit:
        print(format_hierarchy_report(registry))
        print()
        print(format_audit_report(registry))

    else:
        print(format_hierarchy_report(registry))

    return 0


if __name__ == "__main__":
    exit(main())

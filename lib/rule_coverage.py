"""
Rule Coverage Analysis - Verify enforcement mechanisms exist for rules.

This module extends rule_registry with actual verification that:
1. Declared enforcement files exist
2. Enforcement code references the rule
3. No orphaned enforcement code exists
4. Coverage metrics are tracked

Usage:
    from lib.rule_coverage import RuleCoverageAnalyzer

    analyzer = RuleCoverageAnalyzer()
    report = analyzer.analyze()

CLI:
    uv run python -m lib.rule_coverage                # Full coverage report
    uv run python -m lib.rule_coverage --verify       # Verify all mechanisms exist
    uv run python -m lib.rule_coverage --orphans      # Find orphaned enforcement
    uv run python -m lib.rule_coverage --json         # JSON output
"""

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

from lib.rule_registry import (
    RuleRegistry,
    EnforcementLevel,
    CODE_ENFORCEMENT_MECHANISMS,
)


# Extended mapping of enforcement patterns to look for in code
ENFORCEMENT_PATTERNS = {
    # Pre-commit hook patterns
    "pre-commit": {
        "file": ".githooks/pre-commit",
        "patterns": [
            r"REVIEW_APPROVED",           # git-review-required
            r"yaml\.safe_load",           # agent-yaml-format
            r"banned_imports|BANNED",     # web-access-policy
        ],
    },
    # Commit-msg hook patterns
    "commit-msg": {
        "file": ".githooks/commit-msg",
        "patterns": [
            r"Agent:",                    # agent-trailer requirement
        ],
    },
    # Guards patterns
    "guards": {
        "file": "lib/guards.py",
        "patterns": [
            r"requests|httpx|urllib",     # web-access-policy
            r"BANNED_IMPORTS",
        ],
    },
    # Approve patterns
    "approve": {
        "file": "lib/approve.py",
        "patterns": [
            r"REVIEW_APPROVED",           # git-review-required
            r"diff_hash",
        ],
    },
    # Feature tracker patterns
    "feature_tracker": {
        "file": "tools/feature_tracker.py",
        "patterns": [
            r"worktree.*branch",          # project isolation
            r"ERROR.*wrong.*branch",
        ],
    },
}

# Rules that SHOULD have code enforcement but currently don't
# This is the "gap" we want to close
ENFORCEMENT_OPPORTUNITIES = {
    "namespace-privacy": {
        "description": "Namespace privacy could be enforced by scanning imports",
        "suggested_file": "lib/guards.py",
        "suggested_pattern": "Check for cross-namespace imports",
    },
    "naming-conventions": {
        "description": "File naming could be validated in pre-commit",
        "suggested_file": ".githooks/pre-commit",
        "suggested_pattern": "Validate file names against patterns",
    },
    "context-first": {
        "description": "Could verify context.py was called before agent invocation",
        "suggested_file": "lib/invoke.py",
        "suggested_pattern": "Check for recent context gathering",
    },
    "document-after-commit": {
        "description": "Already implemented via knowledge_check.py",
        "suggested_file": "lib/knowledge_check.py",
        "suggested_pattern": "Post-commit knowledge capture",
        "status": "implemented",
    },
}


@dataclass
class EnforcementVerification:
    """Result of verifying an enforcement mechanism."""
    rule_name: str
    mechanism: str
    files_declared: list[str]
    files_exist: list[str]
    files_missing: list[str]
    patterns_found: list[str]
    patterns_missing: list[str]
    is_verified: bool
    verification_notes: str = ""


@dataclass
class OrphanedEnforcement:
    """Enforcement code without a corresponding rule."""
    file: str
    pattern: str
    line_number: int
    context: str
    suggested_rule: str = ""


@dataclass
class CoverageReport:
    """Complete rule coverage analysis report."""
    timestamp: str
    total_rules: int
    rules_with_code_enforcement: int
    rules_verified: int
    rules_failed_verification: int
    coverage_percentage: float
    verifications: list[EnforcementVerification]
    orphaned_enforcement: list[OrphanedEnforcement]
    opportunities: list[dict]
    summary: str


class RuleCoverageAnalyzer:
    """Analyzes rule coverage and enforcement verification."""

    def __init__(self, repo_root: str = "."):
        self.repo_root = Path(repo_root)
        self.registry = RuleRegistry()
        self._loaded = False

    def _ensure_loaded(self):
        if not self._loaded:
            self.registry.load_rules()
            self._loaded = True

    def verify_enforcement(self, rule_name: str) -> EnforcementVerification:
        """Verify that a rule's enforcement mechanism exists and works."""
        self._ensure_loaded()

        if rule_name not in CODE_ENFORCEMENT_MECHANISMS:
            return EnforcementVerification(
                rule_name=rule_name,
                mechanism="none",
                files_declared=[],
                files_exist=[],
                files_missing=[],
                patterns_found=[],
                patterns_missing=[],
                is_verified=False,
                verification_notes="No code enforcement declared for this rule",
            )

        mechanism_info = CODE_ENFORCEMENT_MECHANISMS[rule_name]
        declared_files = mechanism_info["files"]

        # Check which files exist
        files_exist = []
        files_missing = []
        for f in declared_files:
            path = self.repo_root / f
            if path.exists():
                files_exist.append(f)
            else:
                files_missing.append(f)

        # Search for enforcement patterns in existing files
        patterns_found = []
        patterns_missing = []

        # Get expected patterns for this rule
        expected_patterns = self._get_expected_patterns(rule_name)

        for f in files_exist:
            path = self.repo_root / f
            try:
                content = path.read_text()
                for pattern in expected_patterns:
                    if re.search(pattern, content, re.IGNORECASE):
                        patterns_found.append(f"{f}: {pattern}")
                    else:
                        patterns_missing.append(f"{f}: {pattern}")
            except IOError:
                pass

        # Determine if verified
        is_verified = (
            len(files_missing) == 0 and
            len(patterns_found) > 0
        )

        notes = []
        if files_missing:
            notes.append(f"Missing files: {', '.join(files_missing)}")
        if patterns_missing and not patterns_found:
            notes.append("No enforcement patterns found in files")
        if is_verified:
            notes.append("Enforcement mechanism verified")

        return EnforcementVerification(
            rule_name=rule_name,
            mechanism=mechanism_info["mechanism"],
            files_declared=declared_files,
            files_exist=files_exist,
            files_missing=files_missing,
            patterns_found=patterns_found,
            patterns_missing=patterns_missing,
            is_verified=is_verified,
            verification_notes="; ".join(notes),
        )

    def _get_expected_patterns(self, rule_name: str) -> list[str]:
        """Get expected code patterns for a rule."""
        # Map rules to their expected patterns
        pattern_map = {
            "git-review-required": [r"REVIEW_APPROVED", r"review.*marker"],
            "web-access-policy": [r"requests|httpx", r"BANNED|blocked"],
            "agent-yaml-format": [r"yaml\.safe_load", r"\.yaml"],
            "code-enforcement-principle": [r"enforcement", r"code.*enforc"],
        }
        return pattern_map.get(rule_name, [rule_name.replace("-", ".")])

    def find_orphaned_enforcement(self) -> list[OrphanedEnforcement]:
        """Find enforcement code that doesn't correspond to any rule."""
        orphans = []

        # Check each enforcement file for patterns not tied to rules
        for name, info in ENFORCEMENT_PATTERNS.items():
            file_path = self.repo_root / info["file"]
            if not file_path.exists():
                continue

            try:
                content = file_path.read_text()
                lines = content.split("\n")

                for i, line in enumerate(lines, 1):
                    # Look for enforcement-like patterns
                    if self._looks_like_enforcement(line):
                        # Check if this is tied to a known rule
                        rule = self._find_rule_for_pattern(line)
                        if not rule:
                            orphans.append(OrphanedEnforcement(
                                file=info["file"],
                                pattern=line.strip()[:80],
                                line_number=i,
                                context=self._get_context(lines, i),
                                suggested_rule=self._suggest_rule(line),
                            ))
            except IOError:
                pass

        return orphans

    def _looks_like_enforcement(self, line: str) -> bool:
        """Check if a line looks like enforcement code."""
        enforcement_keywords = [
            "BLOCKED", "DENIED", "PROHIBITED", "BANNED",
            "MUST", "REQUIRED", "ENFORCE", "VALIDATE",
            "ERROR.*not allowed", "reject", "refuse",
        ]
        line_lower = line.lower()
        return any(kw.lower() in line_lower for kw in enforcement_keywords)

    def _find_rule_for_pattern(self, line: str) -> Optional[str]:
        """Find which rule a line of enforcement code is for."""
        self._ensure_loaded()
        line_lower = line.lower()

        for rule_name in self.registry.rules:
            # Check if rule name appears in line
            if rule_name.replace("-", "_") in line_lower or rule_name.replace("-", " ") in line_lower:
                return rule_name

            # Check if rule keywords appear
            rule = self.registry.rules[rule_name]
            keywords = rule_name.split("-")
            if all(kw in line_lower for kw in keywords if len(kw) > 3):
                return rule_name

        return None

    def _get_context(self, lines: list[str], line_num: int, context_size: int = 2) -> str:
        """Get surrounding context for a line."""
        start = max(0, line_num - context_size - 1)
        end = min(len(lines), line_num + context_size)
        return "\n".join(lines[start:end])

    def _suggest_rule(self, line: str) -> str:
        """Suggest a rule that this enforcement might relate to."""
        line_lower = line.lower()
        suggestions = {
            "review": "git-review-required",
            "import": "web-access-policy",
            "yaml": "agent-yaml-format",
            "commit": "git-checkpoint",
            "file": "naming-conventions",
        }
        for keyword, rule in suggestions.items():
            if keyword in line_lower:
                return rule
        return ""

    def get_opportunities(self) -> list[dict]:
        """Get list of enforcement opportunities (rules that could be code-enforced)."""
        self._ensure_loaded()
        opportunities = []

        for rule_name, info in ENFORCEMENT_OPPORTUNITIES.items():
            if rule_name in self.registry.rules:
                rule = self.registry.rules[rule_name]
                opportunities.append({
                    "rule": rule_name,
                    "priority": rule.priority,
                    "description": info["description"],
                    "suggested_file": info["suggested_file"],
                    "suggested_pattern": info["suggested_pattern"],
                    "status": info.get("status", "not_implemented"),
                })

        return sorted(opportunities, key=lambda x: -self.registry.rules.get(x["rule"], type("R", (), {"priority": 0})()).priority if x["rule"] in self.registry.rules else 0)

    def analyze(self) -> CoverageReport:
        """Run complete coverage analysis."""
        self._ensure_loaded()

        # Verify all code-enforced rules
        verifications = []
        verified_count = 0
        failed_count = 0

        for rule_name in CODE_ENFORCEMENT_MECHANISMS:
            verification = self.verify_enforcement(rule_name)
            verifications.append(verification)
            if verification.is_verified:
                verified_count += 1
            else:
                failed_count += 1

        # Find orphaned enforcement
        orphans = self.find_orphaned_enforcement()

        # Get opportunities
        opportunities = self.get_opportunities()

        # Calculate coverage
        total_rules = len(self.registry.rules)
        code_enforced = len(CODE_ENFORCEMENT_MECHANISMS)
        coverage_pct = (verified_count / total_rules * 100) if total_rules > 0 else 0

        # Generate summary
        summary_parts = [
            f"Total rules: {total_rules}",
            f"Code-enforced: {code_enforced} ({code_enforced/total_rules*100:.1f}%)",
            f"Verified: {verified_count}/{code_enforced}",
        ]
        if failed_count > 0:
            summary_parts.append(f"FAILED: {failed_count}")
        if orphans:
            summary_parts.append(f"Orphaned enforcement: {len(orphans)}")

        return CoverageReport(
            timestamp=datetime.now().isoformat(),
            total_rules=total_rules,
            rules_with_code_enforcement=code_enforced,
            rules_verified=verified_count,
            rules_failed_verification=failed_count,
            coverage_percentage=coverage_pct,
            verifications=verifications,
            orphaned_enforcement=orphans,
            opportunities=opportunities,
            summary=" | ".join(summary_parts),
        )


def format_coverage_report(report: CoverageReport) -> str:
    """Format coverage report as human-readable text."""
    lines = []

    lines.append("=" * 70)
    lines.append("RULE COVERAGE ANALYSIS")
    lines.append("=" * 70)
    lines.append(f"\n{report.summary}")

    # Verification results
    lines.append(f"\n{'─' * 40}")
    lines.append("ENFORCEMENT VERIFICATION")
    lines.append(f"{'─' * 40}")

    for v in report.verifications:
        status = "✓" if v.is_verified else "✗"
        lines.append(f"\n  {status} {v.rule_name}")
        lines.append(f"    Mechanism: {v.mechanism}")
        lines.append(f"    Files: {', '.join(v.files_exist)} ({len(v.files_missing)} missing)")
        if v.patterns_found:
            lines.append(f"    Patterns found: {len(v.patterns_found)}")
        lines.append(f"    Notes: {v.verification_notes}")

    # Orphaned enforcement
    if report.orphaned_enforcement:
        lines.append(f"\n{'─' * 40}")
        lines.append(f"ORPHANED ENFORCEMENT ({len(report.orphaned_enforcement)})")
        lines.append(f"{'─' * 40}")
        for orphan in report.orphaned_enforcement[:10]:  # Limit to 10
            lines.append(f"\n  {orphan.file}:{orphan.line_number}")
            lines.append(f"    Pattern: {orphan.pattern[:60]}...")
            if orphan.suggested_rule:
                lines.append(f"    Suggested rule: {orphan.suggested_rule}")

    # Opportunities
    lines.append(f"\n{'─' * 40}")
    lines.append("ENFORCEMENT OPPORTUNITIES")
    lines.append(f"{'─' * 40}")
    for opp in report.opportunities:
        status_marker = "✓" if opp["status"] == "implemented" else "○"
        lines.append(f"\n  {status_marker} {opp['rule']} (P{opp.get('priority', '?')})")
        lines.append(f"    {opp['description']}")
        lines.append(f"    Suggested: {opp['suggested_file']}")

    # Coverage summary
    lines.append(f"\n{'─' * 40}")
    lines.append("COVERAGE METRICS")
    lines.append(f"{'─' * 40}")
    lines.append(f"  Total rules: {report.total_rules}")
    lines.append(f"  Code-enforced: {report.rules_with_code_enforcement} ({report.rules_with_code_enforcement/report.total_rules*100:.1f}%)")
    lines.append(f"  Verified: {report.rules_verified}/{report.rules_with_code_enforcement}")
    lines.append(f"  Overall coverage: {report.coverage_percentage:.1f}%")

    lines.append("\n" + "=" * 70)
    return "\n".join(lines)


def main():
    """CLI entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Analyze rule coverage and enforcement verification",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Full coverage report
    uv run python -m lib.rule_coverage

    # Verify specific rule
    uv run python -m lib.rule_coverage --verify git-review-required

    # Find orphaned enforcement
    uv run python -m lib.rule_coverage --orphans

    # JSON output
    uv run python -m lib.rule_coverage --json
""",
    )

    parser.add_argument("--verify", "-v", metavar="RULE", help="Verify specific rule")
    parser.add_argument("--orphans", "-o", action="store_true", help="Find orphaned enforcement only")
    parser.add_argument("--opportunities", action="store_true", help="Show enforcement opportunities")
    parser.add_argument("--json", "-j", action="store_true", help="Output as JSON")

    args = parser.parse_args()

    analyzer = RuleCoverageAnalyzer()

    if args.verify:
        verification = analyzer.verify_enforcement(args.verify)
        if args.json:
            print(json.dumps({
                "rule": verification.rule_name,
                "mechanism": verification.mechanism,
                "files_exist": verification.files_exist,
                "files_missing": verification.files_missing,
                "patterns_found": verification.patterns_found,
                "is_verified": verification.is_verified,
                "notes": verification.verification_notes,
            }, indent=2))
        else:
            status = "VERIFIED" if verification.is_verified else "FAILED"
            print(f"Rule: {verification.rule_name} - {status}")
            print(f"Mechanism: {verification.mechanism}")
            print(f"Files: {verification.files_exist} (missing: {verification.files_missing})")
            print(f"Notes: {verification.verification_notes}")

    elif args.orphans:
        orphans = analyzer.find_orphaned_enforcement()
        if args.json:
            print(json.dumps([{
                "file": o.file,
                "line": o.line_number,
                "pattern": o.pattern,
                "suggested_rule": o.suggested_rule,
            } for o in orphans], indent=2))
        else:
            print(f"Found {len(orphans)} orphaned enforcement patterns:")
            for o in orphans:
                print(f"  {o.file}:{o.line_number} - {o.pattern[:50]}...")

    elif args.opportunities:
        opportunities = analyzer.get_opportunities()
        if args.json:
            print(json.dumps(opportunities, indent=2))
        else:
            print("Enforcement Opportunities:")
            for opp in opportunities:
                status = "✓" if opp["status"] == "implemented" else "○"
                print(f"  {status} {opp['rule']}: {opp['description']}")

    else:
        report = analyzer.analyze()
        if args.json:
            print(json.dumps({
                "timestamp": report.timestamp,
                "total_rules": report.total_rules,
                "code_enforced": report.rules_with_code_enforcement,
                "verified": report.rules_verified,
                "failed": report.rules_failed_verification,
                "coverage_pct": report.coverage_percentage,
                "verifications": [{
                    "rule": v.rule_name,
                    "verified": v.is_verified,
                    "mechanism": v.mechanism,
                } for v in report.verifications],
                "orphans": len(report.orphaned_enforcement),
                "opportunities": len(report.opportunities),
            }, indent=2))
        else:
            print(format_coverage_report(report))

    return 0


if __name__ == "__main__":
    exit(main())

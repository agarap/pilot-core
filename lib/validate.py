"""
Validation utilities for enforcing pilot system conventions.

Used by pre-commit hooks and code review to ensure:
- No logs or workspaces in commits
- Project outputs in correct locations
- Run manifests present for project changes
- YAML/MD files have required fields
- Consistency across the repo
"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import yaml

# Legacy projects exempt from .runs/ requirement
# These predate the run manifest convention
LEGACY_PROJECTS: frozenset[str] = frozenset({
    "code-enforcement-max",
    "deep-research-utilization",
})

# Parallel.ai tools that provide work namespace provenance
PARALLEL_TOOLS: frozenset[str] = frozenset({
    "parallel_task",
    "web_search",
    "web_fetch",
    "deep_research",
    "parallel_findall",
    "parallel_chat",
})


def get_staged_files() -> list[str]:
    """Get list of staged files."""
    result = subprocess.run(
        ["git", "diff", "--cached", "--name-only"],
        capture_output=True,
        text=True,
    )
    return [f for f in result.stdout.strip().split("\n") if f]


def check_no_logs_or_workspaces(files: list[str]) -> list[str]:
    """Check that no log or workspace files are being committed."""
    errors = []
    for f in files:
        if f.startswith("logs/"):
            errors.append(f"ERROR: Log file should not be committed: {f}")
        if f.startswith("workspaces/"):
            errors.append(f"ERROR: Workspace file should not be committed: {f}")
        if f.startswith("output/"):
            errors.append(f"ERROR: Output file should not be committed: {f}")
    return errors


def check_project_structure(files: list[str]) -> list[str]:
    """Check that project files follow expected structure.

    All projects must have a .runs/ directory for provenance tracking,
    except legacy projects that predate this convention.

    Note: This only applies to legacy flat-structure projects (projects/{project}/).
    Namespace directories (projects/work/, projects/personal/) are handled by
    check_namespace_separation().
    """
    errors = []

    # Find projects being modified
    projects_modified = set()
    for f in files:
        if f.startswith("projects/"):
            parts = f.split("/")
            if len(parts) > 1:
                # Skip namespace directories - handled by check_namespace_separation()
                if parts[1] in ("work", "personal"):
                    continue
                projects_modified.add(parts[1])

    # Check each modified project has a .runs directory
    for project in projects_modified:
        if project == ".gitkeep":
            continue
        # Skip legacy projects exempt from this requirement
        if project in LEGACY_PROJECTS:
            continue
        runs_dir = Path("projects") / project / ".runs"
        if not runs_dir.exists():
            errors.append(
                f"ERROR: Project '{project}' has no .runs/ directory. "
                f"Run manifests are required for provenance tracking."
            )

    return errors


def check_yaml_format(files: list[str]) -> list[str]:
    """Validate YAML files have required structure."""
    errors = []

    for f in files:
        if not f.endswith(".yaml"):
            continue

        path = Path(f)
        if not path.exists():
            continue  # Deleted file

        try:
            with open(path) as fh:
                content = yaml.safe_load(fh)

            if not isinstance(content, dict):
                continue

            # Check system/rules have required fields
            if f.startswith("system/rules/"):
                required = ["name", "description"]
                for req in required:
                    if req not in content:
                        errors.append(f"ERROR: {f} missing required field: {req}")

            # Check knowledge/decisions have required fields
            if f.startswith("knowledge/decisions/") and not f.endswith("_template.yaml"):
                required = ["id", "title", "status"]
                for req in required:
                    if req not in content:
                        errors.append(f"ERROR: {f} missing required field: {req}")

        except yaml.YAMLError as e:
            errors.append(f"ERROR: Invalid YAML in {f}: {e}")

    return errors


def check_agent_yaml(files: list[str]) -> list[str]:
    """Validate agent YAML files have required fields."""
    errors = []

    for f in files:
        if not f.endswith(".yaml"):
            continue

        # Only check agent definitions
        if not f.startswith("agents/"):
            continue

        path = Path(f)
        if not path.exists():
            continue

        try:
            with open(path) as fh:
                content = yaml.safe_load(fh)

            if not isinstance(content, dict):
                errors.append(f"ERROR: {f} is not a valid YAML dictionary")
                continue

            # Check required fields for agents
            required = ["name", "type", "description", "prompt"]
            for req in required:
                if req not in content:
                    errors.append(f"ERROR: {f} missing required field: {req}")

            # Check type is subagent
            if content.get("type") != "subagent":
                errors.append(f"ERROR: {f} should have type: subagent")

        except yaml.YAMLError as e:
            errors.append(f"ERROR: {f} invalid YAML: {e}")
        except Exception as e:
            errors.append(f"ERROR: Could not read {f}: {e}")

    return errors


def check_consistency(files: list[str]) -> list[str]:
    """Check cross-file consistency."""
    warnings = []

    # If CLAUDE.md is modified, check it still references valid paths
    if "CLAUDE.md" in files:
        claude_md = Path("CLAUDE.md")
        if claude_md.exists():
            content = claude_md.read_text()

            # Check referenced directories exist
            dirs_to_check = ["agents", "tools", "lib", "projects"]
            for d in dirs_to_check:
                if d in content and not Path(d).exists():
                    warnings.append(f"WARNING: CLAUDE.md references non-existent: {d}")

    return warnings


def check_parallel_branch_binding() -> list[str]:
    """Check that parallel/* branches have a project binding.

    If the current branch starts with 'parallel/', we require a binding
    in some project's feature_list.json (worktree.branch field).
    Commits on parallel branches without bindings are blocked.

    Bypass: Set PILOT_SKIP_WORKTREE_BINDING=1 env var to skip this check.
    """
    # Bypass via environment variable
    if os.environ.get("PILOT_SKIP_WORKTREE_BINDING"):
        return []

    # Get current branch
    result = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        capture_output=True,
        text=True,
    )
    branch = result.stdout.strip()

    # Only check parallel/* branches
    if not branch.startswith("parallel/"):
        return []

    # Scan all feature_list.json files for binding
    projects_dir = Path("projects")
    if not projects_dir.exists():
        return [
            f"ERROR: Branch {branch} has no project binding. "
            "Create binding in projects/<project>/feature_list.json"
        ]

    for feature_list in projects_dir.glob("**/feature_list.json"):
        try:
            with open(feature_list) as fh:
                data = json.load(fh)

            # Check worktree.branch field
            worktree = data.get("worktree", {})
            if isinstance(worktree, dict) and worktree.get("branch") == branch:
                return []  # Binding found, valid

            # Check worktree_assignments format (nested branch fields)
            assignments = data.get("worktree_assignments", {})
            if isinstance(assignments, dict):
                for _key, info in assignments.items():
                    if isinstance(info, dict) and info.get("branch") == branch:
                        return []  # Binding found, valid

        except (json.JSONDecodeError, OSError):
            continue

    # No binding found
    return [
        f"ERROR: Branch {branch} has no project binding. "
        "Create binding in projects/<project>/feature_list.json"
    ]


def check_delegation(files: list[str]) -> list[str]:
    """Check that staged project files have delegation evidence in run manifests.

    For each staged file in projects/*, this checks that at least one run manifest
    exists with an "agent" field, providing evidence that the change was made
    through proper agent delegation.

    Args:
        files: List of staged file paths

    Returns:
        List of error messages for files without delegation evidence.
    """
    # Bypass via environment variable
    if os.environ.get("PILOT_SKIP_DELEGATION") == "1":
        return []

    errors = []

    # Find projects being modified (excluding namespace directories)
    projects_modified = set()
    for f in files:
        if f.startswith("projects/"):
            parts = f.split("/")
            if len(parts) > 1:
                # Skip namespace directories - they have different validation
                if parts[1] in ("work", "personal"):
                    continue
                # Skip .gitkeep files
                if parts[1] == ".gitkeep":
                    continue
                projects_modified.add(parts[1])

    # Check each modified project for delegation evidence
    for project in projects_modified:
        # Skip legacy projects exempt from this requirement
        if project in LEGACY_PROJECTS:
            continue

        runs_dir = Path("projects") / project / ".runs"

        # If no .runs directory, check_project_structure will catch it
        if not runs_dir.exists():
            continue

        # Look for manifests with an "agent" field
        has_delegation_evidence = False
        for manifest_file in runs_dir.glob("*.yaml"):
            try:
                with open(manifest_file) as fh:
                    manifest = yaml.safe_load(fh)

                if not isinstance(manifest, dict):
                    continue

                # Check for agent field (evidence of delegation)
                if manifest.get("agent"):
                    has_delegation_evidence = True
                    break

            except (yaml.YAMLError, OSError):
                continue

        if not has_delegation_evidence:
            errors.append(
                f"ERROR: Project '{project}' has no delegation evidence. "
                f"Run manifests in projects/{project}/.runs/ must have an 'agent' field "
                f"showing the work was delegated to a subagent. "
                f"Bypass with: PILOT_SKIP_DELEGATION=1"
            )

    return errors


def check_namespace_separation(files: list[str]) -> list[str]:
    """Check that work namespace categories have Parallel.ai provenance.

    The work namespace structure is: projects/work/{category}/{project}/
    Categories (parallel, research, infrastructure) require evidence of
    Parallel.ai tool usage in run manifests at the category level.
    Personal namespace (projects/personal/*) has no such restriction.

    The .runs/ directory is checked at the CATEGORY level:
    - projects/work/parallel/.runs/
    - projects/work/research/.runs/
    - projects/work/infrastructure/.runs/
    """
    errors = []

    # Find work categories being modified
    # Structure: projects/work/{category}/{project}/...
    work_categories = set()
    for f in files:
        if f.startswith("projects/work/"):
            parts = f.split("/")
            if len(parts) > 2:
                work_categories.add(parts[2])  # category (parallel, research, etc.)

    # Check each work category has Parallel provenance
    for category in work_categories:
        if category == ".gitkeep":
            continue

        # Check for .runs/ at category level
        runs_dir = Path("projects/work") / category / ".runs"
        if not runs_dir.exists():
            errors.append(
                f"ERROR: Work category '{category}' has no .runs/ directory. "
                f"Expected: projects/work/{category}/.runs/ for Parallel.ai provenance."
            )
            continue

        # Scan manifests for Parallel.ai tool usage
        has_parallel_provenance = False
        for manifest_file in runs_dir.glob("*.yaml"):
            try:
                with open(manifest_file) as fh:
                    manifest = yaml.safe_load(fh)

                if not isinstance(manifest, dict):
                    continue

                # Check tools field for Parallel.ai tools
                tools = manifest.get("tools", [])
                if isinstance(tools, list):
                    for tool in tools:
                        if tool in PARALLEL_TOOLS:
                            has_parallel_provenance = True
                            break

                if has_parallel_provenance:
                    break

            except (yaml.YAMLError, OSError):
                continue

        if not has_parallel_provenance:
            errors.append(
                f"ERROR: Work category '{category}' has no Parallel.ai provenance. "
                f"Run manifests in projects/work/{category}/.runs/ must show usage of: "
                f"{', '.join(sorted(PARALLEL_TOOLS))}"
            )

    return errors


def validate_staged_changes() -> int:
    """Run all validations on staged changes. Returns exit code."""
    files = get_staged_files()
    if not files:
        return 0

    all_errors = []
    all_warnings = []

    # Check for forbidden files
    all_errors.extend(check_no_logs_or_workspaces(files))

    # Check project structure (now errors, not warnings)
    all_errors.extend(check_project_structure(files))

    # Check delegation evidence in run manifests
    all_errors.extend(check_delegation(files))

    # Check namespace separation (work vs personal)
    all_errors.extend(check_namespace_separation(files))

    # Check parallel branch binding
    all_errors.extend(check_parallel_branch_binding())

    # Validate YAML format
    all_errors.extend(check_yaml_format(files))

    # Validate agent YAML files
    all_errors.extend(check_agent_yaml(files))

    # Check consistency
    all_warnings.extend(check_consistency(files))

    # Print results
    for error in all_errors:
        print(error, file=sys.stderr)

    for warning in all_warnings:
        print(warning, file=sys.stderr)

    # Errors block commit, warnings don't
    if all_errors:
        print("\nCommit blocked due to errors above.", file=sys.stderr)
        return 1

    return 0


def validate_full_repo() -> int:
    """Validate entire repo, not just staged changes."""
    all_errors = []
    all_warnings = []

    # Check all YAML files
    for f in Path(".").rglob("*.yaml"):
        if ".venv" in str(f):
            continue
        all_errors.extend(check_yaml_format([str(f)]))

    # Check all agent YAML files
    agents_dir = Path("agents")
    if agents_dir.exists():
        for f in agents_dir.glob("*.yaml"):
            all_errors.extend(check_agent_yaml([str(f)]))

    # Print results
    for error in all_errors:
        print(error, file=sys.stderr)

    for warning in all_warnings:
        print(warning, file=sys.stderr)

    if all_errors:
        print(f"\nFound {len(all_errors)} errors.", file=sys.stderr)
        return 1

    print("Repo validation passed.")
    return 0


if __name__ == "__main__":
    if "--full" in sys.argv:
        sys.exit(validate_full_repo())
    else:
        sys.exit(validate_staged_changes())

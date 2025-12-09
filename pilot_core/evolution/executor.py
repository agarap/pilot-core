"""
Agent-first evolution executor.

All migrations are performed by agents. The executor orchestrates but
delegates actual transformations to intelligent models.

This approach:
1. Handles edge cases that code can't anticipate
2. Makes migrations robust to format variations
3. Allows "intelligent" handling of ambiguous cases
4. Keeps migration definitions simple and declarative
"""

from pathlib import Path
from typing import Optional
import yaml
import logging
import asyncio
import os

from pilot_core.evolution.registry import MigrationRegistry, Migration
from pilot_core.paths import PathRegistry, get_registry

logger = logging.getLogger("pilot.evolution.executor")


class EvolutionExecutor:
    """
    Agent-first migration executor.

    Migrations are ALWAYS performed by agents. The executor:
    1. Detects what needs migration
    2. Loads migration definitions (prompts + examples)
    3. Invokes agents to perform each migration
    4. Validates results
    """

    def __init__(self, paths: Optional[PathRegistry] = None):
        """
        Initialize executor.

        Args:
            paths: PathRegistry instance. If None, auto-discovers.
        """
        self.paths = paths or get_registry()

    def _load_versions(self) -> dict:
        """Load current schema versions from core."""
        versions_file = self.paths.core_root / "system" / "schemas" / "versions.yaml"
        if versions_file.exists():
            with open(versions_file) as f:
                return yaml.safe_load(f) or {}
        return {"agent": 1, "rule": 1, "tool": 1, "config": 1}

    def _get_file_version(self, data: dict) -> int:
        """Get schema version from file data, defaulting to 1."""
        return data.get("_schema_version", 1)

    def check_compatibility(self) -> dict:
        """
        Check if user repo is compatible with current core schemas.

        Returns:
            {
                "compatible": bool,
                "issues": [
                    {"type": "agent", "file": "...", "current": 1, "required": 2},
                    ...
                ],
                "migrations_needed": ["agent_v1_to_v2", ...]
            }
        """
        issues = []
        migrations_needed = set()
        versions = self._load_versions()

        # Check agents
        user_agents = self.paths.user_root / "agents"
        if user_agents.exists():
            for agent_file in user_agents.glob("*.yaml"):
                try:
                    with open(agent_file) as f:
                        data = yaml.safe_load(f) or {}

                    file_version = self._get_file_version(data)
                    required = versions.get("agent", 1)

                    if file_version < required:
                        issues.append({
                            "type": "agent",
                            "file": str(agent_file),
                            "current": file_version,
                            "required": required,
                        })
                        try:
                            migs = MigrationRegistry.get_path("agent", file_version, required)
                            migrations_needed.update(m.id for m in migs)
                        except ValueError:
                            pass  # No migration path defined yet

                except Exception as e:
                    logger.warning(f"Failed to check {agent_file}: {e}")

        # Check rules
        user_rules = self.paths.user_root / "system" / "rules"
        if user_rules.exists():
            for rule_file in user_rules.glob("*.yaml"):
                try:
                    with open(rule_file) as f:
                        data = yaml.safe_load(f) or {}

                    file_version = self._get_file_version(data)
                    required = versions.get("rule", 1)

                    if file_version < required:
                        issues.append({
                            "type": "rule",
                            "file": str(rule_file),
                            "current": file_version,
                            "required": required,
                        })
                        try:
                            migs = MigrationRegistry.get_path("rule", file_version, required)
                            migrations_needed.update(m.id for m in migs)
                        except ValueError:
                            pass

                except Exception as e:
                    logger.warning(f"Failed to check {rule_file}: {e}")

        return {
            "compatible": len(issues) == 0,
            "issues": issues,
            "migrations_needed": list(migrations_needed),
        }

    async def migrate_file_with_agent(
        self,
        file_path: Path,
        migration: Migration,
    ) -> dict:
        """
        Use an agent to migrate a single file.

        The agent receives:
        - Migration guidance (what to transform)
        - Examples of before/after
        - The actual file content

        Returns:
            Agent result dict with success/failure
        """
        # Import here to avoid circular imports
        from pilot_core.invoke import invoke_agent

        # Read current content
        with open(file_path) as f:
            content = f.read()

        # Build the migration prompt
        prompt = migration.build_prompt(content, str(file_path))

        # Full task for the agent
        task = f"""You are performing a schema migration on {file_path}.

{prompt}

After reading the guidance and examples above:
1. Read the current file at {file_path}
2. Apply the migration transformations
3. Write the migrated content back to {file_path}
4. Ensure the file is valid YAML

The migrated file MUST include `_schema_version: {migration.to_version}` field.
"""

        logger.info(f"Invoking agent to migrate {file_path} ({migration.id})")

        # Use builder agent for migrations
        # Could also use a dedicated "migrator" agent if defined
        try:
            result = await invoke_agent("builder", task)

            if result.get("success"):
                logger.info(f"Successfully migrated {file_path}")
            else:
                logger.error(f"Failed to migrate {file_path}: {result.get('error')}")

            return result

        except Exception as e:
            logger.error(f"Exception during migration of {file_path}: {e}")
            return {
                "success": False,
                "error": str(e),
                "agent": "builder",
            }

    async def migrate_all(self, dry_run: bool = False) -> dict:
        """
        Migrate all files in user repo to current schema versions.

        Args:
            dry_run: If True, report what would change without modifying

        Returns:
            {
                "migrated": ["path1", "path2", ...],
                "failed": [{"file": "...", "error": "..."}, ...],
                "skipped": [{"file": "...", "reason": "..."}, ...]
            }
        """
        compat = self.check_compatibility()

        if compat["compatible"]:
            logger.info("All files are compatible, no migrations needed")
            return {"migrated": [], "failed": [], "skipped": []}

        versions = self._load_versions()
        results = {"migrated": [], "failed": [], "skipped": []}

        for issue in compat["issues"]:
            file_path = Path(issue["file"])
            schema_type = issue["type"]
            current_ver = issue["current"]
            target_ver = versions.get(schema_type, 1)

            if dry_run:
                results["skipped"].append({
                    "file": str(file_path),
                    "reason": f"dry_run: would migrate {schema_type} v{current_ver} to v{target_ver}",
                })
                continue

            # Get migration chain
            try:
                migrations = MigrationRegistry.get_path(schema_type, current_ver, target_ver)
            except ValueError as e:
                results["failed"].append({
                    "file": str(file_path),
                    "error": str(e),
                })
                continue

            if not migrations:
                results["skipped"].append({
                    "file": str(file_path),
                    "reason": "no migrations needed",
                })
                continue

            # Apply each migration in sequence
            success = True
            for migration in migrations:
                result = await self.migrate_file_with_agent(file_path, migration)
                if not result.get("success"):
                    results["failed"].append({
                        "file": str(file_path),
                        "migration": migration.id,
                        "error": result.get("error", "Unknown error"),
                    })
                    success = False
                    break

            if success:
                results["migrated"].append(str(file_path))

        return results


# Convenience functions for CLI/module use

def check_compatibility() -> dict:
    """Check compatibility of current repo."""
    executor = EvolutionExecutor()
    return executor.check_compatibility()


async def migrate_all(dry_run: bool = False) -> dict:
    """Migrate all files in current repo."""
    executor = EvolutionExecutor()
    return await executor.migrate_all(dry_run=dry_run)


def migrate_all_sync(dry_run: bool = False) -> dict:
    """Synchronous wrapper for migrate_all."""
    return asyncio.run(migrate_all(dry_run=dry_run))

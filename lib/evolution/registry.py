"""
Migration registry for agent-first schema migrations.

Migrations are defined declaratively in YAML with:
- Guidance: Instructions for the agent
- Examples: Before/after examples for few-shot learning

The agent interprets the guidance and applies transformations intelligently,
handling edge cases that hardcoded transforms can't anticipate.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Optional
import yaml
import logging

logger = logging.getLogger("pilot.evolution.registry")


@dataclass
class Migration:
    """
    An agent-executable migration.

    Migrations are defined declaratively with guidance for the agent.
    The agent interprets the guidance and applies it intelligently.
    """

    schema_type: str  # e.g., "agent", "rule"
    from_version: int
    to_version: int
    description: str
    guidance: str  # Prompt for agent to follow
    examples: list[dict]  # Before/after examples for few-shot

    @property
    def id(self) -> str:
        """Unique identifier for this migration."""
        return f"{self.schema_type}_v{self.from_version}_to_v{self.to_version}"

    @classmethod
    def load(cls, path: Path) -> "Migration":
        """Load migration from YAML file."""
        with open(path) as f:
            data = yaml.safe_load(f)

        return cls(
            schema_type=data["schema_type"],
            from_version=data["from_version"],
            to_version=data["to_version"],
            description=data.get("description", ""),
            guidance=data["guidance"],
            examples=data.get("examples", []),
        )

    def build_prompt(self, file_content: str, file_path: str = "file.yaml") -> str:
        """
        Build the migration prompt for the agent.

        This creates a comprehensive prompt that:
        1. Explains the migration task
        2. Provides guidance on what to change
        3. Shows examples of before/after transformations
        4. Includes the actual file content to migrate
        """
        prompt = f"""# Migration Task: {self.schema_type} v{self.from_version} to v{self.to_version}

## Description
{self.description}

## Migration Guidance
{self.guidance}

"""

        if self.examples:
            prompt += "## Examples\n\n"
            for i, ex in enumerate(self.examples, 1):
                prompt += f"### Example {i}\n"
                prompt += f"**Before** (v{self.from_version}):\n```yaml\n{ex['before'].strip()}\n```\n\n"
                prompt += f"**After** (v{self.to_version}):\n```yaml\n{ex['after'].strip()}\n```\n\n"

        prompt += f"""## File to Migrate

Path: `{file_path}`

Current content:
```yaml
{file_content}
```

## Instructions

1. Read and understand the current file content
2. Apply the migration transformations described above
3. Ensure the migrated content is valid YAML
4. Add or update `_schema_version: {self.to_version}` field

Output ONLY the migrated YAML content. Do not include any explanations or markdown.
"""
        return prompt


class MigrationRegistry:
    """
    Registry of all available migrations.

    Migrations are loaded from the system/migrations/ directory.
    Each migration is a YAML file defining the transformation.
    """

    _migrations: dict[str, Migration] = {}
    _loaded: bool = False

    @classmethod
    def load_all(cls, migrations_dir: Optional[Path] = None):
        """
        Load all migrations from a directory.

        Args:
            migrations_dir: Directory containing migration YAML files.
                           Defaults to system/migrations/ in core.
        """
        if migrations_dir is None:
            # Default to core's migrations directory
            migrations_dir = Path(__file__).parent.parent.parent / "system" / "migrations"

        if not migrations_dir.exists():
            logger.debug(f"Migrations directory does not exist: {migrations_dir}")
            cls._loaded = True
            return

        for yaml_file in migrations_dir.glob("*.yaml"):
            try:
                migration = Migration.load(yaml_file)
                cls._migrations[migration.id] = migration
                logger.debug(f"Loaded migration: {migration.id}")
            except Exception as e:
                logger.warning(f"Failed to load migration {yaml_file}: {e}")

        cls._loaded = True
        logger.info(f"Loaded {len(cls._migrations)} migrations")

    @classmethod
    def ensure_loaded(cls):
        """Ensure migrations are loaded."""
        if not cls._loaded:
            cls.load_all()

    @classmethod
    def get(cls, migration_id: str) -> Optional[Migration]:
        """Get a migration by ID."""
        cls.ensure_loaded()
        return cls._migrations.get(migration_id)

    @classmethod
    def get_path(cls, schema_type: str, from_ver: int, to_ver: int) -> list[Migration]:
        """
        Get migration path from one version to another.

        Args:
            schema_type: Type of schema (agent, rule, etc.)
            from_ver: Current version
            to_ver: Target version

        Returns:
            List of migrations to apply in order

        Raises:
            ValueError: If no migration path exists
        """
        cls.ensure_loaded()

        if from_ver >= to_ver:
            return []

        path = []
        current = from_ver

        while current < to_ver:
            mig_id = f"{schema_type}_v{current}_to_v{current + 1}"
            if mig_id not in cls._migrations:
                raise ValueError(
                    f"No migration path from {schema_type} v{from_ver} to v{to_ver}. "
                    f"Missing: {mig_id}"
                )
            path.append(cls._migrations[mig_id])
            current += 1

        return path

    @classmethod
    def list_migrations(cls) -> list[str]:
        """List all available migration IDs."""
        cls.ensure_loaded()
        return list(cls._migrations.keys())

    @classmethod
    def reset(cls):
        """Reset the registry (for testing)."""
        cls._migrations = {}
        cls._loaded = False

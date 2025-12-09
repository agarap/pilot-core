"""
Evolution system for pilot-core.

This module provides agent-first schema migrations for dependent repositories.
When pilot-core evolves its formats, dependents can be automatically migrated.

Usage:
    # Check compatibility
    from pilot_core.evolution import check_compatibility
    issues = check_compatibility()

    # Migrate all files
    from pilot_core.evolution import migrate_all
    results = await migrate_all()

CLI:
    # Check what needs migration
    uv run python -m lib.evolution check

    # Dry-run migration
    uv run python -m lib.evolution migrate --dry-run

    # Apply migrations
    uv run python -m lib.evolution migrate
"""

from pilot_core.evolution.executor import (
    EvolutionExecutor,
    check_compatibility,
    migrate_all,
)
from pilot_core.evolution.registry import (
    Migration,
    MigrationRegistry,
)

__all__ = [
    "EvolutionExecutor",
    "check_compatibility",
    "migrate_all",
    "Migration",
    "MigrationRegistry",
]

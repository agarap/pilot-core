"""
CLI for pilot-core evolution system.

Usage:
    # Check compatibility
    uv run python -m lib.evolution check

    # Show migration status
    uv run python -m lib.evolution status

    # Dry-run migrations
    uv run python -m lib.evolution migrate --dry-run

    # Apply migrations
    uv run python -m lib.evolution migrate

    # List available migrations
    uv run python -m lib.evolution list
"""

import argparse
import asyncio
import json
import sys

from pilot_core.evolution.executor import EvolutionExecutor, check_compatibility
from pilot_core.evolution.registry import MigrationRegistry
from pilot_core.paths import PathRegistry


def cmd_check(args):
    """Check compatibility of current repo."""
    result = check_compatibility()

    if result["compatible"]:
        print("All files are compatible with current pilot-core schemas.")
        return 0

    print(f"Found {len(result['issues'])} compatibility issues:\n")

    for issue in result["issues"]:
        print(f"  - {issue['file']}")
        print(f"    Type: {issue['type']}, Current: v{issue['current']}, Required: v{issue['required']}")

    if result["migrations_needed"]:
        print(f"\nMigrations needed: {', '.join(result['migrations_needed'])}")

    print("\nRun 'uv run python -m lib.evolution migrate' to fix.")
    return 1


def cmd_status(args):
    """Show detailed migration status."""
    paths = PathRegistry.discover()
    executor = EvolutionExecutor(paths)
    result = executor.check_compatibility()

    print("Evolution Status")
    print("=" * 50)
    print(f"Core root: {paths.core_root}")
    print(f"User root: {paths.user_root}")
    print(f"Same repo: {paths.is_same_repo()}")
    print()

    # Load and show schema versions
    versions = executor._load_versions()
    print("Current Schema Versions:")
    for schema_type, version in versions.items():
        print(f"  {schema_type}: v{version}")
    print()

    if result["compatible"]:
        print("Status: COMPATIBLE")
        print("All files match current schema versions.")
    else:
        print(f"Status: {len(result['issues'])} FILES NEED MIGRATION")
        print()
        for issue in result["issues"]:
            print(f"  {issue['file']}")
            print(f"    {issue['type']} v{issue['current']} -> v{issue['required']}")

    return 0 if result["compatible"] else 1


def cmd_migrate(args):
    """Run migrations."""
    executor = EvolutionExecutor()

    # Check what needs migration first
    compat = executor.check_compatibility()

    if compat["compatible"]:
        print("All files are already compatible. Nothing to migrate.")
        return 0

    print(f"Found {len(compat['issues'])} files needing migration.")

    if args.dry_run:
        print("\n[DRY RUN] Would migrate:")
        for issue in compat["issues"]:
            print(f"  - {issue['file']} ({issue['type']} v{issue['current']} -> v{issue['required']})")
        return 0

    # Confirm before running
    if not args.yes:
        response = input("\nProceed with migration? [y/N] ")
        if response.lower() != "y":
            print("Aborted.")
            return 1

    print("\nRunning migrations...")
    result = asyncio.run(executor.migrate_all(dry_run=False))

    print("\nResults:")
    if result["migrated"]:
        print(f"  Migrated: {len(result['migrated'])} files")
        for f in result["migrated"]:
            print(f"    - {f}")

    if result["failed"]:
        print(f"  Failed: {len(result['failed'])} files")
        for f in result["failed"]:
            print(f"    - {f['file']}: {f.get('error', 'Unknown error')}")

    if result["skipped"]:
        print(f"  Skipped: {len(result['skipped'])} files")

    return 0 if not result["failed"] else 1


def cmd_list(args):
    """List available migrations."""
    MigrationRegistry.load_all()
    migrations = MigrationRegistry.list_migrations()

    if not migrations:
        print("No migrations defined yet.")
        print("\nMigrations are stored in: system/migrations/")
        print("They will be created as pilot-core evolves.")
        return 0

    print("Available Migrations:")
    print("-" * 40)

    for mig_id in sorted(migrations):
        migration = MigrationRegistry.get(mig_id)
        if migration:
            print(f"  {mig_id}")
            if migration.description:
                print(f"    {migration.description[:60]}...")
    return 0


def main():
    parser = argparse.ArgumentParser(
        description="Pilot-core evolution system",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Commands:
  check     Check if current repo is compatible with core schemas
  status    Show detailed migration status
  migrate   Apply migrations to bring repo up to date
  list      List available migration definitions

Examples:
  uv run python -m lib.evolution check
  uv run python -m lib.evolution migrate --dry-run
  uv run python -m lib.evolution migrate -y
""",
    )

    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # check command
    check_parser = subparsers.add_parser("check", help="Check compatibility")
    check_parser.set_defaults(func=cmd_check)

    # status command
    status_parser = subparsers.add_parser("status", help="Show migration status")
    status_parser.set_defaults(func=cmd_status)

    # migrate command
    migrate_parser = subparsers.add_parser("migrate", help="Run migrations")
    migrate_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be migrated without making changes",
    )
    migrate_parser.add_argument(
        "-y", "--yes",
        action="store_true",
        help="Skip confirmation prompt",
    )
    migrate_parser.set_defaults(func=cmd_migrate)

    # list command
    list_parser = subparsers.add_parser("list", help="List available migrations")
    list_parser.set_defaults(func=cmd_list)

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 1

    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

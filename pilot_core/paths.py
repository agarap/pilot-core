"""
Path discovery for pilot-core and dependent repositories.

This module provides the PathRegistry class which discovers and merges paths
from pilot-core (the installed package) and the user repository (where the
user has their custom agents, tools, rules, etc.).

Priority: User paths > Core paths (user can override core defaults)

Usage:
    from pilot_core.paths import PathRegistry

    paths = PathRegistry.discover()

    # Find an agent (user overrides core)
    agent_path = paths.find_agent("builder")

    # Iterate all agents (user first, then core)
    for agent_file in paths.iter_agents():
        print(agent_file)

    # Get all rules (additive, both user and core)
    for rule_file in paths.iter_rules():
        print(rule_file)
"""

from pathlib import Path
from typing import Iterator, Optional
import os


class PathRegistry:
    """
    Discovers and merges paths from pilot-core and user repository.

    Path resolution strategy:
    - Agents: User overrides core (same name = user wins)
    - Rules: Additive (both user and core rules apply)
    - Tools: User overrides core
    - Queries: User overrides core
    - Schemas: Core only (schemas define the standard)
    - Migrations: Core only (migrations are provided by core)
    """

    def __init__(self, core_root: Path, user_root: Path):
        """
        Initialize with explicit core and user roots.

        Args:
            core_root: Root of pilot-core (where lib/, agents/, etc. live)
            user_root: Root of user repository (current project)
        """
        self.core_root = core_root
        self.user_root = user_root

    @classmethod
    def discover(cls) -> "PathRegistry":
        """
        Auto-discover core and user roots.

        Core root is determined by:
        1. PILOT_CORE_ROOT environment variable
        2. Location of this file (lib/paths.py -> parent.parent)

        User root is determined by:
        1. PILOT_ROOT environment variable
        2. Current working directory
        """
        # Discover core root
        if os.environ.get("PILOT_CORE_ROOT"):
            core_root = Path(os.environ["PILOT_CORE_ROOT"])
        else:
            # This file is at lib/paths.py, so parent.parent is core root
            core_root = Path(__file__).parent.parent

        # Discover user root
        if os.environ.get("PILOT_ROOT"):
            user_root = Path(os.environ["PILOT_ROOT"])
        else:
            user_root = Path.cwd()

        return cls(core_root, user_root)

    def is_same_repo(self) -> bool:
        """Check if core and user are the same repo (development mode)."""
        try:
            return self.core_root.resolve() == self.user_root.resolve()
        except Exception:
            return False

    # -------------------------------------------------------------------------
    # Agent discovery
    # -------------------------------------------------------------------------

    def agents_dirs(self) -> list[Path]:
        """
        Return agent directories in priority order (user first, then core).

        Returns list of existing directories only.
        """
        dirs = []

        # User agents first (higher priority)
        user_agents = self.user_root / "agents"
        if user_agents.exists() and user_agents.is_dir():
            dirs.append(user_agents)

        # Core agents second (if not same repo)
        if not self.is_same_repo():
            core_agents = self.core_root / "agents"
            if core_agents.exists() and core_agents.is_dir():
                dirs.append(core_agents)

        return dirs

    def find_agent(self, name: str) -> Optional[Path]:
        """
        Find an agent by name.

        User agents override core agents with the same name.

        Args:
            name: Agent name (without .yaml extension)

        Returns:
            Path to agent YAML file, or None if not found
        """
        for agents_dir in self.agents_dirs():
            agent_path = agents_dir / f"{name}.yaml"
            if agent_path.exists():
                return agent_path
        return None

    def iter_agents(self) -> Iterator[Path]:
        """
        Iterate all agents (user first, skip core if overridden).

        Yields Path to each agent YAML file. If user has an agent with
        the same name as core, only the user's version is yielded.
        """
        seen = set()
        for agents_dir in self.agents_dirs():
            for agent_file in agents_dir.glob("*.yaml"):
                if agent_file.stem not in seen:
                    seen.add(agent_file.stem)
                    yield agent_file

    def list_agents(self) -> list[str]:
        """Return list of all available agent names."""
        return [p.stem for p in self.iter_agents()]

    # -------------------------------------------------------------------------
    # Rules discovery (additive - both apply)
    # -------------------------------------------------------------------------

    def rules_dirs(self) -> list[Path]:
        """
        Return rules directories (both user and core, additive).

        Rules are additive: user rules ADD to core rules, they don't override.
        """
        dirs = []

        # User rules
        user_rules = self.user_root / "system" / "rules"
        if user_rules.exists() and user_rules.is_dir():
            dirs.append(user_rules)

        # Core rules (if not same repo)
        if not self.is_same_repo():
            core_rules = self.core_root / "system" / "rules"
            if core_rules.exists() and core_rules.is_dir():
                dirs.append(core_rules)

        return dirs

    def iter_rules(self) -> Iterator[Path]:
        """
        Iterate all rules from all sources.

        Rules are additive - both user and core rules are included.
        If same name exists in both, user version takes precedence.
        """
        seen = set()
        for rules_dir in self.rules_dirs():
            for rule_file in rules_dir.glob("*.yaml"):
                if rule_file.stem not in seen:
                    seen.add(rule_file.stem)
                    yield rule_file

    # -------------------------------------------------------------------------
    # Tools discovery
    # -------------------------------------------------------------------------

    def tools_dirs(self) -> list[Path]:
        """Return tools directories in priority order."""
        dirs = []

        user_tools = self.user_root / "tools"
        if user_tools.exists() and user_tools.is_dir():
            dirs.append(user_tools)

        if not self.is_same_repo():
            core_tools = self.core_root / "tools"
            if core_tools.exists() and core_tools.is_dir():
                dirs.append(core_tools)

        return dirs

    def find_tool(self, name: str) -> Optional[Path]:
        """Find a tool by name (user overrides core)."""
        for tools_dir in self.tools_dirs():
            # Try both {name}.py and {name}/__init__.py
            tool_path = tools_dir / f"{name}.py"
            if tool_path.exists():
                return tool_path

            tool_dir = tools_dir / name
            if tool_dir.is_dir() and (tool_dir / "__init__.py").exists():
                return tool_dir / "__init__.py"

        return None

    def iter_tools(self) -> Iterator[Path]:
        """Iterate all tool modules (user first, skip core if overridden)."""
        seen = set()
        for tools_dir in self.tools_dirs():
            for tool_file in tools_dir.glob("*.py"):
                if tool_file.stem.startswith("_"):
                    continue
                if tool_file.stem not in seen:
                    seen.add(tool_file.stem)
                    yield tool_file

    # -------------------------------------------------------------------------
    # Queries discovery
    # -------------------------------------------------------------------------

    def queries_dirs(self) -> list[Path]:
        """Return queries directories in priority order."""
        dirs = []

        user_queries = self.user_root / "system" / "queries"
        if user_queries.exists() and user_queries.is_dir():
            dirs.append(user_queries)

        if not self.is_same_repo():
            core_queries = self.core_root / "system" / "queries"
            if core_queries.exists() and core_queries.is_dir():
                dirs.append(core_queries)

        return dirs

    def find_query(self, name: str) -> Optional[Path]:
        """Find a query template by name."""
        for queries_dir in self.queries_dirs():
            query_path = queries_dir / f"{name}.sql"
            if query_path.exists():
                return query_path
        return None

    # -------------------------------------------------------------------------
    # Schemas (core only - they define the standard)
    # -------------------------------------------------------------------------

    def schemas_dir(self) -> Optional[Path]:
        """Return the schemas directory (core only)."""
        schemas_dir = self.core_root / "system" / "schemas"
        if schemas_dir.exists() and schemas_dir.is_dir():
            return schemas_dir
        return None

    def find_schema(self, schema_type: str, version: int) -> Optional[Path]:
        """Find a schema file by type and version."""
        schemas_dir = self.schemas_dir()
        if not schemas_dir:
            return None

        schema_path = schemas_dir / f"{schema_type}.v{version}.yaml"
        if schema_path.exists():
            return schema_path
        return None

    # -------------------------------------------------------------------------
    # Migrations (core only - they define transformations)
    # -------------------------------------------------------------------------

    def migrations_dir(self) -> Optional[Path]:
        """Return the migrations directory (core only)."""
        migrations_dir = self.core_root / "system" / "migrations"
        if migrations_dir.exists() and migrations_dir.is_dir():
            return migrations_dir
        return None

    def iter_migrations(self) -> Iterator[Path]:
        """Iterate all migration definitions."""
        migrations_dir = self.migrations_dir()
        if migrations_dir:
            yield from migrations_dir.glob("*.yaml")

    # -------------------------------------------------------------------------
    # Data and index paths
    # -------------------------------------------------------------------------

    def index_path(self) -> Path:
        """Return the path to the index file (user repo)."""
        return self.user_root / "data" / "index.json"

    def data_dir(self) -> Path:
        """Return the data directory (user repo)."""
        return self.user_root / "data"

    def logs_dir(self) -> Path:
        """Return the logs directory (user repo)."""
        return self.user_root / "logs"

    def projects_dir(self) -> Path:
        """Return the projects directory (user repo)."""
        return self.user_root / "projects"

    # -------------------------------------------------------------------------
    # Utility methods
    # -------------------------------------------------------------------------

    def to_dict(self) -> dict:
        """Return a dict representation for debugging."""
        return {
            "core_root": str(self.core_root),
            "user_root": str(self.user_root),
            "is_same_repo": self.is_same_repo(),
            "agents_dirs": [str(p) for p in self.agents_dirs()],
            "rules_dirs": [str(p) for p in self.rules_dirs()],
            "tools_dirs": [str(p) for p in self.tools_dirs()],
            "available_agents": self.list_agents(),
        }


# Global singleton for convenience
_registry: Optional[PathRegistry] = None


def get_registry() -> PathRegistry:
    """Get the global PathRegistry singleton."""
    global _registry
    if _registry is None:
        _registry = PathRegistry.discover()
    return _registry


def reset_registry():
    """Reset the global registry (useful for testing)."""
    global _registry
    _registry = None


if __name__ == "__main__":
    import json

    paths = PathRegistry.discover()
    print(json.dumps(paths.to_dict(), indent=2))

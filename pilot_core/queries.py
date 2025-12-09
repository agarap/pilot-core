"""
SQL template loader and executor for DuckDB queries.

Loads SQL templates from system/queries/{name}.sql and executes them
with parameter substitution using DuckDB's native parameter binding.

Usage:
    from pilot_core.queries import load_query, execute_query

    # Load a template
    sql = load_query('rules_for_agent')
    # Returns: 'SELECT ... WHERE agent = :agent_name ...'

    # Execute with parameters
    results = execute_query('rules_for_agent', {'agent_name': 'builder'})
    # Returns: [{'name': 'git-review-required', ...}, ...]

    # Clear cache if templates change
    clear_cache()
"""

from pathlib import Path
from typing import Optional

import duckdb

# Module-level cache for loaded templates
_template_cache: dict[str, str] = {}

# Path to SQL templates directory
QUERIES_DIR = Path("system/queries")

# Path to index file (same as lib/search.py)
INDEX_PATH = Path("data/index.json")


class QueryError(Exception):
    """Raised when query loading or execution fails."""
    pass


class TemplateNotFoundError(QueryError):
    """Raised when a SQL template file is not found."""
    pass


def load_query(name: str, use_cache: bool = True) -> str:
    """
    Load a SQL template from system/queries/{name}.sql.

    Args:
        name: Template name (without .sql extension)
        use_cache: Whether to use cached template (default True)

    Returns:
        SQL template string with :param_name style parameters

    Raises:
        TemplateNotFoundError: If template file doesn't exist
    """
    # Check cache first
    if use_cache and name in _template_cache:
        return _template_cache[name]

    # Build path to template
    template_path = QUERIES_DIR / f"{name}.sql"

    if not template_path.exists():
        available = list_templates()
        raise TemplateNotFoundError(
            f"SQL template '{name}' not found at {template_path}. "
            f"Available templates: {', '.join(available) if available else 'none'}"
        )

    # Load template
    sql = template_path.read_text()

    # Cache it
    if use_cache:
        _template_cache[name] = sql

    return sql


def execute_query(
    name: str,
    params: Optional[dict] = None,
    use_cache: bool = True
) -> list[dict]:
    """
    Load and execute a SQL template with parameters.

    Uses DuckDB's native parameter binding for security (not string interpolation).

    Args:
        name: Template name (without .sql extension)
        params: Dictionary of parameter values (keys match :param_name in SQL)
        use_cache: Whether to use cached template (default True)

    Returns:
        List of result rows as dictionaries

    Raises:
        TemplateNotFoundError: If template file doesn't exist
        QueryError: If query execution fails
    """
    # Load the template
    sql = load_query(name, use_cache=use_cache)

    # Execute the query
    return execute_sql(sql, params)


def _convert_params_to_duckdb(sql: str, params: dict) -> tuple[str, dict]:
    """
    Convert :param_name style parameters to $param_name for DuckDB.

    DuckDB uses $name syntax for named parameters, but our SQL templates
    use :name style (more common in other databases).

    Args:
        sql: SQL with :param_name style parameters
        params: Dictionary of parameter values

    Returns:
        Tuple of (converted_sql, params_dict)
    """
    import re

    # Find all :param_name patterns and convert to $param_name
    # Be careful not to match :: (cast operator) or strings
    pattern = r'(?<![:\w]):([a-zA-Z_][a-zA-Z0-9_]*)'

    converted_sql = re.sub(pattern, r'$\1', sql)

    return converted_sql, params


def _fix_json_read_size(sql: str) -> str:
    """
    Add maximum_object_size to read_json_auto calls if not present.

    The index.json file with embeddings can be large (>16MB), so we need
    to increase the default limit for read_json_auto.

    Args:
        sql: SQL query string

    Returns:
        SQL with maximum_object_size added to read_json_auto calls
    """
    import re

    # Only modify if maximum_object_size is not already present
    if "maximum_object_size" in sql:
        return sql

    # Pattern to find read_json_auto calls with just a path (no options)
    # Match read_json_auto('path') where there's no second argument
    pattern = r"read_json_auto\s*\(\s*'([^']+)'\s*\)"

    def add_size_option(match):
        path = match.group(1)
        return f"read_json_auto('{path}', maximum_object_size=50000000)"

    return re.sub(pattern, add_size_option, sql)


def execute_sql(sql: str, params: Optional[dict] = None) -> list[dict]:
    """
    Execute a SQL string directly with parameters.

    Useful for one-off queries or when you've already loaded the template.
    Converts :param_name style to $param_name for DuckDB compatibility.

    Args:
        sql: SQL query string with :param_name style parameters
        params: Dictionary of parameter values

    Returns:
        List of result rows as dictionaries

    Raises:
        QueryError: If query execution fails
    """
    params = params or {}

    try:
        # Convert :param_name to $param_name for DuckDB
        converted_sql, converted_params = _convert_params_to_duckdb(sql, params)

        # Fix read_json_auto calls to handle large files
        converted_sql = _fix_json_read_size(converted_sql)

        # Create in-memory DuckDB connection
        con = duckdb.connect(":memory:")

        # Execute with parameter binding
        result = con.execute(converted_sql, converted_params)

        # Get column names from description
        columns = [desc[0] for desc in result.description]

        # Fetch all rows and convert to dicts
        rows = result.fetchall()
        return [dict(zip(columns, row)) for row in rows]

    except duckdb.Error as e:
        raise QueryError(f"Query execution failed: {e}") from e
    except Exception as e:
        raise QueryError(f"Unexpected error executing query: {e}") from e


def list_templates() -> list[str]:
    """
    List all available SQL templates.

    Returns:
        List of template names (without .sql extension)
    """
    if not QUERIES_DIR.exists():
        return []

    return sorted(
        p.stem for p in QUERIES_DIR.glob("*.sql")
    )


def clear_cache() -> None:
    """Clear the template cache."""
    _template_cache.clear()


def get_template_info(name: str) -> dict:
    """
    Get information about a SQL template.

    Parses the template comments for usage info and extracts parameters.

    Args:
        name: Template name (without .sql extension)

    Returns:
        Dictionary with template metadata:
        - name: Template name
        - path: Path to template file
        - description: First comment line if present
        - parameters: List of :param_name parameters found
        - sql: The raw SQL template
    """
    sql = load_query(name)

    # Extract description from first comment line
    description = ""
    for line in sql.split("\n"):
        line = line.strip()
        if line.startswith("--"):
            description = line[2:].strip()
            break
        elif line and not line.startswith("--"):
            break

    # Extract parameter names (:param_name pattern)
    import re
    param_pattern = r':([a-zA-Z_][a-zA-Z0-9_]*)'
    parameters = sorted(set(re.findall(param_pattern, sql)))

    return {
        "name": name,
        "path": str(QUERIES_DIR / f"{name}.sql"),
        "description": description,
        "parameters": parameters,
        "sql": sql,
    }


if __name__ == "__main__":
    # Test the module
    import sys

    print("Available SQL templates:")
    for template in list_templates():
        info = get_template_info(template)
        params = ", ".join(f":{p}" for p in info["parameters"]) or "none"
        print(f"  {template}: {info['description'][:60]}... (params: {params})")

    # Test execution if index exists
    if INDEX_PATH.exists():
        print("\n--- Testing execute_query ---")

        # Test search_content template
        try:
            results = execute_query("search_content", {"query": "web", "limit": 3})
            print(f"\nsearch_content('web', limit=3): {len(results)} results")
            for r in results[:3]:
                print(f"  - {r.get('name', 'N/A')}: {r.get('type', 'N/A')}")
        except QueryError as e:
            print(f"Error: {e}")

        # Test rules_for_agent template
        try:
            results = execute_query("rules_for_agent", {"agent_name": "builder"})
            print(f"\nrules_for_agent('builder'): {len(results)} results")
            for r in results[:3]:
                print(f"  - {r.get('name', 'N/A')}: priority={r.get('priority', 'N/A')}")
        except QueryError as e:
            print(f"Error: {e}")
    else:
        print(f"\n(Skipping execution tests: {INDEX_PATH} not found)")

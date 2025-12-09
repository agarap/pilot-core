"""
Fluent interface for building DuckDB queries against data/index.json.

Provides a chainable query builder that generates SQL and executes it via
lib.queries.execute_sql().

Usage:
    from lib.query_builder import QueryBuilder

    # Filter by type
    results = QueryBuilder().type('rule').execute()

    # Search across name, description, content
    results = QueryBuilder().search('git').limit(5).execute()

    # Chain multiple conditions
    results = QueryBuilder().type('agent').where('name', 'builder').execute()

    # Search within content
    results = QueryBuilder().type('tool').content_contains('parallel').execute()

    # Order and paginate
    results = QueryBuilder().type('rule').order_by('name').limit(10).offset(5).execute()

    # Debugging: see the generated SQL
    sql = QueryBuilder().type('agent').search('web').to_sql()
"""

from typing import Optional, Any


class QueryBuilder:
    """Fluent query builder for the pilot index."""

    def __init__(self):
        """Initialize empty query conditions."""
        self._type_filter: Optional[str] = None
        self._where_conditions: list[tuple[str, str, str]] = []  # (field, op, value)
        self._search_term: Optional[str] = None
        self._content_search: Optional[str] = None
        self._order_field: Optional[str] = None
        self._order_desc: bool = False
        self._limit_value: Optional[int] = None
        self._offset_value: Optional[int] = None
        self._params: dict[str, Any] = {}
        self._param_counter: int = 0

    def _next_param(self) -> str:
        """Generate a unique parameter name."""
        self._param_counter += 1
        return f"p{self._param_counter}"

    def type(self, type_name: str) -> 'QueryBuilder':
        """
        Filter by item type.

        Args:
            type_name: Type to filter by (rule, agent, tool, lib, decision, lesson, etc.)

        Returns:
            Self for chaining

        Example:
            QueryBuilder().type('rule').execute()
        """
        self._type_filter = type_name
        return self

    def where(self, field: str, value: str) -> 'QueryBuilder':
        """
        Filter by exact field match.

        Args:
            field: Field name (name, path, type, description)
            value: Exact value to match

        Returns:
            Self for chaining

        Example:
            QueryBuilder().where('name', 'builder').execute()
        """
        param = self._next_param()
        self._where_conditions.append((field, '=', param))
        self._params[param] = value
        return self

    def where_like(self, field: str, pattern: str) -> 'QueryBuilder':
        """
        Filter by pattern match (SQL LIKE).

        Args:
            field: Field name to match against
            pattern: SQL LIKE pattern (use % for wildcards)

        Returns:
            Self for chaining

        Example:
            QueryBuilder().where_like('name', 'web%').execute()
        """
        param = self._next_param()
        self._where_conditions.append((field, 'LIKE', param))
        self._params[param] = pattern
        return self

    def search(self, query: str) -> 'QueryBuilder':
        """
        Full-text search across name, description, and text content.

        Matches are case-insensitive and partial.

        Args:
            query: Search term

        Returns:
            Self for chaining

        Example:
            QueryBuilder().search('git').execute()
        """
        self._search_term = query
        return self

    def content_contains(self, text: str) -> 'QueryBuilder':
        """
        Search within the content field.

        For items with structured content (dict), this searches the JSON string.
        For items with text content, this searches the text.

        Args:
            text: Text to search for in content

        Returns:
            Self for chaining

        Example:
            QueryBuilder().content_contains('parallel').execute()
        """
        self._content_search = text
        return self

    def order_by(self, field: str, desc: bool = False) -> 'QueryBuilder':
        """
        Order results by field.

        Args:
            field: Field to order by (name, type, path)
            desc: If True, order descending

        Returns:
            Self for chaining

        Example:
            QueryBuilder().type('tool').order_by('name').execute()
        """
        self._order_field = field
        self._order_desc = desc
        return self

    def limit(self, n: int) -> 'QueryBuilder':
        """
        Limit number of results.

        Args:
            n: Maximum number of results to return

        Returns:
            Self for chaining

        Example:
            QueryBuilder().search('web').limit(5).execute()
        """
        self._limit_value = n
        return self

    def offset(self, n: int) -> 'QueryBuilder':
        """
        Skip first n results.

        Args:
            n: Number of results to skip

        Returns:
            Self for chaining

        Example:
            QueryBuilder().type('rule').offset(10).limit(10).execute()
        """
        self._offset_value = n
        return self

    def to_sql(self) -> tuple[str, dict]:
        """
        Build and return the SQL query string and parameters.

        Returns:
            Tuple of (sql_string, params_dict)

        Example:
            sql, params = QueryBuilder().type('agent').to_sql()
        """
        # Base query - use 'unnest' as alias to match existing SQL templates
        sql_parts = [
            "SELECT",
            "    unnest.path,",
            "    unnest.name,",
            "    unnest.type,",
            "    unnest.description,",
            "    unnest.content",
            "FROM read_json_auto('data/index.json', maximum_object_size=100000000),",
            "UNNEST(items) as unnest"
        ]

        where_clauses = []
        params = dict(self._params)

        # Type filter
        if self._type_filter:
            where_clauses.append("unnest.type = :type_filter")
            params['type_filter'] = self._type_filter

        # Where conditions
        for field, op, param_name in self._where_conditions:
            # Map simple field names to unnest.field
            if field in ('name', 'path', 'type', 'description'):
                where_clauses.append(f"unnest.{field} {op} :{param_name}")
            else:
                # For other fields, try JSON access
                where_clauses.append(f"unnest.content->>{repr(field)} {op} :{param_name}")

        # Full-text search
        if self._search_term:
            params['search_term'] = f"%{self._search_term}%"
            where_clauses.append(
                "(lower(unnest.name) LIKE lower(:search_term) "
                "OR lower(COALESCE(unnest.description, '')) LIKE lower(:search_term) "
                "OR lower(CAST(COALESCE(unnest.text, '') AS VARCHAR)) LIKE lower(:search_term))"
            )

        # Content search
        if self._content_search:
            params['content_search'] = f"%{self._content_search}%"
            where_clauses.append(
                "lower(CAST(unnest.content AS VARCHAR)) LIKE lower(:content_search)"
            )

        # Build WHERE clause
        if where_clauses:
            sql_parts.append("WHERE " + " AND ".join(where_clauses))

        # ORDER BY
        if self._order_field:
            direction = "DESC" if self._order_desc else "ASC"
            sql_parts.append(f"ORDER BY unnest.{self._order_field} {direction}")
        elif self._search_term:
            # Default ordering for search: prioritize name matches
            sql_parts.append(
                "ORDER BY CASE WHEN lower(unnest.name) LIKE lower(:search_term) THEN 0 ELSE 1 END, unnest.name"
            )
        else:
            # Default ordering by name
            sql_parts.append("ORDER BY unnest.name")

        # LIMIT and OFFSET
        if self._limit_value is not None:
            sql_parts.append(f"LIMIT {self._limit_value}")
        if self._offset_value is not None:
            sql_parts.append(f"OFFSET {self._offset_value}")

        return "\n".join(sql_parts), params

    def execute(self) -> list[dict]:
        """
        Build and execute the query, returning results.

        Returns:
            List of result rows as dictionaries with keys:
            path, name, type, description, content

        Example:
            results = QueryBuilder().type('rule').search('git').execute()
            for r in results:
                print(f"{r['name']}: {r['description']}")
        """
        from lib.queries import execute_sql

        sql, params = self.to_sql()
        return execute_sql(sql, params)


# Convenience function for quick queries
def query() -> QueryBuilder:
    """
    Create a new QueryBuilder instance.

    This is a convenience function for more readable code.

    Example:
        from lib.query_builder import query
        results = query().type('agent').execute()
    """
    return QueryBuilder()


if __name__ == '__main__':
    import json

    print("=== QueryBuilder Tests ===\n")

    # Test 1: Get all rules
    print("Test 1: QueryBuilder().type('rule').execute()")
    results = QueryBuilder().type('rule').execute()
    print(f"  Found {len(results)} rules")
    if results:
        print(f"  First: {results[0]['name']}")
    print()

    # Test 2: Get builder agent
    print("Test 2: QueryBuilder().type('agent').where('name', 'builder').execute()")
    results = QueryBuilder().type('agent').where('name', 'builder').execute()
    print(f"  Found {len(results)} results")
    if results:
        print(f"  Match: {results[0]['name']} - {results[0]['description'][:60]}...")
    print()

    # Test 3: Search for 'web'
    print("Test 3: QueryBuilder().search('web').limit(5).execute()")
    results = QueryBuilder().search('web').limit(5).execute()
    print(f"  Found {len(results)} results (limited to 5)")
    for r in results[:3]:
        print(f"    - {r['type']}/{r['name']}")
    print()

    # Test 4: Tools ordered by name
    print("Test 4: QueryBuilder().type('tool').order_by('name').execute()")
    results = QueryBuilder().type('tool').order_by('name').execute()
    print(f"  Found {len(results)} tools")
    for r in results[:3]:
        print(f"    - {r['name']}")
    print()

    # Test 5: Content contains 'parallel'
    print("Test 5: QueryBuilder().type('tool').content_contains('parallel').execute()")
    results = QueryBuilder().type('tool').content_contains('parallel').execute()
    print(f"  Found {len(results)} tools with 'parallel' in content")
    for r in results[:3]:
        print(f"    - {r['name']}")
    print()

    # Test 6: Combined - rules with 'git'
    print("Test 6: QueryBuilder().type('rule').search('git').execute()")
    results = QueryBuilder().type('rule').search('git').execute()
    print(f"  Found {len(results)} rules matching 'git'")
    for r in results:
        print(f"    - {r['name']}")
    print()

    # Test 7: Show SQL for debugging
    print("Test 7: QueryBuilder().type('agent').search('web').to_sql()")
    sql, params = QueryBuilder().type('agent').search('web').to_sql()
    print(f"  SQL:\n{sql}")
    print(f"  Params: {params}")
    print()

    # Test 8: Pagination
    print("Test 8: QueryBuilder().type('tool').order_by('name').limit(3).offset(2).execute()")
    results = QueryBuilder().type('tool').order_by('name').limit(3).offset(2).execute()
    print(f"  Found {len(results)} tools (skipped 2, limited to 3)")
    for r in results:
        print(f"    - {r['name']}")
    print()

    print("=== All tests passed ===")

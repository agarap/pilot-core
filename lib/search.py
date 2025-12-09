"""
Search utilities for querying the pilot system index.

Provides:
- Keyword search across all indexed items
- Vector similarity search (when embeddings available)
- Type-filtered queries
- Full-text search

Usage:
    from lib.search import search, search_by_type, similar_to

    # Keyword search
    results = search("web search tool")

    # Search specific types
    results = search_by_type("rule", "code review")

    # Vector similarity (requires embeddings)
    results = similar_to("How do I make API calls?")
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import duckdb

from .embed import embed


INDEX_PATH = Path("data/index.json")


@dataclass
class SearchResult:
    """A search result with relevance score."""
    path: str
    name: str
    type: str
    description: str
    score: float
    content: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "name": self.name,
            "type": self.type,
            "description": self.description,
            "score": self.score,
            "content": self.content,
        }


def get_connection() -> duckdb.DuckDBPyConnection:
    """Get a DuckDB connection with the index loaded."""
    con = duckdb.connect(":memory:")

    if not INDEX_PATH.exists():
        return con

    # Create view for easier querying
    # Use maximum_object_size to handle large index files with full text content
    con.execute(f"""
        CREATE VIEW index_items AS
        SELECT * FROM (
            SELECT unnest(items) as item
            FROM read_json_auto('{INDEX_PATH}', maximum_object_size=200000000)
        )
    """)

    return con


def search(query: str, limit: int = 10, types: Optional[list[str]] = None) -> list[SearchResult]:
    """
    Search the index using keyword matching.

    Searches across: name, description, text, content, tags.
    Multi-word queries search for each term and aggregate scores.

    Args:
        query: Search query string (can be multi-word)
        limit: Maximum results to return
        types: Optional list of types to filter by

    Returns:
        List of SearchResult ordered by relevance
    """
    if not INDEX_PATH.exists():
        return []

    con = get_connection()

    # Build type filter if specified
    type_filter = ""
    if types:
        type_list = ", ".join(f"'{t}'" for t in types)
        type_filter = f"AND type IN ({type_list})"

    # Split query into terms for better matching
    terms = [t.strip() for t in query.split() if len(t.strip()) >= 2]
    if not terms:
        terms = [query]  # Fall back to original query

    # Build scoring that sums scores for each matching term
    # This allows multi-word queries to match documents with any of the terms
    score_parts = []
    params = []
    for term in terms[:5]:  # Limit to 5 terms to avoid query explosion
        score_parts.append("""
            CASE
                WHEN lower(item.name) LIKE lower('%' || ? || '%') THEN 10
                WHEN lower(item.description) LIKE lower('%' || ? || '%') THEN 5
                WHEN lower(COALESCE(item.text, '')) LIKE lower('%' || ? || '%') THEN 3
                WHEN lower(CAST(item.content AS VARCHAR)) LIKE lower('%' || ? || '%') THEN 2
                WHEN lower(CAST(item.tags AS VARCHAR)) LIKE lower('%' || ? || '%') THEN 1
                ELSE 0
            END
        """)
        params.extend([term, term, term, term, term])

    # Sum scores across all terms
    score_expr = " + ".join(score_parts) if score_parts else "0"

    sql = f"""
        SELECT path, name, type, description, score, content
        FROM (
            SELECT
                item.path as path,
                item.name as name,
                item.type as type,
                item.description as description,
                ({score_expr}) as score,
                left(COALESCE(item.text, CAST(item.content AS VARCHAR)), 500) as content
            FROM index_items
        ) scored
        WHERE score > 0 {type_filter}
        ORDER BY score DESC
        LIMIT ?
    """
    params.append(limit)

    try:
        results = con.execute(sql, params).fetchall()
        return [
            SearchResult(
                path=r[0],
                name=r[1],
                type=r[2],
                description=r[3],
                score=r[4],
                content=r[5],
            )
            for r in results
        ]
    except Exception as e:
        print(f"Search error: {e}")
        return []


def search_by_type(item_type: str, query: Optional[str] = None, limit: int = 20) -> list[SearchResult]:
    """
    Search for items of a specific type.

    Args:
        item_type: Type to filter by (subagent, rule, tool, lib, decision, fact, lesson, run)
        query: Optional keyword to search within type
        limit: Maximum results

    Returns:
        List of SearchResult
    """
    if not INDEX_PATH.exists():
        return []

    con = get_connection()

    if query:
        sql = """
            SELECT
                item.path as path,
                item.name as name,
                item.type as type,
                item.description as description,
                1.0 as score,
                left(COALESCE(item.text, CAST(item.content AS VARCHAR)), 500) as content
            FROM index_items
            WHERE item.type = ?
            AND (
                lower(item.name) LIKE lower('%' || ? || '%')
                OR lower(item.description) LIKE lower('%' || ? || '%')
                OR lower(COALESCE(item.text, '')) LIKE lower('%' || ? || '%')
                OR lower(CAST(item.content AS VARCHAR)) LIKE lower('%' || ? || '%')
            )
            LIMIT ?
        """
        params = [item_type, query, query, query, query, limit]
    else:
        sql = """
            SELECT
                item.path as path,
                item.name as name,
                item.type as type,
                item.description as description,
                1.0 as score,
                left(COALESCE(item.text, CAST(item.content AS VARCHAR)), 500) as content
            FROM index_items
            WHERE item.type = ?
            LIMIT ?
        """
        params = [item_type, limit]

    try:
        results = con.execute(sql, params).fetchall()
        return [
            SearchResult(
                path=r[0],
                name=r[1],
                type=r[2],
                description=r[3],
                score=r[4],
                content=r[5],
            )
            for r in results
        ]
    except Exception as e:
        print(f"Search error: {e}")
        return []


def similar_to(text: str, limit: int = 5) -> list[SearchResult]:
    """
    Find items similar to the given text using vector similarity.

    Requires embeddings to be populated in the index.

    Args:
        text: Text to find similar items to
        limit: Maximum results

    Returns:
        List of SearchResult ordered by similarity
    """
    if not INDEX_PATH.exists():
        return []

    # Generate embedding for query
    query_embedding = embed(text)
    if not query_embedding:
        # Fall back to keyword search if no embeddings
        return search(text, limit)

    con = get_connection()

    # Use cosine similarity for vector search
    # DuckDB supports list_cosine_similarity
    sql = """
        SELECT
            item.path as path,
            item.name as name,
            item.type as type,
            item.description as description,
            list_cosine_similarity(item.embedding, ?) as score,
            left(CAST(item.content AS VARCHAR), 500) as content
        FROM index_items
        WHERE item.embedding IS NOT NULL
        AND len(item.embedding) > 0
        ORDER BY score DESC
        LIMIT ?
    """

    try:
        results = con.execute(sql, [query_embedding, limit]).fetchall()
        return [
            SearchResult(
                path=r[0],
                name=r[1],
                type=r[2],
                description=r[3],
                score=r[4] or 0.0,
                content=r[5],
            )
            for r in results
        ]
    except Exception as e:
        print(f"Vector search error: {e}")
        # Fall back to keyword search
        return search(text, limit)


def get_all_rules() -> list[dict]:
    """Get all rules, ordered by priority."""
    if not INDEX_PATH.exists():
        return []

    con = get_connection()

    # Content is stored as JSON, extract priority from content.priority
    sql = """
        SELECT
            item.name,
            item.description,
            item.content.priority as priority,
            item.content.when as applies_to,
            item.content.rule as rule_text,
            item.path
        FROM index_items
        WHERE item.type = 'rule'
        ORDER BY priority DESC NULLS LAST
    """

    try:
        results = con.execute(sql).fetchall()
        return [
            {
                "name": r[0],
                "description": r[1],
                "priority": r[2],
                "applies_to": r[3],
                "rule_text": r[4],
                "path": r[5],
            }
            for r in results
        ]
    except Exception as e:
        print(f"Error getting rules: {e}")
        return []


def get_recent_runs(project: Optional[str] = None, limit: int = 10) -> list[dict]:
    """Get recent runs, optionally filtered by project."""
    if not INDEX_PATH.exists():
        return []

    con = get_connection()

    # Content is stored as JSON, extract fields from content
    if project:
        sql = """
            SELECT
                item.name,
                item.content.project as project,
                item.content.task as task,
                item.content.status as status,
                item.content.id as run_id,
                item.content.agents as agents,
                item.path
            FROM index_items
            WHERE item.type = 'run' AND item.content.project = ?
            ORDER BY item.name DESC
            LIMIT ?
        """
        params = [project, limit]
    else:
        sql = """
            SELECT
                item.name,
                item.content.project as project,
                item.content.task as task,
                item.content.status as status,
                item.content.id as run_id,
                item.content.agents as agents,
                item.path
            FROM index_items
            WHERE item.type = 'run'
            ORDER BY item.name DESC
            LIMIT ?
        """
        params = [limit]

    try:
        results = con.execute(sql, params).fetchall()
        return [
            {
                "name": r[0],
                "project": r[1],
                "task": r[2],
                "status": r[3],
                "run_id": r[4],
                "agents": r[5],
                "path": r[6],
            }
            for r in results
        ]
    except Exception as e:
        print(f"Error getting runs: {e}")
        return []


def list_types() -> dict[str, int]:
    """List all indexed types and their counts."""
    if not INDEX_PATH.exists():
        return {}

    con = get_connection()

    sql = """
        SELECT item.type, count(*) as count
        FROM index_items
        GROUP BY item.type
        ORDER BY count DESC
    """

    try:
        results = con.execute(sql).fetchall()
        return {r[0]: r[1] for r in results}
    except Exception as e:
        print(f"Error listing types: {e}")
        return {}


if __name__ == "__main__":
    # Test search functionality
    print("Index types:", list_types())
    print("\nSearch 'web':", [r.name for r in search("web")])
    print("\nRules:", [r["name"] for r in get_all_rules()])

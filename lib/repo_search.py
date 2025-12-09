"""
Comprehensive repository search module - THE unified search API for all agents.

Provides exhaustive search capabilities over all repository data:
- Keyword search (multi-term, scored)
- Semantic/vector similarity search
- Regular expression pattern matching
- Structured field queries
- Raw SQL for advanced queries

Usage:
    from lib.repo_search import find, context_for, search_everything

    # Quick search
    results = find("web search tool")

    # Get comprehensive context before starting work
    context = context_for("implement feature X")

    # Run ALL search methods exhaustively
    all_results = search_everything("topic")

This module auto-rebuilds the index if missing or stale.
"""

import ast
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

import duckdb

from .embed import embed
from .index import index_all

INDEX_PATH = Path("data/index.json")

# Auto-rebuild threshold: if index is older than this many seconds, rebuild
INDEX_STALE_SECONDS = 3600  # 1 hour


def _ensure_index() -> bool:
    """Ensure the index exists and is reasonably fresh. Auto-rebuild if needed."""
    if not INDEX_PATH.exists():
        print("Index not found, building...")
        index_all()
        return True

    # Check if index is stale
    try:
        with open(INDEX_PATH) as f:
            data = json.load(f)
            generated_at = data.get("generated_at", "")
            if generated_at:
                gen_time = datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
                age = (datetime.now() - gen_time.replace(tzinfo=None)).total_seconds()
                if age > INDEX_STALE_SECONDS:
                    print(f"Index is {age/3600:.1f}h old, rebuilding...")
                    index_all()
                    return True
    except Exception:
        pass  # If we can't check, assume it's fine

    return True


def _get_connection() -> duckdb.DuckDBPyConnection:
    """Get a DuckDB connection with the index loaded."""
    _ensure_index()

    con = duckdb.connect(":memory:")

    if INDEX_PATH.exists():
        con.execute(f"""
            CREATE VIEW index_items AS
            SELECT * FROM (
                SELECT unnest(items) as item
                FROM read_json_auto('{INDEX_PATH}', maximum_object_size=200000000)
            )
        """)

    return con


# =============================================================================
# CORE SEARCH METHODS
# =============================================================================


def keyword(
    query: str, types: Optional[list[str]] = None, limit: int = 20
) -> list[dict]:
    """
    Multi-term keyword search across all indexed content.

    Searches: name, description, text, content, tags
    Scores results by relevance (name matches score highest).

    Args:
        query: Search query (can be multi-word)
        types: Optional list of types to filter by
        limit: Maximum results

    Returns:
        List of dicts with: path, name, type, description, score, content
    """
    if not INDEX_PATH.exists():
        _ensure_index()

    con = _get_connection()

    # Build type filter
    type_filter = ""
    if types:
        type_list = ", ".join(f"'{t}'" for t in types)
        type_filter = f"AND type IN ({type_list})"

    # Split query into terms
    terms = [t.strip() for t in query.split() if len(t.strip()) >= 2]
    if not terms:
        terms = [query]

    # Build scoring expression
    score_parts = []
    params = []
    for term in terms[:5]:
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
            {
                "path": r[0],
                "name": r[1],
                "type": r[2],
                "description": r[3],
                "score": r[4],
                "content": r[5],
            }
            for r in results
        ]
    except Exception as e:
        print(f"Keyword search error: {e}")
        return []


def semantic(query: str, limit: int = 10) -> list[dict]:
    """
    Vector similarity search using embeddings.

    Finds items semantically similar to the query text.
    Falls back to keyword search if embeddings unavailable.

    Args:
        query: Text to find similar items to
        limit: Maximum results

    Returns:
        List of dicts with: path, name, type, description, score, content
    """
    if not INDEX_PATH.exists():
        _ensure_index()

    query_embedding = embed(query)
    if not query_embedding:
        return keyword(query, limit=limit)

    con = _get_connection()

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
            {
                "path": r[0],
                "name": r[1],
                "type": r[2],
                "description": r[3],
                "score": r[4] or 0.0,
                "content": r[5],
            }
            for r in results
        ]
    except Exception as e:
        print(f"Semantic search error: {e}")
        return keyword(query, limit=limit)


def regex(
    pattern: str, types: Optional[list[str]] = None, limit: int = 50
) -> list[dict]:
    """
    Regular expression search across all content.

    Searches text and content fields with regex patterns.

    Args:
        pattern: Regular expression pattern
        types: Optional list of types to filter by
        limit: Maximum results

    Returns:
        List of dicts with: path, name, type, description, score, content
    """
    if not INDEX_PATH.exists():
        _ensure_index()

    con = _get_connection()

    type_filter = ""
    if types:
        type_list = ", ".join(f"'{t}'" for t in types)
        type_filter = f"AND item.type IN ({type_list})"

    sql = f"""
        SELECT
            item.path as path,
            item.name as name,
            item.type as type,
            item.description as description,
            1.0 as score,
            left(COALESCE(item.text, CAST(item.content AS VARCHAR)), 500) as content
        FROM index_items
        WHERE (
            regexp_matches(COALESCE(item.text, ''), ?)
            OR regexp_matches(CAST(item.content AS VARCHAR), ?)
            OR regexp_matches(item.name, ?)
        )
        {type_filter}
        LIMIT ?
    """

    try:
        results = con.execute(sql, [pattern, pattern, pattern, limit]).fetchall()
        return [
            {
                "path": r[0],
                "name": r[1],
                "type": r[2],
                "description": r[3],
                "score": r[4],
                "content": r[5],
            }
            for r in results
        ]
    except Exception as e:
        print(f"Regex search error: {e}")
        return []


def sql(query_str: str, params: Optional[dict] = None) -> list[dict]:
    """
    Execute raw SQL query against the index.

    For advanced queries that need full DuckDB power.
    The index is available as 'index_items' view with 'item' column.

    Args:
        query_str: SQL query string (use $param_name for parameters)
        params: Parameter values dict

    Returns:
        List of result dicts
    """
    if not INDEX_PATH.exists():
        _ensure_index()

    params = params or {}
    con = _get_connection()

    try:
        result = con.execute(query_str, params)
        columns = [desc[0] for desc in result.description]
        rows = result.fetchall()
        return [dict(zip(columns, row)) for row in rows]
    except Exception as e:
        print(f"SQL query error: {e}")
        return []


def structured(
    item_type: Optional[str] = None,
    field: Optional[str] = None,
    value: Optional[str] = None,
    limit: int = 50,
) -> list[dict]:
    """
    Structured field queries for filtering by type and field values.

    Args:
        item_type: Filter by type (agent, rule, tool, etc.)
        field: Field name to match on (in content JSON)
        value: Value to match for the field
        limit: Maximum results

    Returns:
        List of dicts with: path, name, type, description, score, content
    """
    if not INDEX_PATH.exists():
        _ensure_index()

    con = _get_connection()

    conditions = []
    params = []

    if item_type:
        conditions.append("item.type = ?")
        params.append(item_type)

    if field and value:
        # Query nested JSON field
        conditions.append(f"CAST(item.content->>'{field}' AS VARCHAR) LIKE ?")
        params.append(f"%{value}%")

    where_clause = " AND ".join(conditions) if conditions else "1=1"

    sql_query = f"""
        SELECT
            item.path as path,
            item.name as name,
            item.type as type,
            item.description as description,
            1.0 as score,
            left(CAST(item.content AS VARCHAR), 500) as content
        FROM index_items
        WHERE {where_clause}
        LIMIT ?
    """
    params.append(limit)

    try:
        results = con.execute(sql_query, params).fetchall()
        return [
            {
                "path": r[0],
                "name": r[1],
                "type": r[2],
                "description": r[3],
                "score": r[4],
                "content": r[5],
            }
            for r in results
        ]
    except Exception as e:
        print(f"Structured query error: {e}")
        return []


# =============================================================================
# CONVENIENCE FUNCTIONS FOR AGENTS
# =============================================================================


def find(query: str, limit: int = 10) -> list[dict]:
    """
    Smart search: combines keyword and semantic search, merges and dedupes results.

    This is the go-to function for general searching.

    Args:
        query: Search query
        limit: Maximum results

    Returns:
        Merged list of search results
    """
    # Run both searches
    kw_results = keyword(query, limit=limit)
    sem_results = semantic(query, limit=limit)

    # Merge and dedupe by path
    seen = set()
    merged = []

    for r in kw_results + sem_results:
        if r["path"] not in seen:
            seen.add(r["path"])
            merged.append(r)

    # Sort by score and return top results
    merged.sort(key=lambda x: x.get("score", 0), reverse=True)
    return merged[:limit]


def find_code(pattern: str, limit: int = 30) -> list[dict]:
    """
    Search code files by regex pattern.

    Optimized for finding functions, classes, imports, etc.

    Args:
        pattern: Regex pattern to search for
        limit: Maximum results

    Returns:
        List of matching code items
    """
    return regex(pattern, types=["code", "tool", "lib"], limit=limit)


def find_by_type(item_type: str, query: Optional[str] = None, limit: int = 50) -> list[dict]:
    """
    Find all items of a specific type, optionally filtered by query.

    Args:
        item_type: Type to search (agent, rule, tool, code, etc.)
        query: Optional keyword to filter within type
        limit: Maximum results

    Returns:
        List of matching items
    """
    if query:
        return keyword(query, types=[item_type], limit=limit)
    return structured(item_type=item_type, limit=limit)


def find_related(path: str, limit: int = 5) -> list[dict]:
    """
    Find items related to a given file path.

    Uses the file's content to find semantically similar items.

    Args:
        path: Path to the file to find related items for
        limit: Maximum results

    Returns:
        List of related items
    """
    try:
        file_path = Path(path)
        if file_path.exists():
            content = file_path.read_text()[:2000]
            return semantic(content, limit=limit)
    except Exception:
        pass

    # Fallback: search by filename
    name = Path(path).stem
    return find(name, limit=limit)


def context_for(task: str) -> str:
    """
    Generate comprehensive context string for a task.

    This is THE function agents should call before starting any work.
    Runs multiple searches and formats results for easy consumption.

    Args:
        task: Description of the task to gather context for

    Returns:
        Formatted string with all relevant context
    """
    lines = [f"# Context for: {task}", ""]

    # Keyword search
    kw = keyword(task, limit=5)
    if kw:
        lines.append("## Keyword Matches")
        for r in kw:
            lines.append(f"- **{r['name']}** ({r['type']}): {r['description'][:100]}")
            lines.append(f"  Path: {r['path']}")
        lines.append("")

    # Semantic search
    sem = semantic(task, limit=5)
    if sem:
        lines.append("## Semantically Related")
        for r in sem:
            if r["path"] not in [x["path"] for x in kw]:  # Dedupe
                lines.append(f"- **{r['name']}** ({r['type']}): {r['description'][:100]}")
                lines.append(f"  Path: {r['path']}")
        lines.append("")

    # Relevant rules
    rules = find_by_type("rule", task, limit=3)
    if rules:
        lines.append("## Relevant Rules")
        for r in rules:
            lines.append(f"- **{r['name']}**: {r['description'][:100]}")
        lines.append("")

    # Related decisions/lessons
    decisions = find_by_type("decision", task, limit=2)
    lessons = find_by_type("lesson", task, limit=2)
    if decisions or lessons:
        lines.append("## Knowledge Base")
        for r in decisions + lessons:
            lines.append(f"- **{r['name']}** ({r['type']}): {r['description'][:100]}")
        lines.append("")

    if len(lines) <= 2:
        lines.append("No relevant context found. Consider searching with different terms.")

    return "\n".join(lines)


def search_everything(query: str, limit: int = 20) -> dict:
    """
    Run ALL search methods exhaustively, return combined results.

    This is the most comprehensive search - use when you need to be thorough.

    Args:
        query: Search query
        limit: Maximum results per method

    Returns:
        Dict with results from each search method
    """
    return {
        "keyword": keyword(query, limit=limit),
        "semantic": semantic(query, limit=limit),
        "regex": regex(query, limit=limit) if len(query) >= 2 else [],
        "agents": find_by_type("agent", query, limit=10),
        "rules": find_by_type("rule", query, limit=10),
        "tools": find_by_type("tool", query, limit=10),
        "code": find_by_type("code", query, limit=10),
        "decisions": find_by_type("decision", query, limit=5),
        "lessons": find_by_type("lesson", query, limit=5),
        "research": find_by_type("deep_research", query, limit=5),
    }


def list_types() -> dict[str, int]:
    """List all indexed types and their counts."""
    if not INDEX_PATH.exists():
        _ensure_index()

    con = _get_connection()

    sql_query = """
        SELECT item.type, count(*) as count
        FROM index_items
        GROUP BY item.type
        ORDER BY count DESC
    """

    try:
        results = con.execute(sql_query).fetchall()
        return {r[0]: r[1] for r in results}
    except Exception as e:
        print(f"Error listing types: {e}")
        return {}


def rebuild_index() -> dict:
    """Force rebuild the index. Returns statistics."""
    result = index_all()
    return {
        "success": True,
        "count": result.get("count", 0),
        "generated_at": result.get("generated_at", ""),
    }


# =============================================================================
# CLI INTERFACE
# =============================================================================


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python -m lib.repo_search <query>")
        print("       python -m lib.repo_search --context <task>")
        print("       python -m lib.repo_search --all <query>")
        print("       python -m lib.repo_search --types")
        print("       python -m lib.repo_search --rebuild")
        sys.exit(1)

    if sys.argv[1] == "--types":
        types = list_types()
        print("Indexed types:")
        for t, count in types.items():
            print(f"  {t}: {count}")
    elif sys.argv[1] == "--rebuild":
        result = rebuild_index()
        print(f"Index rebuilt: {result['count']} items")
    elif sys.argv[1] == "--context" and len(sys.argv) > 2:
        task = " ".join(sys.argv[2:])
        print(context_for(task))
    elif sys.argv[1] == "--all" and len(sys.argv) > 2:
        query = " ".join(sys.argv[2:])
        results = search_everything(query)
        for method, items in results.items():
            if items:
                print(f"\n## {method} ({len(items)} results)")
                for item in items[:3]:
                    print(f"  - {item['name']}: {item['description'][:60]}...")
    else:
        query = " ".join(sys.argv[1:])
        results = find(query)
        print(f"Found {len(results)} results for '{query}':")
        for r in results:
            print(f"  - {r['name']} ({r['type']}): {r['description'][:60]}...")

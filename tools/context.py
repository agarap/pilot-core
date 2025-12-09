"""
tool: context
description: Gather relevant context from the filesystem before starting a task
parameters:
  query: Natural language description of what you're looking for
  types: Optional list of types to search (subagent, rule, tool, lib, decision, run)
  include_files: Whether to include file content previews (default true)
  max_results: Maximum results per source (default 5)
returns: Aggregated context from index search, grep, and file listings
"""

import json
import subprocess
import sys
from pathlib import Path
from typing import Optional

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from lib.search import search, search_by_type, similar_to, get_all_rules, list_types


def get_relevant_knowledge(query: str, max_results: int = 3) -> list[dict]:
    """
    Search for relevant lessons and decisions from knowledge/.

    Args:
        query: Search query to match against knowledge entries
        max_results: Maximum number of results to return

    Returns:
        List of knowledge entries sorted by relevance score
    """
    results = {}  # Use dict to dedupe by path

    # Extract meaningful terms from query (words > 3 chars)
    terms = [t for t in query.lower().split() if len(t) > 3]

    # Search for each term to improve matching
    for term in terms[:5]:  # Limit to 5 terms
        # Search lessons
        lessons = search_by_type("lesson", term, limit=max_results * 2)
        for lesson in lessons:
            if lesson.path not in results:
                results[lesson.path] = {
                    "type": "lesson",
                    "name": lesson.name,
                    "description": lesson.description,
                    "path": lesson.path,
                    "score": lesson.score,
                    "content": lesson.content,
                }
            else:
                # Boost score for multiple term matches
                results[lesson.path]["score"] += lesson.score

        # Search decisions
        decisions = search_by_type("decision", term, limit=max_results * 2)
        for decision in decisions:
            if decision.path not in results:
                results[decision.path] = {
                    "type": "decision",
                    "name": decision.name,
                    "description": decision.description,
                    "path": decision.path,
                    "score": decision.score,
                    "content": decision.content,
                }
            else:
                # Boost score for multiple term matches
                results[decision.path]["score"] += decision.score

    # Sort by score and return top results
    sorted_results = sorted(results.values(), key=lambda x: x["score"], reverse=True)
    return sorted_results[:max_results]


def grep_codebase(pattern: str, max_results: int = 10) -> list[dict]:
    """Search codebase with grep."""
    try:
        result = subprocess.run(
            ["grep", "-r", "-i", "-l", "--include=*.py", "--include=*.md", "--include=*.yaml", pattern, "."],
            capture_output=True,
            text=True,
            timeout=60,  # 1 minute
        )
        files = [f for f in result.stdout.strip().split("\n") if f][:max_results]
        return [{"path": f, "match_type": "grep"} for f in files]
    except Exception:
        return []


def glob_files(pattern: str, max_results: int = 10) -> list[dict]:
    """Find files matching glob pattern."""
    try:
        matches = list(Path(".").glob(pattern))[:max_results]
        return [{"path": str(m), "match_type": "glob"} for m in matches]
    except Exception:
        return []


def get_file_preview(path: str, max_lines: int = 20) -> Optional[str]:
    """Get preview of file content."""
    try:
        p = Path(path)
        if not p.exists() or p.stat().st_size > 100000:  # Skip large files
            return None
        content = p.read_text()
        lines = content.split("\n")[:max_lines]
        if len(content.split("\n")) > max_lines:
            lines.append(f"... ({len(content.split(chr(10))) - max_lines} more lines)")
        return "\n".join(lines)
    except Exception:
        return None


def context(
    query: str,
    types: Optional[list[str]] = None,
    include_files: bool = True,
    max_results: int = 5,
) -> dict:
    """
    Gather comprehensive context for a task.

    Combines:
    - DuckDB index keyword search
    - DuckDB index vector similarity search
    - Grep search across codebase
    - Relevant rules

    Args:
        query: What you're looking for
        types: Optional type filter
        include_files: Include file previews
        max_results: Max results per source

    Returns:
        Aggregated context dictionary
    """
    results = {
        "query": query,
        "index_types": list_types(),
        "keyword_matches": [],
        "similar_items": [],
        "grep_matches": [],
        "relevant_rules": [],
        "relevant_knowledge": [],
        "file_previews": {},
    }

    # Keyword search in index
    if types:
        for t in types:
            matches = search_by_type(t, query, limit=max_results)
            results["keyword_matches"].extend([m.to_dict() for m in matches])
    else:
        matches = search(query, limit=max_results)
        results["keyword_matches"] = [m.to_dict() for m in matches]

    # Vector similarity search
    similar = similar_to(query, limit=max_results)
    results["similar_items"] = [s.to_dict() for s in similar]

    # Grep search
    # Extract key terms from query for grep
    terms = [t for t in query.lower().split() if len(t) > 3]
    for term in terms[:3]:  # Limit to 3 terms
        grep_results = grep_codebase(term, max_results=3)
        for gr in grep_results:
            if gr not in results["grep_matches"]:
                results["grep_matches"].append(gr)

    # Get relevant rules (always useful context)
    all_rules = get_all_rules()
    # Filter rules that might be relevant based on query
    query_lower = query.lower()
    relevant_rules = [
        r for r in all_rules
        if any(term in r.get("name", "").lower() or term in r.get("description", "").lower()
               for term in query_lower.split())
    ]
    results["relevant_rules"] = relevant_rules[:max_results] if relevant_rules else all_rules[:3]

    # Get relevant knowledge (lessons, decisions)
    results["relevant_knowledge"] = get_relevant_knowledge(query, max_results=3)

    # File previews
    if include_files:
        seen_paths = set()
        for match in results["keyword_matches"] + results["similar_items"]:
            path = match.get("path")
            if path and path not in seen_paths:
                seen_paths.add(path)
                preview = get_file_preview(path)
                if preview:
                    results["file_previews"][path] = preview

    return results


def format_context_report(ctx: dict) -> str:
    """Format context as a readable report."""
    lines = [
        f"# Context for: {ctx['query']}",
        "",
        "## Index Overview",
        f"Types indexed: {ctx['index_types']}",
        "",
    ]

    if ctx["keyword_matches"]:
        lines.append("## Keyword Matches")
        for m in ctx["keyword_matches"]:
            lines.append(f"- **{m['name']}** ({m['type']}): {m['description']}")
            lines.append(f"  Path: {m['path']}")
        lines.append("")

    if ctx["similar_items"]:
        lines.append("## Similar Items (Vector Search)")
        for s in ctx["similar_items"]:
            lines.append(f"- **{s['name']}** ({s['type']}): score={s['score']:.3f}")
        lines.append("")

    if ctx["grep_matches"]:
        lines.append("## Grep Matches")
        for g in ctx["grep_matches"]:
            lines.append(f"- {g['path']}")
        lines.append("")

    if ctx["relevant_rules"]:
        lines.append("## Relevant Rules")
        for r in ctx["relevant_rules"]:
            lines.append(f"- **{r['name']}** (priority={r.get('priority', 0)})")
            lines.append(f"  {r.get('description', '')}")
        lines.append("")

    if ctx.get("relevant_knowledge"):
        lines.append("## Relevant Knowledge")
        lines.append("*Lessons and decisions that may be relevant to this task:*")
        lines.append("")
        for k in ctx["relevant_knowledge"]:
            kind = k["type"].capitalize()
            lines.append(f"- **{k['name']}** ({kind})")
            if k.get("description"):
                # Truncate long descriptions
                desc = k["description"]
                if len(desc) > 150:
                    desc = desc[:147] + "..."
                lines.append(f"  {desc}")
            lines.append(f"  Path: {k['path']}")
        lines.append("")

    if ctx["file_previews"]:
        lines.append("## File Previews")
        for path, preview in list(ctx["file_previews"].items())[:3]:
            lines.append(f"\n### {path}")
            lines.append("```")
            lines.append(preview[:500] + "..." if len(preview) > 500 else preview)
            lines.append("```")

    return "\n".join(lines)


if __name__ == "__main__":
    import sys
    import json

    if len(sys.argv) < 2:
        print("Usage: uv run python -m tools context '<query>' [--json]")
        print("\nGathers context from index, grep, and files for a task.")
        sys.exit(1)

    query = sys.argv[1]
    output_json = "--json" in sys.argv

    ctx = context(query)

    if output_json:
        print(json.dumps(ctx, indent=2, default=str))
    else:
        print(format_context_report(ctx))

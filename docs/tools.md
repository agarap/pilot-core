# Pilot Tools & Infrastructure

> This document contains tool documentation and directory structure.
> For essential agent configuration, see [core-config.md](core-config.md).
> For detailed workflows, see [workflows.md](workflows.md).

## Tool CLI

All tools are CLI with automatic I/O logging:

```bash
uv run python -m tools <tool_name> '<json_args>'

# Examples
uv run python -m tools web_search '{"objective": "Claude API docs"}'
uv run python -m tools web_fetch '{"urls": ["https://example.com"]}'
uv run python -m tools --list
```

Tools automatically pick up `PILOT_RUN_ID` from environment to link calls to runs.

Logs: `logs/tools/<tool>/<timestamp>_<id>.json` (includes `run_id` if set)

---

## Context-First Workflow

**Before starting ANY task, gather context:**

```bash
# Gather context about a topic
uv run python tools/context.py "your task description"

# Or use the search module directly
uv run python -c "from lib.search import search; print([r.name for r in search('keyword')])"
```

This searches:
- **DuckDB index** - keyword and vector similarity search
- **Grep** - pattern matching across codebase
- **Rules** - relevant behavioral rules

The index (`data/index.json`) is automatically regenerated on each commit via pre-commit hook.

---

## Search API (lib/search.py)

The universal index enables powerful search across all YAML, MD, and Python files:

```python
from lib.search import search, search_by_type, similar_to, list_types, get_all_rules

# Keyword search (searches name, description, content, tags)
results = search("web search", limit=10)
results = search("parallel", types=["tool", "agent"])  # Filter by type

# Search within a specific type
results = search_by_type("rule", "commit")  # Rules mentioning "commit"
results = search_by_type("agent")  # All agents

# Vector similarity search (requires embeddings)
results = similar_to("How do I make API calls?")

# List all indexed types and counts
types = list_types()  # {'agent': 5, 'rule': 8, 'tool': 12, ...}

# Get all rules ordered by priority
rules = get_all_rules()
```

**Available types**: `agent`, `rule`, `tool`, `lib`, `config`, `decision`, `lesson`, `fact`, `run`, `project`, `parallel_task`, `parallel_findall`, `deep_research`, `file`

---

## DuckDB Index Queries

The universal index (`data/index.json`) can be queried using multiple approaches, from simple Python APIs to raw SQL.

### lib/queries.py - SQL Template System

The simplest approach for common queries. Templates are pre-built SQL in `system/queries/*.sql`.

```python
from lib.queries import load_query, execute_query, list_templates, get_template_info

# List available templates
templates = list_templates()
# ['agents_with_tool', 'all_by_type', 'content_with_field', 'list_by_type',
#  'research_findings', 'rules_for_agent', 'search_by_tag', 'search_content',
#  'search_json_field', 'system_overview']

# Execute a template with parameters
results = execute_query('rules_for_agent', {'agent_name': 'builder'})
results = execute_query('search_content', {'query': 'web', 'limit': 10})
results = execute_query('all_by_type', {'item_type': 'tool'})
results = execute_query('agents_with_tool', {'tool_name': 'Bash'})

# Load SQL for inspection or modification
sql = load_query('search_content')

# Get template metadata (description, parameters)
info = get_template_info('rules_for_agent')
# {'name': 'rules_for_agent', 'description': 'Query rules applicable to a specific agent',
#  'parameters': ['agent_name'], 'sql': '...'}
```

### lib/query_builder.py - Fluent Interface

For dynamic queries when templates don't fit. Chainable methods build SQL automatically.

```python
from lib.query_builder import QueryBuilder, query

# Filter by type
results = QueryBuilder().type('rule').execute()

# Search across name, description, content
results = QueryBuilder().search('web access').limit(10).execute()

# Combine filters
results = QueryBuilder().type('agent').where('name', 'builder').execute()

# Pattern matching
results = QueryBuilder().where_like('name', 'web%').execute()

# Content search (searches within JSON content field)
results = QueryBuilder().type('tool').content_contains('parallel').execute()

# Pagination
results = QueryBuilder().type('rule').order_by('name').limit(10).offset(20).execute()

# Order descending
results = QueryBuilder().type('rule').order_by('priority', desc=True).execute()

# Debug: see generated SQL and parameters
sql, params = QueryBuilder().type('rule').search('git').to_sql()

# Convenience function for cleaner code
results = query().type('agent').execute()
```

**QueryBuilder methods:**
- `.type(name)` - Filter by item type
- `.where(field, value)` - Exact field match
- `.where_like(field, pattern)` - SQL LIKE pattern (% wildcards)
- `.search(term)` - Full-text search across name, description, text
- `.content_contains(text)` - Search within content field
- `.order_by(field, desc=False)` - Sort results
- `.limit(n)` - Limit result count
- `.offset(n)` - Skip first n results
- `.to_sql()` - Return (sql, params) tuple for debugging
- `.execute()` - Run query and return results

### Available SQL Templates

Templates in `system/queries/*.sql` with their parameters:

| Template | Parameters | Description |
|----------|------------|-------------|
| `rules_for_agent` | `:agent_name` | Rules applicable to a specific agent (by priority) |
| `search_content` | `:query`, `:limit` | Full-text search across all types |
| `all_by_type` | `:item_type` | Get all items of a specific type |
| `list_by_type` | `:type` | List items by type (same as above, different format) |
| `agents_with_tool` | `:tool_name` | Find agents that have access to a tool |
| `search_by_tag` | `:tag` | Find items with a specific tag |
| `research_findings` | `:query`, `:limit` | Search parallel_task/deep_research results |
| `search_json_field` | `:field`, `:value` | Find items with specific JSON field value |
| `content_with_field` | `:field` | Find items that have a specific field |
| `system_overview` | (none) | Type counts and system summary |

### Direct DuckDB Access

For advanced queries when templates and QueryBuilder don't suffice:

```python
import duckdb

con = duckdb.connect(":memory:")
con.execute("""
    CREATE VIEW items AS
    SELECT unnest(items) as item
    FROM read_json_auto('data/index.json', maximum_object_size=50000000)
""")

# Find all agents using opus model (use LIKE for JSON-encoded values)
con.execute("SELECT item.name FROM items WHERE item.content.model::VARCHAR LIKE '%opus%'")

# Search research results
con.execute("""
    SELECT item.path, item.description
    FROM items
    WHERE item.type IN ('parallel_task', 'deep_research')
    AND item.description LIKE '%health%'
""")

# Count items by type
con.execute("SELECT item.type, count(*) FROM items GROUP BY item.type")

# Find items with specific tags (using list_contains)
con.execute("SELECT item.name FROM items WHERE list_contains(item.tags, 'research')")
```

**Key DuckDB patterns for the index:**
- `UNNEST(items) as unnest` - Flatten the items array
- `unnest.content->>'field'` - Extract JSON field as string
- `list_contains(unnest.tags, 'tag')` - Check if array contains value
- `maximum_object_size=50000000` - Required for large index files

---

## Directory Structure

```
pilot/
+-- CLAUDE.md            # Primary entry point - references docs/
+-- docs/                # Modular documentation
|   +-- core-config.md   # Essential agent instructions
|   +-- workflows.md     # Detailed workflows
|   +-- tools.md         # Tool documentation (this file)
+-- agents/              # SDK-based subagent definitions (YAML)
|   +-- builder.yaml
|   +-- web-researcher.yaml
|   +-- git-reviewer.yaml
+-- tools/               # CLI tools with I/O logging
+-- lib/                 # Core modules (run.py, search.py, index.py, invoke.py, etc.)
+-- data/index.json      # DuckDB index (IN GIT, auto-regenerated)
+-- projects/            # Work product (IN GIT)
|   +-- <project>/
|       +-- .runs/       # Run manifests (IN GIT)
|       +-- <outputs>/   # Deliverables
+-- workspaces/          # Ephemeral agent work (NOT in git)
+-- output/              # Session outputs from subagents (NOT in git)
+-- logs/                # I/O logs (NOT in git)
|   +-- agents/          # Agent invocation logs
|   +-- tools/           # Tool I/O logs
+-- system/
|   +-- config.yaml      # System config
|   +-- rules/           # Behavioral rules (YAML)
|   +-- queries/         # SQL query templates for DuckDB
+-- knowledge/           # Decisions, facts, lessons
+-- .claude/             # Reserved for native Claude Code features only
```

---

## What Goes Where

| Type | Location | In Git? |
|------|----------|---------|
| Pilot config | `CLAUDE.md` | Yes |
| Modular docs | `docs/*.md` | Yes |
| Agent definitions | `agents/*.yaml` | Yes |
| DuckDB index | `data/index.json` | Yes (auto-updated) |
| Run manifests | `projects/<p>/.runs/*.yaml` | Yes |
| Agent outputs | `projects/<p>/<files>` | Yes |
| Tool I/O logs | `logs/tools/` | No |
| Agent logs | `logs/agents/` | No |
| Session outputs | `output/` | No |
| Working files | `workspaces/` | No |
| SQL queries | `system/queries/` | Yes |

---

## Core Tools Reference

### Web Access Tools

| Tool | Purpose | When to Use |
|------|---------|-------------|
| `web_search` | Quick keyword searches | Finding URLs, simple lookups |
| `web_fetch` | Extract content from URLs | Reading known documentation |
| `parallel_task` | Deep research with citations | Multi-source analysis, synthesis |
| `parallel_findall` | Entity discovery at scale | Finding many entities |
| `parallel_chat` | Fast factual Q&A | Quick fact checks |
| `deep_research` | Extended research (pro+ processors) | Complex multi-hour analysis |

### Project Management Tools

| Tool | Purpose | When to Use |
|------|---------|-------------|
| `project_tracker` | Universal project tracking (all types) | Any tracked project |
| `feature_tracker` | Track feature implementation (legacy) | Feature-based projects |
| `agent_status` | Monitor background agent progress | Checking agent completion |
| `context.py` | Gather relevant context | Start of any task |

#### project_tracker

Universal project tracking supporting 5 work types:

| Type | Lifecycle | Use Case |
|------|-----------|----------|
| `feature` | pending → in_progress → passing/failing | Code features |
| `research` | pending → discovery → synthesis → verification → completed | Web/academic research |
| `planning` | problem_defined → decomposed → solutions_proposed → completed | Strategic planning |
| `knowledge` | proposed → verified → committed | Facts, lessons, decisions |
| `investigation` | open → exploring → concluded | Open-ended exploration |

**Actions:**

```bash
# Standard actions (all project types)
uv run python -m tools project_tracker '{"action": "list", "project": "<project>"}'
uv run python -m tools project_tracker '{"action": "next", "project": "<project>"}'
uv run python -m tools project_tracker '{"action": "add", "project": "<project>", "item_data": {...}}'
uv run python -m tools project_tracker '{"action": "bind", "project": "<project>"}'

# Lifecycle actions
uv run python -m tools project_tracker '{"action": "advance", "project": "<project>", "item_id": "q-001"}'
uv run python -m tools project_tracker '{"action": "mark_passing", "project": "<project>", "item_id": "core-001"}'
uv run python -m tools project_tracker '{"action": "mark_failing", "project": "<project>", "item_id": "core-001"}'

# Research-specific actions
uv run python -m tools project_tracker '{"action": "add_finding", "project": "<project>", "item_id": "q-001", "finding": "..."}'
uv run python -m tools project_tracker '{"action": "synthesize", "project": "<project>", "item_id": "synth-001"}'

# Parallel execution
uv run python -m tools project_tracker '{"action": "parallel_batch", "project": "<project>"}'
```

**Parallel Execution:**

Projects can enable parallel execution with `parallel_config`:

```json
{
  "project": "company-research",
  "type": "research",
  "parallel_config": {
    "enabled": true,
    "max_concurrent": 5,
    "agent_types": ["web-researcher", "company-researcher"]
  },
  "items": [
    {"id": "q-001", "question": "Market share?", "parallel_safe": true},
    {"id": "q-002", "question": "Competitors?", "parallel_safe": true},
    {"id": "synth-001", "description": "Synthesize", "parallel_safe": false, "dependencies": ["q-001", "q-002"]}
  ]
}
```

Use `parallel_batch` to get items that can run concurrently (parallel_safe=true + no unmet deps).

**Schema:** `system/schemas/project_list.schema.json`

#### agent_status

Monitor progress of background agents. Critical for token-efficient polling.

```bash
# Check all active agents in a project
uv run python -m tools agent_status '{"project": "my-project"}'

# Check specific run IDs
uv run python -m tools agent_status '{"project": "my-project", "run_ids": ["run_abc123", "run_def456"]}'

# List all active agents across all projects
uv run python -m tools agent_status '{"list_all": true}'

# Include completed agents in results
uv run python -m tools agent_status '{"project": "my-project", "include_completed": true}'
```

**Output format:**

```json
{
  "run_abc123": {
    "status": "running",
    "agent": "git-reviewer",
    "phase": "Reviewing lib/invoke.py",
    "last_heartbeat": "2025-12-07T10:05:32Z",
    "is_stale": false,
    "messages_processed": 42
  },
  "run_def456": {
    "status": "completed",
    "agent": "builder",
    "result_summary": "Created 3 files",
    "artifacts_created": ["lib/foo.py", "tests/test_foo.py"]
  }
}
```

**Progress file location:** `projects/{project}/.progress/{run_id}.yaml`

**Stale detection:** Agents with no heartbeat for 5+ minutes are flagged as `is_stale: true`.

### Internal Tools

| Tool | Purpose |
|------|---------|
| `lib/index.py` | Regenerate search index |
| `lib/search.py` | Search indexed content |
| `lib/queries.py` | Load and execute SQL templates from `system/queries/` |
| `lib/query_builder.py` | Fluent interface for building index queries |
| `lib/invoke.py` | Invoke subagents (supports background mode) |
| `lib/progress.py` | Agent progress tracking and heartbeat management |
| `lib/run.py` | Create/manage runs |
| `lib/worktree.py` | Manage parallel sessions |
| `lib/resume.py` | Resume stuck sessions |
| `lib/startup.py` | Comprehensive startup check (stuck sessions, projects, recommendations) |
| `lib/knowledge_check.py` | Post-commit knowledge capture prompts |
| `lib/rule_registry.py` | Rule hierarchy, conflicts, enforcement gaps |
| `tools/rule_audit` | CLI for auditing system rules |
| `tools/rule_coverage` | Verify enforcement mechanisms exist |
| `tools/log_search.py` | Search agent/tool invocation logs |
| `tools/detect_task_tool.py` | Scan agent logs for banned Task tool usage |

### Rule Audit Tool

Audit system rules for hierarchy, conflicts, and enforcement gaps:

```bash
# Show rule hierarchy (priority order)
uv run python -m tools rule_audit '{"action": "hierarchy"}'

# Detect rule conflicts
uv run python -m tools rule_audit '{"action": "conflicts"}'

# Find enforcement gaps (prompt-only rules that could be code-enforced)
uv run python -m tools rule_audit '{"action": "gaps"}'

# Rules for specific agent
uv run python -m tools rule_audit '{"action": "agent", "agent": "builder"}'

# Full audit report
uv run python -m tools rule_audit '{"action": "all"}'
```

Or via the library directly:

```python
from lib.rule_registry import RuleRegistry

registry = RuleRegistry()
registry.load_rules()

# Get rules sorted by priority
rules = registry.get_rules_by_priority()

# Detect conflicts
conflicts = registry.detect_conflicts()

# Find enforcement gaps
gaps = registry.audit_enforcement()
```

### Rule Coverage Tool

Verify that enforcement mechanisms actually exist and work:

```bash
# Full coverage report
uv run python -m tools rule_coverage '{"action": "report"}'

# Verify specific rule's enforcement
uv run python -m tools rule_coverage '{"action": "verify", "rule": "git-review-required"}'

# Find orphaned enforcement code (code without rules)
uv run python -m tools rule_coverage '{"action": "orphans"}'

# List rules that could be code-enforced
uv run python -m tools rule_coverage '{"action": "opportunities"}'
```

Coverage analysis provides:
- **Verification**: Checks that declared enforcement files exist and contain expected patterns
- **Orphan detection**: Finds enforcement code that doesn't map to any rule
- **Opportunities**: Lists prompt-only rules that could benefit from code enforcement

### Domain-Specific Tools

Optional tools for specific use cases. Require additional setup.

| Tool | Purpose | Setup Required |
|------|---------|----------------|
| `tools/gmail.py` | Gmail API (search, read, send, reply) | OAuth credentials |
| `tools/email_style.py` | Learn user communication style | Gmail OAuth |

Used by `@email-agent` for EA-style email prioritization.

---

## Deep Research Tools

Tools for browsing, filtering, and synthesizing deep research results stored in `data/deep_research/results/`.

### browse_research

Browse and filter deep research results. Click-based CLI (run directly, not through JSON dispatcher).

**Commands:**

| Command | Purpose |
|---------|---------|
| `list` | List all results with summary info (newest first) |
| `show <run_id>` | Show detailed info for a specific run |
| `stats` | Show aggregate statistics across all research |
| `search` | Search by citation URL or domain |

**Usage Examples:**

```bash
# List recent research
python -m tools.browse_research list
python -m tools.browse_research list --limit 10
python -m tools.browse_research list --format json

# Filter by date range
python -m tools.browse_research list --from 2025-01-01 --to 2025-01-31

# Filter by query keyword
python -m tools.browse_research list --query "AI startups"

# Show details for a specific run
python -m tools.browse_research show abc123

# Show aggregate statistics
python -m tools.browse_research stats

# Search by citation domain
python -m tools.browse_research search --citation arxiv.org
python -m tools.browse_research search -c techcrunch.com --format json
```

**Parameters:**

| Option | Command | Description |
|--------|---------|-------------|
| `--limit`, `-n` | list, search | Maximum results to show (default: 20) |
| `--format` | list, search | Output format: `table` or `json` (default: table) |
| `--from` | list | Filter results from date (YYYY-MM-DD) |
| `--to` | list | Filter results to date (YYYY-MM-DD) |
| `--query`, `-q` | list | Filter by keyword in query (case-insensitive) |
| `--citation`, `-c` | search | URL or domain to search for in citations (required) |

**Output Examples:**

Table output (list):
```
RUN_ID       DATE                 PROC     QUERY
--------------------------------------------------------------------------------
abc123       2025-01-15 14:30:00  ultra    What are the latest AI developments?
def456       2025-01-14 10:00:00  pro      Market analysis for SaaS startups

Showing 2 of 2 results
```

JSON output (list --format json):
```json
[
  {
    "run_id": "abc123",
    "query": "What are the latest AI developments?",
    "completed_at": "2025-01-15T14:30:00",
    "processor": "ultra"
  }
]
```

Stats output:
```
Research Statistics
========================================
Total Research Runs: 25
Total Citations: 1250
Total Basis Items: 450
Average Basis per Research: 18.0

By Processor:
  pro: 5 (20.0%)
  ultra: 20 (80.0%)

Date Range: 2025-01-01 to 2025-01-31
```

---

### synthesize_research

Synthesize findings across multiple deep research runs. Click-based CLI.

**Commands:**

| Command | Purpose |
|---------|---------|
| `citations` | Aggregate and deduplicate citations across runs |
| `common-findings` | Identify findings corroborated by multiple runs |
| `conflicts` | Detect potentially conflicting findings |
| `report` | Generate unified synthesis report (markdown or JSON) |

**Usage Examples:**

```bash
# Aggregate citations from specific runs
python -m tools.synthesize_research citations --runs run1,run2,run3
python -m tools.synthesize_research citations --query "AI startups" --format json

# Find common findings across runs
python -m tools.synthesize_research common-findings --runs run1,run2,run3
python -m tools.synthesize_research common-findings --query "market analysis" --threshold 2

# Detect conflicts between research findings
python -m tools.synthesize_research conflicts --runs run1,run2
python -m tools.synthesize_research conflicts --query "AI" --similarity 0.6

# Generate full synthesis report
python -m tools.synthesize_research report --runs run1,run2 --output synthesis.md
python -m tools.synthesize_research report --query "startups" --format json
```

**Parameters:**

| Option | Commands | Description |
|--------|----------|-------------|
| `--runs`, `-r` | all | Comma-separated list of run IDs |
| `--query`, `-q` | all | Filter runs by query keyword (alternative to --runs) |
| `--limit`, `-n` | citations | Maximum citations to show (default: 20) |
| `--format` | citations, common-findings, conflicts | Output format: `table` or `json` |
| `--threshold`, `-t` | common-findings | Minimum runs a finding must appear in (default: 2) |
| `--similarity`, `-s` | common-findings, conflicts, report | Similarity threshold for grouping 0-1 (default: 0.75) |
| `--output`, `-o` | report | Output file path (default: stdout) |
| `--format` | report | Output format: `markdown` or `json` (default: markdown) |

**Output Examples:**

Citations table output:
```
Citation Aggregation for 3 Research Runs
============================================================
Total Citations: 150
Unique URLs: 85
Unique Domains: 32

Sources Cited by Multiple Runs:
----------------------------------------

  [3 runs, 5 times] arxiv.org
    Title: Attention Is All You Need
    URL: https://arxiv.org/abs/1706.03762
    Fields: methodology, background

Top Citation Domains:
----------------------------------------
  arxiv.org: 25 citations
  techcrunch.com: 15 citations
```

Report markdown output:
```markdown
# Research Synthesis Report

Generated: 2025-01-15T14:30:00

## Overview

**Research Runs Analyzed:** 3
**Total Basis Items:** 45
**Total Citations:** 150
**Unique Domains:** 32

### Contributing Research

1. **run1**: What are the latest AI developments?
2. **run2**: AI startup landscape 2025
3. **run3**: Machine learning trends

## Common Findings

Found **5** findings corroborated across multiple runs:

### Finding 1 (3 runs, 100% confidence)

**Supported by:** run1, run2, run3

> Transformer architectures continue to dominate...

**Sources (3):**
- https://arxiv.org/...
- https://example.com/...

## Potential Conflicts

No conflicting findings detected.

## Top Citations
...
```

---

### lib/research_cache

Search-before-research functionality to avoid duplicate expensive queries. Import as a library module.

**Key Functions:**

| Function | Purpose |
|----------|---------|
| `search_existing_research(query)` | Find research similar to a query |
| `pre_research_check(query)` | Check if cache can satisfy query before new research |
| `research_reuse_report()` | Generate cache usage and cost savings report |

**Usage Examples:**

```python
from lib.research_cache import search_existing_research, pre_research_check, research_reuse_report

# Find similar existing research
results = search_existing_research('What are the latest AI developments?')
for r in results:
    print(f'{r.score:.2f}: {r.query} ({r.run_id})')

# Check cache before running expensive research
check = pre_research_check('What is the latest in AI?', threshold=0.7)
if check.should_use_cache:
    print(f'Using cached research: {len(check.cached_results)} matches')
    for match in check.cached_results:
        print(f'  - {match.run_id}: {match.query[:50]}...')
else:
    print(f'Need new research: {check.reason}')

# Generate reuse report
report = research_reuse_report(days_back=30)
print(report.format_text())
```

**CLI Usage:**

```bash
# Search for existing research
python -m lib.research_cache "AI developments"

# Generate reuse report
python -m lib.research_cache --report
python -m lib.research_cache --report --days 7
python -m lib.research_cache --report --json
```

**Parameters:**

| Parameter | Function | Description |
|-----------|----------|-------------|
| `query` | search_existing_research | Search query to find matches |
| `limit` | search_existing_research | Max results (default: 5) |
| `min_score` | search_existing_research | Minimum similarity 0-1 (default: 0.0) |
| `processor` | search_existing_research | Filter by processor type |
| `threshold` | pre_research_check | Cache hit threshold 0-1 (default: 0.7) |
| `force_new` | pre_research_check | Bypass cache, always return False |
| `days_back` | research_reuse_report | Days of logs to analyze (default: 30) |

**Return Types:**

- `ResearchMatch`: Contains `run_id`, `query`, `processor`, `completed_at`, `path`, `score`
- `CacheCheckResult`: Contains `should_use_cache`, `cached_results`, `reason`, `query`, `threshold`
- `ResearchReuseReport`: Contains cache stats, hit rate, cost savings estimate

---

### lib/indexer

Incremental indexing utilities for updating `data/index.json` without full rebuilds.

**Key Functions:**

| Function | Purpose |
|----------|---------|
| `incremental_index(path)` | Add/update a single item in the index |
| `rebuild_deep_research_index()` | Rebuild all deep_research entries |
| `get_index_status()` | Get index statistics |

**Usage Examples:**

```python
from lib.indexer import incremental_index, rebuild_deep_research_index, get_index_status

# Index a single new research result
result = incremental_index('data/deep_research/results/xxx/metadata.yaml')
if result['success']:
    print(f"Indexed {result['type']}: {result['path']}")
else:
    print(f"Error: {result.get('error')}")

# Rebuild all deep_research entries (removes stale items)
result = rebuild_deep_research_index()
print(f"Added {result['items_added']}, removed {result['items_removed']}")

# Check index status
status = get_index_status()
print(f"Index has {status['count']} items")
for item_type, count in status['by_type'].items():
    print(f"  {item_type}: {count}")
```

**CLI Usage:**

```bash
# Index a single file
python -m lib.indexer data/deep_research/results/xxx/metadata.yaml

# Rebuild all deep_research entries
python -m lib.indexer rebuild

# Show index statistics
python -m lib.indexer status
```

**Output Examples:**

Status output:
```json
{
  "success": true,
  "exists": true,
  "count": 150,
  "by_type": {
    "agent": 12,
    "tool": 25,
    "rule": 8,
    "deep_research": 45,
    "decision": 10
  },
  "generated_at": "2025-01-15T14:30:00"
}
```

Rebuild output:
```json
{
  "success": true,
  "items_added": 45,
  "items_removed": 42,
  "total_count": 150
}
```

---

### Related Files

| File | Purpose |
|------|---------|
| `tools/browse_research.py` | CLI for browsing research results |
| `tools/synthesize_research.py` | CLI for synthesizing across runs |
| `lib/research_cache.py` | Search-before-research functionality |
| `lib/indexer.py` | Incremental indexing utilities |
| `data/deep_research/results/` | Research result storage directory |
| `data/index.json` | Unified search index |

---

## Tool Development

When creating a tool in tools/:

1. Create file with proper docstring header:
   ```python
   """
   tool: tool_name
   description: What this tool does
   parameters:
     param1: Description of param1
   returns: What it returns
   """
   ```

2. Implement the main function

3. **CRITICAL: Web Access Policy**
   - NEVER import requests, httpx, urllib, aiohttp directly
   - For web access, import from tools.web_search or tools.web_fetch
   - All web tools MUST use PARALLEL_API_KEY
   - No web scraping (BeautifulSoup, Scrapy, Selenium)

4. Add dependencies with `uv add` if needed

5. Run `uv run python -m lib.index`

6. Test the tool works

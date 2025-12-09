# Research Knowledge Base v2 - Full Provenance Design

**Version**: 2.0
**Date**: 2025-12-07
**Status**: Design Complete - Ready for Implementation
**Author**: Pilot System

---

## Executive Summary

This design extends the Notion sync system to create a **complete research knowledge base with full provenance**. The key innovation is a **provenance chain** that links every research output back through the agents, runs, and API calls that produced it—enabling you to trace from a high-level project summary down to individual citations and raw web search results.

### Design Principles

1. **Full Content Sync**: Not just metadata—actual research content readable in Notion
2. **Provenance Chain**: Every output links to what produced it
3. **Evidence Trail**: Citations, excerpts, and reasoning preserved
4. **Navigable UX**: Click-through from summary → evidence → raw outputs
5. **Incremental Sync**: Only changed content syncs (content hashing)

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           NOTION KNOWLEDGE BASE                              │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌─────────────┐      ┌─────────────┐      ┌─────────────┐                  │
│  │  Projects   │◄────►│   Features  │◄────►│    Runs     │                  │
│  │  Database   │      │  (Work Items)│      │  Database   │                  │
│  └──────┬──────┘      └──────┬──────┘      └──────┬──────┘                  │
│         │                    │                    │                          │
│         │                    │                    ▼                          │
│         │                    │           ┌─────────────┐                    │
│         │                    │           │   Agent     │                    │
│         │                    │           │   Outputs   │                    │
│         │                    │           └──────┬──────┘                    │
│         │                    │                  │                            │
│         ▼                    ▼                  ▼                            │
│  ┌─────────────┐      ┌─────────────┐    ┌─────────────┐                    │
│  │  Research   │◄────►│  Parallel   │◄──►│  Evidence   │                    │
│  │  Documents  │      │  Searches   │    │  (Citations)│                    │
│  └─────────────┘      └──────┬──────┘    └─────────────┘                    │
│                              │                                               │
│                              ▼                                               │
│                       ┌─────────────┐                                        │
│                       │  Candidates │                                        │
│                       │  (Results)  │                                        │
│                       └─────────────┘                                        │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Database Schema (7 Databases)

### 1. Projects Database

**Purpose**: Top-level project tracking with roll-up statistics

| Property | Type | Description |
|----------|------|-------------|
| Name | title | Project name |
| Type | select | research, gtm, competitive, personal, health |
| Status | select | Active, Paused, Completed, Archived |
| Description | rich_text | Project description |
| Local Path | rich_text | Path to project directory |
| Feature Count | number | Total features |
| Completed Count | number | Completed features |
| Completion % | formula | `Completed Count / Feature Count * 100` |
| Research Docs | rollup | Count of related Research Documents |
| Parallel Searches | rollup | Count of related searches |
| Last Sync | date | Last sync timestamp |
| Features | relation | → Features database |

**Page Body Content**:
- Project overview (from README or progress.txt)
- Embedded linked database view of Features (filtered to this project)
- Embedded linked database view of Research Documents

---

### 2. Features Database (Work Items)

**Purpose**: Track research features with links to supporting evidence

| Property | Type | Description |
|----------|------|-------------|
| Name | title | Feature name |
| ID | rich_text | Feature ID (e.g., lit-nir-001) |
| Project | relation | → Projects database |
| Type | select | feature, literature_review, hypothesis, analysis, synthesis, experiment, prototype |
| Status | select | Pending, In Progress, Completed, Blocked |
| Priority | select | Critical, High, Medium, Low |
| Complexity | select | Low, Medium, High |
| Passes | checkbox | Verification status |
| Category | select | From feature_list categories |
| Output Path | rich_text | Expected output file path |
| Dependencies | relation | → Features (self-relation) |
| **Runs** | relation | → Runs database (NEW - provenance) |
| **Evidence** | relation | → Evidence database (NEW - provenance) |
| **Research Docs** | relation | → Research Documents (NEW) |
| Last Sync | date | Last sync timestamp |

**Page Body Content**:
- Description (full text)
- Methodology section
- Acceptance Criteria (bulleted list)
- Expected Outputs (bulleted list)
- **Linked Evidence** toggle (expandable list of supporting citations)
- **Related Runs** toggle (timeline of agent work)

---

### 3. Runs Database (NEW)

**Purpose**: Track every agent invocation for provenance

| Property | Type | Description |
|----------|------|-------------|
| Name | title | Task summary (truncated) |
| Run ID | rich_text | Unique run identifier (e.g., 20251203_220504_builder) |
| Timestamp | date | When run started |
| Agent | select | builder, web-researcher, academic-researcher, verifier, etc. |
| Status | select | Completed, Failed, In Progress |
| Feature | relation | → Features (what feature this run worked on) |
| Files Modified | multi_select | List of files created/modified |
| Duration | number | Run duration in seconds (if available) |
| Local Path | rich_text | Path to .runs/*.yaml manifest |
| **Agent Output** | relation | → Agent Outputs (the raw output produced) |

**Page Body Content**:
- Full task description (from manifest)
- Files modified list
- Link to agent output (if exists)

---

### 4. Agent Outputs Database (NEW)

**Purpose**: Raw agent research outputs before synthesis

| Property | Type | Description |
|----------|------|-------------|
| Name | title | Output title (from H1 or filename) |
| Agent | select | web-researcher, academic-researcher, etc. |
| Created | date | File creation timestamp |
| Run | relation | → Runs database (which run produced this) |
| Feature | relation | → Features (what feature this supports) |
| Project | relation | → Projects |
| Type | select | research, analysis, synthesis, notes |
| Local Path | rich_text | Path to _working/agent-outputs/*.md |
| Summary | rich_text | First 500 chars |
| **Full Content** | checkbox | Whether full content is synced to page body |

**Page Body Content**:
- **Full markdown content** (synced to Notion blocks)
- Chunked across multiple append operations if large
- Preserves headings, lists, code blocks, tables

---

### 5. Research Documents Database

**Purpose**: Final synthesized research outputs (full content)

| Property | Type | Description |
|----------|------|-------------|
| Name | title | Document title |
| Project | relation | → Projects |
| Features | relation | → Features (what features this addresses) |
| Type | select | research, analysis, notes, report, design, documentation |
| Status | select | Active, Draft, Archived, Reviewed |
| Created | date | Creation timestamp |
| Updated | date | Last modified |
| Tags | multi_select | Topic tags |
| Local Path | rich_text | Path to research/*.md |
| Summary | rich_text | Executive summary or first 500 chars |
| Word Count | number | Document length |
| **Runs** | relation | → Runs (what runs contributed) |
| **Agent Outputs** | relation | → Agent Outputs (source materials) |

**Page Body Content**:
- **Full markdown content** synced as Notion blocks
- Table of contents (if document has headings)
- Callout with metadata (created, updated, word count)
- Related content section (linked databases filtered to this doc)

---

### 6. Parallel Searches Database

**Purpose**: Track Parallel.ai findall and deep_research runs

| Property | Type | Description |
|----------|------|-------------|
| Name | title | Query or search description |
| Type | select | findall, deep_research |
| Status | select | Pending, Completed, Failed |
| Run ID | rich_text | Parallel run ID (e.g., trun_xxx or findall_xxx) |
| Query | rich_text | The search query (full text) |
| Completed At | date | Completion timestamp |
| Candidate Count | number | Total candidates/basis entries |
| Matched Count | number | Matched/relevant results |
| Citation Count | number | Total citations (for deep_research) |
| Feature | relation | → Features (what feature triggered this) |
| Project | relation | → Projects |
| Local Path | rich_text | Path to data/parallel_*/ directory |
| **Evidence** | relation | → Evidence (citations extracted) |
| **Candidates** | relation | → Candidates database |

**Page Body Content**:
- Query details (full text, context)
- Summary statistics
- **Embedded linked database**: Candidates filtered to this search
- **Embedded linked database**: Evidence/Citations filtered to this search

---

### 7. Evidence Database (NEW - Citations & Excerpts)

**Purpose**: Individual citations with excerpts and reasoning

| Property | Type | Description |
|----------|------|-------------|
| Name | title | Source title or excerpt summary |
| URL | url | Source URL |
| Search | relation | → Parallel Searches (which search found this) |
| Feature | relation | → Features (what feature this supports) |
| Field | rich_text | What aspect this evidences (from basis.field) |
| Confidence | select | high, medium, low |
| Source Type | select | web, paper, api, manual |
| Created | date | When captured |

**Page Body Content**:
- **Excerpts** (toggle block, expandable)
  - Each excerpt as a quote block
- **Reasoning** (full AI reasoning for why this is relevant)
- Callout with confidence level and source info

---

## Page UX Design

### Project Page Layout

```
┌─────────────────────────────────────────────────────────────────┐
│ 🗂️ next-gen-search-index                                        │
│ ═══════════════════════════════════════════════════════════════ │
│                                                                  │
│ ┌─────────────────────────────────────────────────────────────┐ │
│ │ 📊 Progress: ████████░░░░░░░░░░░░ 35% (15/44 features)      │ │
│ │ Status: Active | Type: Research | Last Sync: 2025-12-07     │ │
│ └─────────────────────────────────────────────────────────────┘ │
│                                                                  │
│ ## Description                                                   │
│ A unified end-to-end trained ML model combining web search,     │
│ recommendations, and SQL/structured queries...                   │
│                                                                  │
│ ▶ Features (44)                    [Linked Database View]       │
│ ┌─────────────────────────────────────────────────────────────┐ │
│ │ Name                  │ Status    │ Type           │ Runs   │ │
│ │ Dense Retrieval...    │ Pending   │ literature_rev │ 3      │ │
│ │ Cross-Encoder...      │ Completed │ literature_rev │ 5      │ │
│ └─────────────────────────────────────────────────────────────┘ │
│                                                                  │
│ ▶ Research Documents (8)           [Linked Database View]       │
│ ┌─────────────────────────────────────────────────────────────┐ │
│ │ MASTER-SYNTHESIS-ULTRA8X-20251201                           │ │
│ │ NOVEL-HYPOTHESES-20251204                                   │ │
│ │ TRANSFORMER-CENTRIC-WEB-INDEX-20251204                      │ │
│ └─────────────────────────────────────────────────────────────┘ │
│                                                                  │
│ ▶ Parallel Searches (9)            [Linked Database View]       │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### Feature Page Layout (with Provenance)

```
┌─────────────────────────────────────────────────────────────────┐
│ 📋 lit-nir-001: Dense Retrieval Architectures Survey            │
│ ═══════════════════════════════════════════════════════════════ │
│                                                                  │
│ Project: next-gen-search-index | Status: In Progress            │
│ Type: literature_review | Complexity: High                      │
│                                                                  │
│ ## Description                                                   │
│ Comprehensive review of dense retrieval methods including       │
│ DPR, ColBERT, ANCE, and their variants...                       │
│                                                                  │
│ ## Methodology                                                   │
│ Systematic literature review using Google Scholar, Semantic     │
│ Scholar, and ACL Anthology. Focus on papers 2019-2024.          │
│                                                                  │
│ ## Acceptance Criteria                                           │
│ • 20+ papers reviewed and synthesized                           │
│ • Taxonomy of dense retrieval approaches created                │
│ • Strengths/weaknesses analysis documented                      │
│ • Key architectural patterns identified                         │
│                                                                  │
│ ─────────────────────────────────────────────────────────────── │
│                     PROVENANCE SECTION                           │
│ ─────────────────────────────────────────────────────────────── │
│                                                                  │
│ ▶ Supporting Evidence (23 citations)                             │
│ ┌─────────────────────────────────────────────────────────────┐ │
│ │ 📎 "Embedding-Based Retrieval in Facebook Search" (high)    │ │
│ │    → Meta EBR system, A/B test results...                   │ │
│ │ 📎 "ColBERT: Efficient BERT for IR" (high)                  │ │
│ │    → Late interaction architecture...                       │ │
│ └─────────────────────────────────────────────────────────────┘ │
│                                                                  │
│ ▶ Agent Runs (5 runs)                                            │
│ ┌─────────────────────────────────────────────────────────────┐ │
│ │ 2025-12-03 | web-researcher | Research Meta's neural search │ │
│ │ 2025-12-02 | academic-res   | ColBERT architecture analysis │ │
│ └─────────────────────────────────────────────────────────────┘ │
│                                                                  │
│ ▶ Raw Agent Outputs (3 documents)                                │
│ ┌─────────────────────────────────────────────────────────────┐ │
│ │ agent-web-meta-production-20251130-145500.md                │ │
│ │ agent-academic-dense-retrieval-20251128.md                  │ │
│ └─────────────────────────────────────────────────────────────┘ │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### Evidence Page Layout

```
┌─────────────────────────────────────────────────────────────────┐
│ 📎 Embedding-Based Retrieval in Facebook Search                 │
│ ═══════════════════════════════════════════════════════════════ │
│                                                                  │
│ 🔗 https://arxiv.org/abs/2006.11632                             │
│ Confidence: 🟢 High | Field: production_deployment_evidence     │
│ Search: deep_research trun_0cb15e174bc44a01...                  │
│                                                                  │
│ ┌─────────────────────────────────────────────────────────────┐ │
│ │ 💡 Why This Evidence Matters                                 │ │
│ │                                                              │ │
│ │ This citation directly demonstrates production-scale        │ │
│ │ deployment of neural retrieval at Meta, with concrete       │ │
│ │ A/B test metrics showing significant wins over boolean      │ │
│ │ matching. It validates the feasibility of two-tower         │ │
│ │ architectures at web scale.                                 │ │
│ └─────────────────────────────────────────────────────────────┘ │
│                                                                  │
│ ▶ Excerpts                                                       │
│                                                                  │
│ > "Significant metrics gains observed in online A/B             │
│ > experiments. EBR helped surface semantically relevant         │
│ > results that Boolean matching missed."                        │
│                                                                  │
│ > "Two-tower model: Separate query and document encoders.       │
│ > User embeddings incorporate: query text, social connections,  │
│ > user history."                                                │
│                                                                  │
│ > "Previously based on Boolean matching model - EBR was the     │
│ > first large-scale neural retrieval deployment"                │
│                                                                  │
│ ## Full Reasoning                                                │
│                                                                  │
│ To determine relevance to the field production_deployment_      │
│ evidence, I focus on excerpts that explicitly mention           │
│ production systems, A/B test results, and real-world metrics... │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## Content Sync Strategy

### Challenge: API Limits

| Limit | Value | Strategy |
|-------|-------|----------|
| Blocks per append | 100 | Chunk content into batches |
| Total blocks | 1000 | Multiple append calls |
| Payload size | 500KB | Split large documents |
| Rich text | 2000 chars | Split long paragraphs |
| Nesting depth | 2 levels | Flatten deep nesting |
| Rate limit | 3 req/sec | Queue with exponential backoff |

### Content Chunking Algorithm

```python
def sync_document_content(page_id: str, markdown: str, client: NotionClient):
    """
    Sync full markdown content to Notion page body.
    Handles chunking to stay within API limits.
    """
    # Convert markdown to Notion blocks
    blocks = markdown_to_notion_blocks(markdown)

    # Chunk into batches of 100
    for i in range(0, len(blocks), 100):
        chunk = blocks[i:i+100]

        # Flatten any deep nesting (>2 levels)
        chunk = flatten_deep_nesting(chunk)

        # Split any oversized rich text
        chunk = split_long_text(chunk, max_chars=2000)

        # Append with rate limiting
        client.append_block_children(
            block_id=page_id,
            children=chunk,
        )

        # Rate limit: 3 req/sec
        time.sleep(0.35)
```

### Markdown to Notion Block Mapping

| Markdown | Notion Block Type |
|----------|-------------------|
| `# Heading` | heading_1 |
| `## Heading` | heading_2 |
| `### Heading` | heading_3 |
| Paragraph | paragraph |
| `- Item` | bulleted_list_item |
| `1. Item` | numbered_list_item |
| `> Quote` | quote |
| ``` code ``` | code |
| `[link](url)` | rich_text with href |
| `**bold**` | annotations.bold |
| `*italic*` | annotations.italic |
| `---` | divider |
| Table | table + table_row |

---

## Provenance Linking Strategy

### Data Flow for Provenance

```
1. Feature Created (feature_list.json)
       │
       ▼
2. Run Triggered (.runs/*.yaml manifest)
       │
       ├──► Agent invoked (builder, web-researcher, etc.)
       │
       ▼
3. Agent Output Created (_working/agent-outputs/*.md)
       │
       ├──► Parallel Search triggered (if web research)
       │         │
       │         ▼
       │    4. Parallel Results (data/deep_research/, data/parallel_findall/)
       │         │
       │         ├──► Evidence/Citations extracted (basis entries)
       │         │
       │         ▼
       │    5. Candidates (individual results)
       │
       ▼
6. Research Document Created (research/*.md)
       │
       ▼
7. Feature marked complete
```

### Automatic Provenance Detection

The sync system will attempt to automatically link provenance by:

1. **Run → Feature**: Parse task description for feature IDs
2. **Agent Output → Run**: Match timestamps and agent names
3. **Research Doc → Agent Outputs**: Parse frontmatter or content for references
4. **Evidence → Parallel Search**: Parent relationship from file structure
5. **Feature → Evidence**: Match feature keywords in evidence content

### Manual Provenance Hints

For cases where automatic detection fails, support frontmatter hints:

```yaml
---
title: Dense Retrieval Survey
feature: lit-nir-001
sources:
  - trun_0cb15e174bc44a01888852f5981f7c60
  - agent-web-meta-production-20251130-145500.md
---
```

---

## Implementation Phases

### Phase 1: Core Database Schema (Foundation)
- Create all 7 databases with properties
- Set up relations between databases
- Migrate existing Projects, Features, Parallel Searches
- Add Runs database populated from .runs/*.yaml

### Phase 2: Full Content Sync
- Implement markdown-to-blocks converter
- Add content chunking algorithm
- Sync Research Documents with full content
- Sync Agent Outputs with full content

### Phase 3: Evidence Extraction
- Parse deep_research output.yaml for basis entries
- Extract citations, excerpts, reasoning
- Create Evidence pages with structured content
- Link Evidence → Parallel Searches → Features

### Phase 4: Provenance Linking
- Implement automatic provenance detection
- Parse run manifests for feature associations
- Link Agent Outputs → Runs → Features
- Create Research Doc → sources relationships

### Phase 5: UX Polish
- Add embedded linked database views to pages
- Create toggle sections for provenance
- Add callouts for key metadata
- Implement summary/overview sections

---

## Configuration Schema

```yaml
# system/config/notion_sync.yaml (v2)

enabled: true
sync_on_commit: true
api_version: "2025-09-03"

# Content sync settings
content_sync:
  enabled: true
  max_document_size_kb: 500  # Skip documents larger than this
  chunk_size: 100  # Blocks per append call

# Provenance settings
provenance:
  enabled: true
  auto_detect: true  # Attempt automatic linking
  sync_runs: true
  sync_agent_outputs: true
  sync_evidence: true

# Which databases to create/sync
databases:
  projects: true
  features: true
  runs: true
  agent_outputs: true
  research_documents: true
  parallel_searches: true
  evidence: true

# Projects to sync
projects:
  - path: projects/next-gen-search-index
    sync_features: true
    sync_research_outputs: true
    sync_agent_outputs: true
    sync_provenance: true

  - path: projects/work/parallel/gtm
    sync_type: documents
    sync_provenance: false
```

---

## API Rate Limiting Strategy

```python
class RateLimitedClient:
    """
    Notion client wrapper with rate limiting and retry logic.
    """

    def __init__(self, api_key: str):
        self.client = NotionClient(api_key)
        self.min_interval = 0.35  # ~3 req/sec
        self.last_request = 0
        self.retry_delays = [1, 2, 4, 8, 16]  # Exponential backoff

    async def request(self, method: str, *args, **kwargs):
        # Ensure minimum interval between requests
        elapsed = time.time() - self.last_request
        if elapsed < self.min_interval:
            await asyncio.sleep(self.min_interval - elapsed)

        for attempt, delay in enumerate(self.retry_delays):
            try:
                self.last_request = time.time()
                return await getattr(self.client, method)(*args, **kwargs)

            except RateLimitError:
                if attempt == len(self.retry_delays) - 1:
                    raise
                await asyncio.sleep(delay)

            except ServerError:
                if attempt == len(self.retry_delays) - 1:
                    raise
                await asyncio.sleep(delay)
```

---

## Success Metrics

| Metric | Target | Measurement |
|--------|--------|-------------|
| Content completeness | 100% | All research docs have full content in Notion |
| Provenance coverage | >80% | Features linked to supporting evidence |
| Sync latency | <5 min | Time from commit to Notion update |
| UX navigability | <3 clicks | From project to any evidence |
| Error rate | <1% | Failed sync operations |

---

## Migration Path from v1

1. **Preserve existing data**: Don't delete v1 databases
2. **Create new databases**: Add Runs, Agent Outputs, Evidence
3. **Migrate relations**: Update Features to link to new databases
4. **Enable content sync**: Gradually enable full content for docs
5. **Backfill provenance**: Run one-time analysis to link existing data

---

## Appendix: File Structure

```
pilot/
├── tools/notion_sync/
│   ├── __init__.py
│   ├── __main__.py
│   ├── sync.py                    # Main orchestrator (updated)
│   ├── client.py                  # API client (rate limiting)
│   ├── config.py                  # Config loader
│   ├── state.py                   # State management
│   ├── content/                   # NEW: Content sync
│   │   ├── __init__.py
│   │   ├── markdown_converter.py  # MD → Notion blocks
│   │   ├── chunker.py             # Content chunking
│   │   └── page_builder.py        # Build page bodies
│   ├── provenance/                # NEW: Provenance tracking
│   │   ├── __init__.py
│   │   ├── run_linker.py          # Link runs to features
│   │   ├── evidence_extractor.py  # Extract from parallel results
│   │   └── auto_detector.py       # Automatic linking
│   └── mappers/
│       ├── project.py
│       ├── feature_list.py
│       ├── parallel_results.py
│       ├── document.py
│       ├── run.py                 # NEW: Run manifest mapper
│       ├── agent_output.py        # NEW: Agent output mapper
│       └── evidence.py            # NEW: Evidence/citation mapper
│
├── system/config/
│   └── notion_sync.yaml           # Updated config schema
│
└── data/
    └── notion_sync_state.yaml     # Extended state tracking
```

---

## Document History

| Version | Date | Changes |
|---------|------|---------|
| 2.0 | 2025-12-07 | Full provenance design, 7-database schema, content sync |
| 1.0 | 2025-12-04 | Initial metadata-only design |

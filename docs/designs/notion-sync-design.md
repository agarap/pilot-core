# Notion Sync Design Document

**Version**: 1.0
**Date**: 2025-12-04
**Status**: Design Complete - Pending Implementation
**Author**: Pilot System

---

## Executive Summary

This document describes a system for syncing select Pilot projects to Notion, enabling a visual interface for navigating research outputs, tracking feature progress, and reviewing collected intelligence.

### Key Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Sync trigger | Post-commit hook (async) | Non-blocking, automatic, git-based observability |
| Sync direction | One-way (local → Notion) | Simpler, avoids conflict resolution |
| Project scope | Research/content only | Infrastructure projects don't benefit from visual UX |
| Content sync | Metadata only (MVP) | Full markdown sync is complex; defer to v2 |

---

## Table of Contents

1. [Scope: What Syncs to Notion](#1-scope-what-syncs-to-notion)
2. [Post-Commit Hook Architecture](#2-post-commit-hook-architecture)
3. [Notion Data Model](#3-notion-data-model)
4. [Property Mapping Reference](#4-property-mapping-reference)
5. [UX Design and User Experience](#5-ux-design-and-user-experience)
6. [Edge Cases and Error Handling](#6-edge-cases-and-error-handling)
7. [Implementation Plan](#7-implementation-plan)
8. [Appendix: Research Notes](#appendix-research-notes)

---

## 1. Scope: What Syncs to Notion

### 1.1 Projects IN Scope

These project types benefit from visual navigation and human review:

| Project | Path | Content Type | Why Sync |
|---------|------|--------------|----------|
| **next-gen-search-index** | `projects/next-gen-search-index/` | Research features (44 items) | Track literature reviews, hypotheses, experiments |
| **parallel-gtm** | `projects/work/parallel/gtm/` | GTM research docs | Navigate strategy documents, track execution |
| **parallel-competitors** | `projects/work/parallel/analysis/` | Competitor intelligence | Visual company profiles, competitive matrix |
| **personal-health** | `projects/personal/my-health/` | Health research | Personal knowledge base navigation |
| **wife-health** | `projects/personal/wife-health/` | Health research | Family health tracking |
| **friends-family-research** | `projects/personal/friends-and-family/` | Professional research | Deep research for family members |

### 1.2 Projects OUT of Scope

Infrastructure/tooling projects that don't benefit from Notion visualization:

| Project | Reason |
|---------|--------|
| `pilot-self-maintenance` | Internal tooling, no human review needed |
| `benchmarks` | Automated testing, ephemeral |
| System configs | Better managed in code |

### 1.3 Configuration

Projects opt-in via configuration file:

```yaml
# system/config/notion_sync.yaml
enabled: true
sync_on_commit: true  # post-commit hook

projects:
  - path: projects/next-gen-search-index
    notion_parent_page: "Research Projects"
    sync_features: true
    sync_research_outputs: false  # MVP: metadata only

  - path: projects/work/parallel/gtm
    notion_parent_page: "Work/Parallel"
    sync_type: documents  # markdown files only

  - path: projects/work/parallel/analysis
    notion_parent_page: "Work/Parallel"
    sync_type: documents

  - path: projects/personal/my-health
    notion_parent_page: "Personal/Health"
    sync_type: documents
    privacy: private  # separate workspace or private pages

# Notion API configuration (secrets in env vars)
# NOTION_API_KEY - integration token
# NOTION_WORKSPACE_ID - target workspace
```

---

## 2. Post-Commit Hook Architecture

### 2.1 Feasibility Analysis

**Question**: Can sync happen as part of git commit to main?

**Answer**: Yes, via post-commit hook (not pre-commit).

| Hook Type | Blocking? | On Failure | Recommendation |
|-----------|-----------|------------|----------------|
| pre-commit | Yes | Commit fails | Not suitable for sync |
| post-commit | No | Commit succeeds anyway | **Recommended** |
| post-merge | No | After merge to main | Also viable |

### 2.2 Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         Git Commit Flow                          │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│   git commit                                                     │
│       │                                                          │
│       ├──► pre-commit hook (existing: git-review check)          │
│       │                                                          │
│       ├──► COMMIT SUCCEEDS                                       │
│       │                                                          │
│       └──► post-commit hook (NEW: notion sync trigger)           │
│               │                                                  │
│               ├──► Detect changed files (git diff HEAD~1)        │
│               │                                                  │
│               ├──► Filter to sync-enabled projects               │
│               │                                                  │
│               └──► Queue async sync (daemonize)                  │
│                       │                                          │
│                       └──► notion_sync.py --incremental          │
│                               │                                  │
│                               ├──► Rate-limited API calls        │
│                               │                                  │
│                               └──► Log to logs/notion_sync.log   │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### 2.3 Post-Commit Hook Implementation

```bash
#!/bin/bash
# .git/hooks/post-commit

# Only sync on main branch
BRANCH=$(git rev-parse --abbrev-ref HEAD)
if [ "$BRANCH" != "main" ]; then
    exit 0
fi

# Check if notion sync is enabled
if [ ! -f "system/config/notion_sync.yaml" ]; then
    exit 0
fi

# Get changed files
CHANGED_FILES=$(git diff --name-only HEAD~1 HEAD 2>/dev/null)

# Check if any sync-enabled projects changed
SYNC_NEEDED=false
for file in $CHANGED_FILES; do
    if [[ "$file" == projects/next-gen-search-index/* ]] || \
       [[ "$file" == projects/work/parallel/* ]] || \
       [[ "$file" == projects/personal/* ]]; then
        SYNC_NEEDED=true
        break
    fi
done

if [ "$SYNC_NEEDED" = true ]; then
    # Run sync in background (non-blocking)
    nohup uv run python -m tools.notion_sync --incremental \
        --commit "$(git rev-parse HEAD)" \
        >> logs/notion_sync.log 2>&1 &

    echo "Notion sync queued (background)"
fi
```

### 2.4 Sync Modes

| Mode | Trigger | Behavior |
|------|---------|----------|
| `--incremental` | Post-commit | Only sync changed files |
| `--full` | Manual | Full resync of all projects |
| `--project <name>` | Manual | Sync specific project |
| `--dry-run` | Testing | Show what would sync |

### 2.5 Failure Handling

Since post-commit is non-blocking:

1. **Sync fails**: Logged to `logs/notion_sync.log`
2. **Notion down**: Retry queue in `data/notion_sync_queue.yaml`
3. **Rate limited**: Exponential backoff, resume on next commit
4. **Partial sync**: State tracked in `data/notion_sync_state.yaml`

---

## 3. Notion Data Model

### 3.1 Database Structure

```
Pilot Knowledge Base (Workspace)
│
├── 🗂️ Projects (Database)
│   │   Properties: Name, Type, Status, Description, Local Path, Feature Count, Last Sync
│   │   Views: All Projects, By Type, Active Only
│   │
│   └── [Each project is a page in this database]
│
├── 📋 Work Items (Database)
│   │   Properties: Name, ID, Project (relation), Type, Status, Priority,
│   │               Complexity, Passes, Output Path, Dependencies (relation)
│   │   Views: By Project, By Status (Kanban), By Type
│   │
│   └── [Features, hypotheses, research tasks from feature_list.json]
│
├── 🏢 Companies (Database)
│   │   Properties: Name, Domain, Industry, Funding Stage, Momentum,
│   │               Last Updated, Research Status
│   │   Views: Competitors, All Companies, By Industry
│   │
│   └── [Competitor profiles from parallel/analysis/competitors/]
│
├── 📚 Research Documents (Database)
│   │   Properties: Title, Project (relation), Type, Created, Updated,
│   │               Local Path, Summary
│   │   Views: By Project, Recent, By Type
│   │
│   └── [Markdown research outputs - metadata only in MVP]
│
└── 🔍 Parallel Results (Database - Optional)
        Properties: Query ID, Type, Completed, Candidate Count, Source
        [findall and deep_research results]
```

### 3.2 Relationships

```
Projects ─────────────< Work Items
    │                      │
    │                      │ (dependencies)
    │                      ▼
    │                  Work Items
    │
    └─────────────────< Research Documents
                           │
Companies ─────────────────┘ (mentioned in research)
```

### 3.3 Database Schemas

#### Projects Database

```json
{
  "Name": { "type": "title" },
  "Type": {
    "type": "select",
    "options": ["research", "gtm", "competitive", "personal", "health"]
  },
  "Status": {
    "type": "status",
    "options": ["Active", "Paused", "Completed", "Archived"]
  },
  "Description": { "type": "rich_text" },
  "Local Path": { "type": "text" },
  "Feature Count": { "type": "number" },
  "Completed Features": { "type": "number" },
  "Completion %": { "type": "formula", "expression": "Completed Features / Feature Count * 100" },
  "Last Sync": { "type": "date" },
  "Work Items": { "type": "relation", "database": "Work Items" }
}
```

#### Work Items Database

```json
{
  "Name": { "type": "title" },
  "ID": { "type": "text" },
  "Project": { "type": "relation", "database": "Projects" },
  "Type": {
    "type": "select",
    "options": ["feature", "literature_review", "hypothesis", "analysis", "synthesis", "experiment", "prototype"]
  },
  "Status": {
    "type": "status",
    "options": ["Pending", "In Progress", "Completed", "Blocked", "Abandoned"]
  },
  "Priority": {
    "type": "select",
    "options": ["Critical", "High", "Medium", "Low"]
  },
  "Complexity": {
    "type": "select",
    "options": ["Low", "Medium", "High"]
  },
  "Passes": { "type": "checkbox" },
  "Output Path": { "type": "text" },
  "Dependencies": { "type": "relation", "database": "Work Items" },
  "Category": { "type": "select" },
  "Acceptance Criteria": { "type": "rich_text" },
  "Local File": { "type": "url" }
}
```

#### Companies Database

```json
{
  "Name": { "type": "title" },
  "Domain": { "type": "url" },
  "Industry": { "type": "select" },
  "Funding Stage": {
    "type": "select",
    "options": ["Seed", "Series A", "Series B", "Series C+", "Public", "Unknown"]
  },
  "Total Funding": { "type": "text" },
  "Momentum": {
    "type": "select",
    "options": ["Accelerating", "Stable", "Decelerating", "Unknown"]
  },
  "Strengths": { "type": "rich_text" },
  "Weaknesses": { "type": "rich_text" },
  "Last Updated": { "type": "date" },
  "Source File": { "type": "text" }
}
```

---

## 4. Property Mapping Reference

### 4.1 Feature List → Work Items

| Local Field | Type | Notion Property | Notion Type | Notes |
|-------------|------|-----------------|-------------|-------|
| `id` | string | ID | text | e.g., "lit-nir-001" |
| `name` | string | Name | title | Primary display |
| `description` | string | Page content | blocks | In page body |
| `status` | enum | Status | status | pending→Pending, etc. |
| `research_type` | enum | Type | select | literature_review, etc. |
| `estimated_complexity` | enum | Complexity | select | low/medium/high |
| `dependencies` | array | Dependencies | relation | Resolved to Notion IDs |
| `acceptance_criteria` | array | Acceptance Criteria | rich_text | Bullet list |
| `expected_outputs` | array | Output Path | text | First item |
| `passes` | boolean | Passes | checkbox | Test status |
| `category` | string | Category | select | From parent category |

**Status Mapping:**
```
local status    → Notion status
─────────────────────────────────
pending         → Pending
in_progress     → In Progress
completed       → Completed
blocked         → Blocked
abandoned       → Abandoned
```

### 4.2 Markdown Research → Research Documents

| Local | Notion Property | Notes |
|-------|-----------------|-------|
| filename | Name (title) | Strip extension, humanize |
| file path | Local Path | Relative to repo root |
| parent dir | Project (relation) | Map to project |
| first 200 chars | Summary | Excerpt |
| mtime | Updated | File modification time |
| --- frontmatter | Properties | If YAML frontmatter exists |

### 4.3 Competitor Analysis → Companies

| Local (from MD) | Notion Property | Extraction Method |
|-----------------|-----------------|-------------------|
| H1 heading | Name | First `# ` line |
| Website field | Domain | Parse from content |
| Funding table | Total Funding, Funding Stage | Table parsing |
| Strengths section | Strengths | Section content |
| Weaknesses section | Weaknesses | Section content |
| File mtime | Last Updated | Filesystem |

---

## 5. UX Design and User Experience

### 5.1 User Journeys

#### Journey 1: Track Research Project Progress

```
User opens Notion → Projects database → next-gen-search-index
    │
    └─► Sees: 44 features, 0% complete, status breakdown
        │
        └─► Clicks "Work Items" relation
            │
            └─► Kanban view: features by status
                │
                └─► Drags item (read-only in MVP - edit locally)
```

#### Journey 2: Review Competitor Intelligence

```
User opens Notion → Companies database → Table view
    │
    └─► Sorts by: Momentum (Accelerating first)
        │
        └─► Clicks "Exa.ai" row
            │
            └─► Sees: Strengths, Weaknesses, Funding history
                │
                └─► "Source File" link → opens in VS Code
```

#### Journey 3: Navigate Health Research

```
User opens Notion → Projects → my-health
    │
    └─► Research Documents (filtered by project)
        │
        └─► Gallery view: document cards with summaries
            │
            └─► Clicks card → sees metadata
                │
                └─► "Open in Editor" → local file
```

### 5.2 Notion Views to Create

#### Projects Database Views

| View Name | Type | Filter | Sort | Columns |
|-----------|------|--------|------|---------|
| All Projects | Table | - | Name | All |
| Active | Table | Status = Active | Last Sync desc | Name, Type, Completion % |
| By Type | Board | - | Group by Type | Name, Status |

#### Work Items Database Views

| View Name | Type | Filter | Sort | Group By |
|-----------|------|--------|------|----------|
| All Items | Table | - | Project, ID | - |
| By Project | Board | - | - | Project |
| Kanban | Board | - | - | Status |
| Research | Table | Type in [literature_review, hypothesis, analysis] | - | - |
| Experiments | Table | Type in [experiment, prototype] | Priority | - |

#### Companies Database Views

| View Name | Type | Filter | Sort |
|-----------|------|--------|------|
| Competitors | Table | Industry = "AI Search" | Momentum |
| All | Table | - | Name |
| By Funding | Table | - | Total Funding desc |
| Gallery | Gallery | - | Name |

### 5.3 UX Issues and Mitigations

#### Issue 1: Stale Data Confusion

**Problem**: User edits in Notion, but changes don't persist (one-way sync)

**Mitigations**:
- Add "Read-Only" badge to synced databases
- Add "Last Synced" timestamp property (visible)
- Add callout block: "This data syncs from local files. Edit there."
- Consider: Lock editing on synced properties

#### Issue 2: Broken Links After Reorganization

**Problem**: Local file paths change, Notion links break

**Mitigations**:
- Store Notion page ID → local path mapping in `data/notion_sync_state.yaml`
- On sync, detect moved files and update Notion paths
- Add "File Not Found" status for missing files

#### Issue 3: Duplicate Entries

**Problem**: Same feature synced twice (ID collision)

**Mitigations**:
- Use local ID as unique key for upsert logic
- Store mapping: `local_id → notion_page_id`
- On sync: lookup existing, update if found, create if not

#### Issue 4: Relation Resolution Order

**Problem**: Feature A depends on Feature B, but B not synced yet

**Mitigations**:
- Two-pass sync: (1) create all pages, (2) set relations
- Or: defer relation updates to separate pass
- Store pending relations in state file

#### Issue 5: Large Project Performance

**Problem**: 44 features × API calls = slow sync

**Mitigations**:
- Incremental sync: only changed items
- Batch where possible (Notion supports some batching)
- Rate limiting: 3 req/sec max
- Progress logging to track long syncs

#### Issue 6: Private Data in Shared Workspace

**Problem**: Health data shouldn't be visible to all workspace members

**Mitigations**:
- Separate "Personal" page tree with restricted permissions
- Or: separate Notion workspace for private data
- Config: `privacy: private` flag per project

---

## 6. Edge Cases and Error Handling

### 6.1 Edge Cases Matrix

| Case | Scenario | Handling |
|------|----------|----------|
| **New Project** | Project dir created, no feature_list.json yet | Skip until feature_list exists |
| **Deleted Project** | Local dir removed | Archive Notion pages (don't delete) |
| **Renamed Project** | Dir renamed | Detect via git rename, update Notion |
| **Empty Feature List** | feature_list.json with 0 features | Create project page, empty relations |
| **Malformed JSON** | Invalid feature_list.json | Log error, skip project, continue others |
| **Notion API Error** | 429 (rate limit) | Exponential backoff, retry |
| **Notion API Error** | 500 (server error) | Retry 3x, then queue for next sync |
| **Notion API Error** | 401 (auth) | Alert user, stop sync |
| **Network Failure** | No internet | Queue sync, retry on next commit |
| **Concurrent Syncs** | Two commits in quick succession | Lock file prevents concurrent runs |
| **Huge Markdown** | 1MB+ research file | Truncate summary, link to local |
| **Special Characters** | Unicode in filenames | URL-encode paths |
| **Circular Dependencies** | A depends on B depends on A | Log warning, sync without relations |

### 6.2 Error Recovery

```yaml
# data/notion_sync_state.yaml
last_sync: "2025-12-04T10:30:00Z"
last_commit: "abc123def"
status: completed  # or: failed, partial

projects:
  next-gen-search-index:
    notion_db_id: "xxx-uuid"
    last_sync: "2025-12-04T10:30:00Z"
    items_synced: 44
    items_failed: 0

    work_items:
      "lit-nir-001":
        notion_page_id: "yyy-uuid"
        last_sync: "2025-12-04T10:30:00Z"
        content_hash: "sha256:abc123"  # for change detection
      "lit-nir-002":
        notion_page_id: "zzz-uuid"
        last_sync: "2025-12-04T10:30:00Z"
        content_hash: "sha256:def456"

pending_relations:  # deferred relation updates
  - source_id: "lit-nir-002"
    target_ids: ["lit-nir-001"]
    relation_type: "dependencies"

failed_items:  # retry queue
  - project: "next-gen-search-index"
    item_id: "arch-001"
    error: "Rate limited"
    retry_count: 2
    last_attempt: "2025-12-04T10:29:55Z"
```

### 6.3 Sync State Machine

```
┌─────────┐     commit      ┌──────────┐
│  IDLE   │ ───────────────►│ QUEUED   │
└─────────┘                 └──────────┘
     ▲                           │
     │                           │ start sync
     │                           ▼
     │                     ┌──────────┐
     │    all succeeded    │ SYNCING  │
     └─────────────────────┤          │
                           └──────────┘
                                │
                    ┌───────────┴───────────┐
                    │                       │
               some failed            all failed
                    │                       │
                    ▼                       ▼
              ┌──────────┐           ┌──────────┐
              │ PARTIAL  │           │ FAILED   │
              └──────────┘           └──────────┘
                    │                       │
                    │ next commit           │ next commit
                    │ retries failed        │ retries all
                    ▼                       ▼
              ┌──────────┐           ┌──────────┐
              │ QUEUED   │           │ QUEUED   │
              └──────────┘           └──────────┘
```

---

## 7. Implementation Plan

### 7.1 MVP Scope

**In Scope:**
- Post-commit hook trigger
- Projects database with basic properties
- Work Items database from feature_list.json
- Companies database from competitor markdown
- One-way sync (local → Notion)
- Incremental sync (changed files only)
- State tracking and error recovery

**Out of Scope (v2):**
- Full markdown content sync (complex block conversion)
- Two-way sync (Notion → local)
- Real-time sync (currently batch on commit)
- Parallel findall/deep_research results
- Research hypothesis confidence tracking UI

### 7.2 File Structure

```
pilot/
├── tools/
│   └── notion_sync/
│       ├── __init__.py
│       ├── __main__.py          # CLI entry point
│       ├── config.py            # Load sync config
│       ├── client.py            # Notion API wrapper
│       ├── sync.py              # Main sync logic
│       ├── mappers/
│       │   ├── feature_list.py  # feature_list.json → Work Items
│       │   ├── project.py       # Project dir → Projects
│       │   ├── company.py       # Competitor MD → Companies
│       │   └── document.py      # Research MD → Documents
│       └── state.py             # State management
│
├── system/config/
│   └── notion_sync.yaml         # Sync configuration
│
├── data/
│   └── notion_sync_state.yaml   # Sync state tracking
│
├── logs/
│   └── notion_sync.log          # Sync logs
│
└── .git/hooks/
    └── post-commit              # Hook script
```

### 7.3 Dependencies

```toml
# pyproject.toml additions
[project.optional-dependencies]
notion = [
    "notion-client>=2.0.0",     # Official Notion SDK
    "python-frontmatter>=1.0",   # Parse MD frontmatter
    "pyyaml>=6.0",               # Config parsing
]
```

### 7.4 Implementation Phases

#### Phase 1: Foundation (MVP)
1. Notion API client wrapper with rate limiting
2. Config loader and validator
3. State management (tracking page IDs)
4. Post-commit hook setup

#### Phase 2: Core Sync
1. Projects database sync
2. Work Items sync from feature_list.json
3. Incremental change detection
4. Relation resolution (two-pass)

#### Phase 3: Extended Content
1. Companies database from competitor markdown
2. Research Documents metadata
3. Summary extraction

#### Phase 4: Polish
1. Error recovery and retry logic
2. Logging and monitoring
3. Documentation and setup guide

---

## Appendix: Research Notes

### A.1 Local Data Formats Found

| Format | Location | Purpose |
|--------|----------|---------|
| **JSON** | `feature_list.json` | Feature/work item tracking |
| **YAML** | `system/schemas/*.yaml` | Schema definitions |
| **YAML** | `data/parallel_findall/**/*.yaml` | Candidate records |
| **YAML** | `data/deep_research/**/*.yaml` | Research results |
| **YAML** | `data/parallel_sessions.yaml` | Session tracking |
| **JSONL** | `data/enforcement_events.jsonl` | Event log |
| **Markdown** | `projects/**/*.md` | Research outputs |
| **JSON** | `data/index.json` | Master search index (85MB) |

### A.2 Notion API Capabilities

- **Create database**: `POST /databases`
- **Create page**: `POST /pages`
- **Update page**: `PATCH /pages/{id}`
- **Query database**: `POST /databases/{id}/query`
- **Append blocks**: `PATCH /blocks/{id}/children`

**Rate Limits**: 3 requests/second average

**Property Types Available**:
- title, rich_text, number, select, multi_select
- date, checkbox, url, email, phone_number
- relation, rollup, formula, status
- created_time, last_edited_time, created_by, last_edited_by

### A.3 Example Feature Entry (for reference)

```json
{
  "id": "lit-nir-001",
  "name": "Dense Retrieval Architectures Survey",
  "description": "Comprehensive review of dense retrieval methods including DPR, ColBERT, ANCE",
  "research_type": "literature_review",
  "methodology": "Systematic literature review using Google Scholar, Semantic Scholar",
  "acceptance_criteria": [
    "20+ papers reviewed and synthesized",
    "Taxonomy of dense retrieval approaches created",
    "Strengths/weaknesses analysis documented"
  ],
  "expected_outputs": [
    "research/lit-reviews/dense-retrieval-survey.md"
  ],
  "estimated_complexity": "high",
  "dependencies": [],
  "status": "pending"
}
```

### A.4 Notion Page JSON Example

```json
{
  "parent": { "database_id": "work_items_db_id" },
  "properties": {
    "Name": {
      "title": [{ "text": { "content": "Dense Retrieval Architectures Survey" } }]
    },
    "ID": {
      "rich_text": [{ "text": { "content": "lit-nir-001" } }]
    },
    "Status": {
      "status": { "name": "Pending" }
    },
    "Type": {
      "select": { "name": "literature_review" }
    },
    "Complexity": {
      "select": { "name": "High" }
    },
    "Project": {
      "relation": [{ "id": "project_page_id" }]
    }
  },
  "children": [
    {
      "object": "block",
      "type": "heading_2",
      "heading_2": {
        "rich_text": [{ "text": { "content": "Description" } }]
      }
    },
    {
      "object": "block",
      "type": "paragraph",
      "paragraph": {
        "rich_text": [{ "text": { "content": "Comprehensive review of dense retrieval methods..." } }]
      }
    },
    {
      "object": "block",
      "type": "heading_2",
      "heading_2": {
        "rich_text": [{ "text": { "content": "Acceptance Criteria" } }]
      }
    },
    {
      "object": "block",
      "type": "bulleted_list_item",
      "bulleted_list_item": {
        "rich_text": [{ "text": { "content": "20+ papers reviewed and synthesized" } }]
      }
    }
  ]
}
```

---

## Document History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2025-12-04 | Pilot System | Initial design |

# Work Tracking System

The pilot system uses a generic work tracking system that supports multiple work item types beyond just code features.

## Overview

Work items are tracked in `work_list.json` (or `feature_list.json` for backward compatibility) files within project directories. All work types share a common base schema with type-specific metadata.

## Tools

### feature_tracker (Primary)

```bash
# List all items in a project
uv run python -m pilot_tools feature_tracker '{"action": "list", "project": "my-project"}'

# Get next available item
uv run python -m pilot_tools feature_tracker '{"action": "next", "project": "my-project"}'

# Mark item as passing
uv run python -m pilot_tools feature_tracker '{"action": "mark_passing", "project": "my-project", "feature_id": "feat-001"}'

# Mark item as failing
uv run python -m pilot_tools feature_tracker '{"action": "mark_failing", "project": "my-project", "feature_id": "feat-001"}'
```

### work_tracker (Generic)

Same interface as feature_tracker but supports all work item types:

```bash
uv run python -m pilot_tools work_tracker '{"action": "list", "project": "research-project"}'
uv run python -m pilot_tools work_tracker '{"action": "next", "project": "research-project"}'
uv run python -m pilot_tools work_tracker '{"action": "update_status", "project": "research-project", "item_id": "h-001", "status": "completed"}'
```

## Work Item Types

### 1. Features (`feature`)

Code implementation tasks. ID prefix: `feat-` or `enforce-`, `duckdb-`, etc.

```json
{
  "id": "feat-001",
  "type": "feature",
  "description": "Implement user authentication",
  "status": "pending",
  "priority": "high",
  "passes": false,
  "dependencies": [],
  "acceptance_criteria": [
    "Login endpoint returns JWT token",
    "Password hashing uses bcrypt"
  ]
}
```

**Status values**: `pending`, `in_progress`, `blocked`, `completed`, `abandoned`

**Schema**: `system/schemas/work_item.yaml`

---

### 2. Research Hypotheses (`hypothesis`)

Scientific/analytical claims to test. ID prefix: `h-`

```json
{
  "id": "h-001",
  "type": "hypothesis",
  "title": "Caching reduces API latency by 50%",
  "description": "Adding Redis caching will reduce P95 latency...",
  "status": "in_progress",
  "metadata": {
    "prior_confidence": 0.6,
    "posterior_confidence": 0.75,
    "evidence_for": [
      "[Internal Test] Staging showed 55% P95 reduction"
    ],
    "evidence_against": [
      "[Analysis] Long-tail queries show only 10% cache hit"
    ],
    "verdict": null,
    "methodology": "A/B test with 24h baseline and comparison"
  }
}
```

**Verdict values**: `supported`, `refuted`, `insufficient`, `null`

**Agents**: `@web-researcher` for evidence, `@academic-researcher` for synthesis

**Schema**: `system/schemas/research_hypothesis.yaml`

---

### 3. Email Tasks (`email_task`)

Emails requiring action. ID prefix: `email-`

```json
{
  "id": "email-001",
  "type": "email_task",
  "title": "Respond: Q4 budget approval from CFO",
  "status": "pending",
  "priority": "critical",
  "metadata": {
    "email_id": "18d5a2f3b4c6e7f8",
    "thread_id": "18d5a2f3b4c6e7f8",
    "sender": "CFO <cfo@company.com>",
    "subject": "URGENT: Q4 Budget Approval",
    "received_at": "2024-11-27T09:15:00Z",
    "action": "respond",
    "deadline": "2024-11-27T17:00:00Z",
    "response_draft": "Hi, Approved! The budget looks good..."
  }
}
```

**Action values**: `respond`, `delegate`, `defer`, `archive`, `review`

**Priority guide**:
- `critical`: VIP sender, deadline today
- `high`: Important sender, deadline this week
- `medium`: Standard business, flexible timing
- `low`: Newsletters, FYI

**Agent**: `@email-agent` for triage and prioritization

**Schema**: `system/schemas/email_task.yaml`

---

### 4. Company Research (`company_research`)

Business intelligence gathering. ID prefix: `co-`

```json
{
  "id": "co-001",
  "type": "company_research",
  "title": "Competitor Analysis: RivalTech Inc",
  "status": "in_progress",
  "priority": "high",
  "metadata": {
    "company_name": "RivalTech Inc",
    "domain": "rivaltech.io",
    "research_purpose": "competitor_analysis",
    "industry": "Enterprise AI",
    "research_questions": [
      "What are their core product capabilities?",
      "How does their pricing compare?",
      "What are their key strengths/weaknesses?"
    ],
    "findings": [
      {
        "question": "What are their core product capabilities?",
        "answer": "Strong in NLP, weak in vision...",
        "confidence": "high",
        "sources": ["https://rivaltech.io/docs"]
      }
    ],
    "key_people": [
      {"name": "Jane Doe", "role": "CEO", "linkedin": "..."}
    ],
    "risk_factors": [
      "Single customer concentration (40% revenue)"
    ],
    "momentum_assessment": "accelerating"
  }
}
```

**Research purpose**: `competitor_analysis`, `investment_target`, `partnership_evaluation`, `acquisition_target`, `vendor_assessment`

**Confidence levels**: `high` (multiple sources), `medium` (single authoritative), `low` (inference)

**Agent**: `@company-researcher` for comprehensive 12-dimension analysis

**Schema**: `system/schemas/company_research.yaml`

---

## Schema Files

All schemas are in `system/schemas/`:

| File | Description |
|------|-------------|
| `work_item.yaml` | Base schema for all work items |
| `research_hypothesis.yaml` | Bayesian hypothesis tracking with confidence |
| `email_task.yaml` | Email triage with action workflow |
| `company_research.yaml` | 12-dimension company intelligence |

## Project Structure

```
projects/my-project/
├── feature_list.json    # Work items (or work_list.json)
├── progress.txt         # Human-readable progress log
└── .runs/               # Run manifests (agent provenance)
```

## Status Transitions

All work types share these valid transitions:

```
pending ──→ in_progress ──→ completed
   │            │              │
   │            ↓              │
   │         blocked           │
   │            │              │
   ↓            ↓              ↓
abandoned ←────────────── (reopen)
```

**Completion requirements vary by type** - see individual schemas for details.

## Integration with Agents

| Work Type | Primary Agent | Supporting Agents |
|-----------|---------------|-------------------|
| feature | `@builder` | `@verifier`, `@git-reviewer` |
| hypothesis | `@academic-researcher` | `@web-researcher` |
| email_task | `@email-agent` | - |
| company_research | `@company-researcher` | `@web-researcher` |

## Initializer Support

The `@initializer` agent can generate work lists for different project types:

```bash
uv run python -m pilot_core.invoke initializer "
  Initialize project: market-analysis
  Type: research

  Generate hypotheses for investigating the AI infrastructure market.
"
```

Supported project types: `code`, `research`, `email_triage`, `company_intel`

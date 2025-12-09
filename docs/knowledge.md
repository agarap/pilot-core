# Knowledge Capture Workflow

> This document explains when and how to capture lessons and decisions in the knowledge base.
> For detailed workflows, see [workflows.md](workflows.md).
> For tool documentation, see [tools.md](tools.md).

## When to Create Knowledge Entries

### Lessons vs Decisions

| Type | When to Create | Example |
|------|----------------|---------|
| **Lesson** | Insights from implementation experience - what worked, what didn't, patterns discovered | "Long-running agent sessions accumulate errors" |
| **Decision** | Architectural choices with trade-offs, alternatives rejected | "Use PostgreSQL over MongoDB for user data" |

**Rule of thumb:**
- **Lesson**: "I learned that..." (retrospective insight)
- **Decision**: "We chose X over Y because..." (deliberate choice)

### Triggers for Each Type

**Create a LESSON when:**
- A bug was caught during review
- Something took longer than expected
- A pattern emerged (good or bad)
- You'd do something differently next time

**Create a DECISION when:**
- Multiple valid approaches were considered
- The choice affects future development
- Others would benefit from knowing WHY
- Trade-offs were explicitly evaluated

---

## Quality Criteria

Knowledge entries are scored on four dimensions (25 points each, 100 total):

### Lesson Quality Scoring

| Criterion | Points | What It Means |
|-----------|--------|---------------|
| Has evidence | 25 | Lessons have supporting evidence, not just opinion |
| Has recommendations | 25 | Actionable takeaways others can follow |
| Has related_files | 25 | Traceable to specific code/files |
| Has depth | 25 | Multiple lessons OR detailed context (>100 chars) |

### Decision Quality Scoring

| Criterion | Points | What It Means |
|-----------|--------|---------------|
| Has alternatives | 25 | Documents options that were considered |
| Has consequences | 25 | Explains impact (enables/prevents/requires) |
| Has clear context | 25 | Explains why decision was needed (>50 chars) |
| Has maturity | 25 | Accepted status OR complete consequences |

### Target Quality

- **Target score**: 70+ (good quality)
- **Threshold for flagging**: 50 (below this needs improvement)

Check knowledge base health:
```bash
uv run python -m pilot_tools knowledge_stats
```

---

## How Knowledge Is Used

### Context Tool Integration

The `context.py` tool searches knowledge/ when gathering context for tasks:

```bash
uv run python tools/context.py "implement rate limiting"
```

Output includes:
- Top 3 relevant lessons matching the query
- Top 3 relevant decisions
- Score-based ranking across multiple search terms

### Agent Context Injection

When agents are invoked via `lib.invoke`, relevant knowledge is included in their context:

1. Query terms extracted from task description
2. Knowledge base searched for matching lessons/decisions
3. Top matches included in agent prompt
4. Agents can reference past learnings

### Search Integration

Knowledge entries are indexed in `data/index.json` and searchable:

```python
from lib.search import search_by_type

# Find lessons about a topic
lessons = search_by_type("lesson", "rate limiting")

# Find decisions about architecture
decisions = search_by_type("decision", "database")
```

Filter by category or severity:
```bash
# Via knowledge_stats
uv run python -m pilot_tools knowledge_stats --json | jq '.by_category'
uv run python -m pilot_tools knowledge_stats --json | jq '.by_severity'
```

---

## Examples: Good vs Poor Entries

### Good Lesson Example

```yaml
name: long-running-agents
title: "Lessons from Implementing Long-Running Agent Pattern"
date: "2025-01-15"
severity: high
category: architecture

context: |
  Implemented Anthropic's long-running agent pattern for the Pilot system.
  Sessions that attempted multiple features had inconsistencies between
  early and late implementations.

lessons:
  - title: "One feature per session produces better quality"
    description: |
      Long-running agent sessions accumulate context, errors, and drift.
      By implementing exactly one feature per session, each gets focused
      attention and errors don't compound.
    evidence: |
      Sessions that attempted multiple features often had inconsistencies
      between early and late implementations. Single-feature sessions
      produced more uniform quality.

recommendations:
  - "Always start sessions by reading progress.txt"
  - "End sessions cleanly - feature complete or not started"
  - "Commit after each feature completion, not in bulk"

related_files:
  - tools/feature_tracker.py
  - lib/resume.py
```

**Why it's good (Score: 100/100):**
- Evidence: Specific observation about inconsistencies
- Recommendations: Three actionable items
- Related files: Links to relevant code
- Depth: Multiple lessons with detailed context

### Poor Lesson Example

```yaml
name: testing-stuff
title: "Testing Notes"
date: "2025-01-15"
severity: medium
category: debugging

context: Testing was hard.

lessons:
  - title: "Tests are important"
    description: Should write more tests.
```

**Why it's poor (Score: 0/100):**
- No evidence (just opinion)
- No recommendations
- No related_files
- No depth (vague context, single shallow lesson)

### Good Decision Example

```yaml
id: "005"
title: "Use YAML over JSON for agent definitions"
date: "2025-01-15"
status: accepted

context: |
  Agent definitions need to be human-readable and support multi-line
  strings for prompts. We evaluated JSON, YAML, and TOML formats.

decision: |
  Use YAML for all agent definition files in agents/*.yaml.
  YAML supports multi-line strings naturally and is more readable
  for configuration with embedded prompts.

alternatives:
  - option: "JSON"
    rejected_because: "Multi-line strings require escaping, less readable"
  - option: "TOML"
    rejected_because: "Less familiar to team, limited tooling support"

consequences:
  enables:
    - Human-readable agent prompts
    - Easy editing without escaping
  prevents:
    - Direct use in JavaScript without parsing
  requires:
    - PyYAML dependency
    - YAML syntax knowledge
```

**Why it's good (Score: 100/100):**
- Alternatives: Two options with clear rejection reasons
- Consequences: All three categories filled
- Context: Explains the problem being solved
- Status: Accepted (mature decision)

---

## Quick Reference

### Capturing a Lesson

```bash
# After completing a feature, reflect on lessons
uv run python -m pilot_tools suggest_lesson --feature core-001 --project myproject

# Generate lesson file from answers
uv run python -m pilot_tools suggest_lesson --generate --answers '{
  "name": "api-rate-limiting",
  "title": "Lessons from API Rate Limiting",
  "severity": "medium",
  "challenges": "API calls were failing intermittently...",
  "patterns": "Exponential backoff with jitter works better than fixed delays",
  "differently": "Start with conservative rate limits, increase gradually"
}'
```

### Checking Knowledge Base Health

```bash
# Full text report
uv run python -m pilot_tools knowledge_stats

# JSON output for scripting
uv run python -m pilot_tools knowledge_stats --json

# Check quality scores
uv run python -m pilot_tools knowledge_stats --json | jq '.low_quality_entries'

# Custom quality threshold
uv run python -m pilot_tools knowledge_stats '{"quality_threshold": 75}'
```

### Template Locations

| Template | Location |
|----------|----------|
| Lesson template | `knowledge/templates/lesson-template.yaml` |
| Decision template | `knowledge/templates/decision-template.yaml` |

### Prompting Questions (suggest_lesson)

When reflecting on lessons, consider:

1. **What unexpected challenges did you encounter?**
   - Things that took longer than expected
   - Required multiple attempts
   - Surprised you

2. **What would you do differently next time?**
   - Different approach, tools, order of operations
   - Changed assumptions

3. **What pattern emerged that others should know?**
   - Reusable insights
   - Anti-patterns to avoid
   - Techniques that worked well

4. **Did you make a decision that should be documented?**
   - Architectural choices
   - Trade-offs made
   - Rejected alternatives

---

## Knowledge Base Structure

```
knowledge/
├── decisions/           # Architectural decisions (ADRs)
│   ├── _template.yaml   # Decision template
│   ├── 001-bootstrap.yaml
│   └── ...
├── lessons/             # Implementation lessons learned
│   ├── long-running-agents.yaml
│   └── ...
└── templates/           # Canonical templates
    ├── decision-template.yaml
    └── lesson-template.yaml
```

### Naming Conventions

- **Decisions**: `NNN-short-name.yaml` (e.g., `005-yaml-over-json.yaml`)
- **Lessons**: `descriptive-name.yaml` (e.g., `api-rate-limiting.yaml`)

### Finding the Next Decision Number

```bash
ls knowledge/decisions/*.yaml | grep -v template | wc -l
```

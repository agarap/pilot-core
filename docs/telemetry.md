# Enforcement Telemetry System

## Overview

The enforcement telemetry system records events from enforcement mechanisms throughout the pilot system:

- **guards.py** - Import guards that block prohibited modules
- **violation_watcher.py** - Rule violation detection
- **precommit.py** - Git pre-commit hook enforcement
- **Git hooks** - commit-msg and post-commit hooks

All events are written to a JSON Lines file at `data/enforcement_events.jsonl`.

### Why Telemetry Exists

Telemetry provides observability for enforcement mechanisms. Without it, you can't answer:

- Are agents learning the rules? (decreasing blocked imports over time)
- Is the review process being followed? (bypasses should be zero)
- Which rules need better enforcement? (high violation counts)
- Is overall enforcement health improving? (score trend)

This data enables evidence-based decisions about rule changes, enforcement improvements, and agent training.

---

## How to Query Stats

### CLI Commands

```bash
# Event counts by type (default: last 7 days)
uv run python tools/enforcement_stats.py stats

# Custom time window
uv run python tools/enforcement_stats.py stats --days 30

# List recent events (default: last 1 day)
uv run python tools/enforcement_stats.py events

# Filter events by type
uv run python tools/enforcement_stats.py events --type import_blocked

# Filter events by source
uv run python tools/enforcement_stats.py events --source guards.py

# Effectiveness score
uv run python tools/enforcement_stats.py score

# Check threshold alerts
uv run python tools/enforcement_stats.py alert

# Check only critical alerts (for scripts/cron)
uv run python tools/enforcement_stats.py alert --quiet

# Generate markdown dashboard
uv run python tools/enforcement_stats.py dashboard

# Save dashboard to file
uv run python tools/enforcement_stats.py dashboard --output docs/dashboard.md
```

### JSON API Format

For programmatic use, pass JSON directly:

```bash
uv run python tools/enforcement_stats.py '{"action": "stats", "days": 14}'
uv run python tools/enforcement_stats.py '{"action": "score"}'
uv run python tools/enforcement_stats.py '{"action": "alert", "quiet": true}'
uv run python tools/enforcement_stats.py '{"action": "events", "event_type": "import_blocked", "limit": 10}'
uv run python tools/enforcement_stats.py '{"action": "dashboard", "output": "docs/dashboard.md"}'
```

### Example Output

**Stats action:**
```
Enforcement Stats (last 7 days)
=============================================

Event Type                    Count
-------------------------------------
commit_completed                 12
commit_review_required           12
import_blocked                    3
violation_detected                1
-------------------------------------
TOTAL                            28
```

**Score action:**
```
Enforcement Effectiveness Score
=======================================================

  [~] Overall Rating: GOOD
      Enforcement is working with minor issues

Score Breakdown
-------------------------------------------------------

  Violations:
    Current week:     1  [-] stable
    Previous week:    2
    Threshold:     <5/week for good, <2/week for excellent

  Import Blocked:
    Current week:     3  [v] decreasing
    Previous week:    7
    Threshold:     decreasing is good

  Bypasses:
    Current week:     0  [-] stable
    Previous week:    0
    Threshold:     0 is required for good/excellent

-------------------------------------------------------
Period: last 7 days vs 8-14 days ago
Total events: 28 (current) / 35 (previous)
```

---

## How to Add Telemetry to New Rules

### Basic Usage

```python
from lib.telemetry import record_event, EventType

# Record an enforcement event
record_event(EventType.IMPORT_BLOCKED, "guards.py", {"module": "requests"})

# Record with more details
record_event(
    EventType.VIOLATION_DETECTED,
    "violation_watcher.py",
    {
        "rule": "web-access-policy",
        "file": "tools/scraper.py",
        "line": 42,
        "severity": "high",
        "description": "Direct use of requests.get() instead of web_fetch tool"
    }
)
```

### Available Event Types

```python
from lib.telemetry import EventType

# Import guards (guards.py)
EventType.IMPORT_BLOCKED      # Prohibited import was blocked
EventType.IMPORT_ALLOWED      # Import passed validation

# Violation watcher (violation_watcher.py)
EventType.VIOLATION_DETECTED  # Rule violation found

# Pre-commit hook (precommit.py)
EventType.COMMIT_REVIEW_REQUIRED   # Commit triggered review requirement
EventType.COMMIT_REVIEW_BYPASSED   # Commit made without review (CRITICAL)
EventType.COMMIT_GITIGNORE_ONLY    # Commit with only .gitignore changes

# Git hooks
EventType.BYPASS_REVIEW           # Review bypassed via PILOT_SKIP_REVIEW=1
EventType.BYPASS_AGENT_TRAILER    # Agent trailer bypassed via PILOT_SKIP_AGENT_TRAILER=1

# Post-commit hook
EventType.COMMIT_COMPLETED        # Commit successfully completed
```

### Best Practices for Details Dict

**Include the triggering context:**
```python
# Good - includes what was blocked and why
record_event(EventType.IMPORT_BLOCKED, "guards.py", {
    "module": "requests",
    "reason": "Direct HTTP requests prohibited - use Parallel API tools"
})

# Good - includes rule, location, and severity
record_event(EventType.VIOLATION_DETECTED, "violation_watcher.py", {
    "rule": "web-access-policy",
    "file": "tools/new_tool.py",
    "line": 15,
    "severity": "high"
})
```

**Keep details concise but informative:**
```python
# Good - actionable information
{"module": "httpx", "reason": "Use web_fetch tool instead"}

# Bad - too verbose
{"module": "httpx", "full_traceback": "...", "all_locals": {...}}

# Bad - too sparse
{"blocked": True}
```

---

## Using Data for Decision-Making

### Effectiveness Scores

The system computes an overall effectiveness rating by comparing the current week to the previous week:

| Rating | Criteria |
|--------|----------|
| **excellent** | violation_detected < 2/week AND import_blocked decreasing AND no bypasses |
| **good** | violation_detected < 5/week AND import_blocked stable/decreasing AND no bypasses |
| **concerning** | violations 5-10/week OR import_blocked increasing OR any bypasses |
| **critical** | violations > 10/week OR bypasses > 1 |

### Questions Telemetry Can Answer

**Are agents learning the rules?**
- Look at `import_blocked` trend over time
- Decreasing counts indicate agents are internalizing the rules
- Flat or increasing counts suggest rules need better documentation or enforcement

**Is the review process being followed?**
- `commit_review_bypassed` should always be 0
- Any non-zero value requires immediate investigation
- Compare `commit_review_required` to total commits for coverage

**Which rules need better enforcement?**
- High `violation_detected` for specific rules indicates gaps
- Look at the `rule` field in violation details
- Consider adding code-based guards for frequently violated rules

**Is overall enforcement health improving?**
- Track `score` rating over time
- Watch for rating degradation (good -> concerning)
- Investigate root causes when score drops

### When to Modify Enforcement Rules

**Add new rules when:**
- Violations indicate a gap in coverage
- A new attack vector or anti-pattern emerges
- Code review repeatedly catches the same issue

**Strengthen rules when:**
- Same violations keep recurring despite existing rules
- Prompt-based rules are being ignored
- Code-based enforcement is feasible (guards.py, hooks)

**Remove rules when:**
- Zero events for extended period (30+ days)
- The rule addresses an obsolete concern
- The rule is redundant with another enforcement mechanism

**Relax rules when:**
- Frequent bypasses indicate rule is too strict
- Legitimate use cases are being blocked
- Cost of enforcement exceeds benefit

---

## Schema Documentation

The full schema is defined in `data/enforcement_stats.yaml`. Key sections:

### Event Type Reference

| Event Type | Source | Interpretation |
|------------|--------|----------------|
| `import_blocked` | guards.py | Decreasing is good - agents learning rules |
| `import_allowed` | guards.py | Informational - normal operation |
| `violation_detected` | violation_watcher.py | Rare is good - each is a failure |
| `commit_review_required` | precommit.py | Expected baseline - 1:1 with commits |
| `commit_review_bypassed` | precommit.py | Zero is good - CRITICAL if >0 |
| `commit_gitignore_only` | precommit.py | Informational - low-risk commits |
| `bypass_review` | git hooks | Low is good - emergency only |
| `bypass_agent_trailer` | git hooks | Low is good - manual commits |
| `commit_completed` | git hooks | Informational - commit metadata |

### Details Field Schemas

**import_blocked / import_allowed:**
```json
{
  "module": "requests",
  "reason": "Direct HTTP requests prohibited"
}
```

**violation_detected:**
```json
{
  "rule": "web-access-policy",
  "file": "tools/scraper.py",
  "line": 42,
  "severity": "high",
  "description": "Direct use of requests.get()"
}
```

**commit_review_required / commit_review_bypassed:**
```json
{
  "commit_sha": "abc1234",
  "files_changed": 5,
  "reviewer": "git-reviewer",
  "bypass_method": "git commit --no-verify"
}
```

**bypass_review / bypass_agent_trailer:**
```json
{
  "reason": "PILOT_SKIP_REVIEW environment variable",
  "user": "Developer <dev@example.com>",
  "branch": "main",
  "files": ["lib/telemetry.py"],
  "file_count": 1
}
```

**commit_completed:**
```json
{
  "commit_sha": "abc1234",
  "branch": "main",
  "files_changed": 5,
  "rules_checked": ["git-reviewer", "web-import", "task-tool"],
  "rules_count": 3,
  "user": "Developer <dev@example.com>"
}
```

### Threshold Configuration

From `data/enforcement_stats.yaml`:

```yaml
effectiveness_thresholds:
  scoring:
    excellent:
      criteria:
        - "violation_detected < 2/week"
        - "import_blocked decreasing trend"
        - "commit_review_bypassed = 0"
    good:
      criteria:
        - "violation_detected < 5/week"
        - "import_blocked stable or decreasing"
        - "commit_review_bypassed = 0"
    concerning:
      criteria:
        - "violation_detected 5-10/week"
        - "import_blocked increasing"
        - "OR commit_review_bypassed > 0"
    critical:
      criteria:
        - "violation_detected > 10/week"
        - "OR commit_review_bypassed > 1"
```

### Data Retention

Events are retained for 30 days by default. Clean up old events with:

```bash
# Preview what would be removed
uv run python tools/enforcement_stats.py cleanup --dry-run

# Remove events older than 30 days (default)
uv run python tools/enforcement_stats.py cleanup

# Custom retention period
uv run python tools/enforcement_stats.py cleanup --days 60
```

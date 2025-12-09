# Pilot Workflows

> This document contains detailed workflows for common tasks.
> For essential agent configuration, see [core-config.md](core-config.md).
> For tool documentation, see [tools.md](tools.md).

## Run System

Every unit of work is a **run** with a unique ID:

```
run_id: 20250126_143022_abc123
```

Runs link everything together:
- Tool calls include `run_id` in logs
- Agent outputs reference the run
- Git commits mention the run ID

### Run Manifests

Each project tracks runs in `.runs/`:

```
projects/research/
  .runs/
    001_Research_Claude_API.yaml    # What was asked, what changed
  findings/
    api-limits.md                   # Actual output
```

Manifest format:
```yaml
id: "20250126_143022_abc123"
number: 1
task: "Research Claude API rate limits"
status: completed
started: "2025-01-26T14:30:22"
completed: "2025-01-26T14:35:00"
agents:
  - web-researcher
tools:
  - web_search
files_created:
  - findings/api-limits.md
summary: "Documented rate limits from official docs"
```

### Creating Runs

```python
from lib.run import Run

with Run.create("Research topic X", project="research") as run:
    run.add_agent("web-researcher")
    # ... do work ...
    run.add_file_created("findings/x.md")
    # auto-completes and saves manifest on exit
```

---

## Main Workflow

1. **Gather context**: `uv run python tools/context.py "task description"`
2. **Create run**: `Run.create("task", project="name")`
3. **Delegate** to subagent(s): `uv run python -m pilot_core.invoke <agent> "task"`
4. **Agents work** -> output files to `projects/<project>/`
5. **Monitor progress** -> Sleep and check agent output after each step
6. **Review** via @git-reviewer: `uv run python -m pilot_core.invoke git-reviewer "Review changes"`
7. **Complete run** -> manifest saved to `.runs/`
8. **Commit** with run ID in message (index auto-regenerated)
9. **Document knowledge** -> Check if decision or lesson should be logged (see below)

### Progress Monitoring Rule

**After each delegated task, sleep and watch for progress:**
- When multiple agents are running in parallel, periodically check their output
- Use `BashOutput` tool to monitor background processes
- Don't overwhelm the system - allow time between checks
- Report progress updates to keep the human informed
- This ensures agents have time to work and avoids rate limiting

### Non-Blocking Agent Invocation

Agents can be launched in background mode for parallel execution:

```python
# Blocking (default) - waits for completion
result = await invoke_agent("builder", "Create new tool")

# Non-blocking - returns immediately with run_id
run_id = await invoke_agent("builder", "Create new tool", background=True, project="my-project")
# Returns: {'run_id': 'run_abc123', 'background': True, 'project': 'my-project', ...}
```

**Checking progress:**

```bash
# Check status of background agents
uv run python -m pilot_tools agent_status '{"project": "my-project"}'
uv run python -m pilot_tools agent_status '{"run_ids": ["run_abc123"], "project": "my-project"}'
uv run python -m pilot_tools agent_status '{"list_all": true}'
```

**Waiting for completion:**

```python
from lib.progress import wait_for_agent, StaleAgentError, AgentNotFoundError

# Wait with timeout and stale detection
try:
    progress = wait_for_agent("my-project", "run_abc123", timeout=600)
    print(f"Agent completed: {progress.result_summary}")
except TimeoutError:
    print("Agent timed out")
except StaleAgentError:
    print("Agent appears stuck (no heartbeat)")
```

**Progress file schema:**

```yaml
run_id: "run_abc123"
agent: "builder"
project: "my-project"
started_at: "2025-12-07T10:00:00Z"
status: "running"  # pending | running | completed | failed | stalled
last_heartbeat: "2025-12-07T10:05:32Z"
phase: "Creating files"
messages_processed: 42
artifacts_created: ["lib/new.py"]
```

**Polling strategy:**
- First check: 30 seconds after launch
- Backoff: 1min, 2min, 4min, max 10min
- Batch checking: one `agent_status` call for multiple agents
- Stale threshold: 5 minutes without heartbeat = potentially stuck

### Parallel Task Completion Rule (MANDATORY)

**ALWAYS wait for ALL parallel tasks to complete before continuing to the next phase.**

When you launch multiple background tasks (via `lib.invoke` or `parallel_task`):
1. **Track all task IDs** - Keep a list of all launched task IDs
2. **Check ALL statuses** - Before proceeding, verify every task has `status: completed`
3. **Collect ALL results** - Use `BashOutput` on each background task to collect its output
4. **Never proceed early** - Do NOT move to compilation/synthesis until all tasks finish
5. **Handle failures** - If a task fails, note the failure but still wait for remaining tasks

### Git Commit Message Format

```
Run 001: Research Claude API rate limits

Run ID: 20250126_143022_abc123
Agents: web-researcher

Found rate limit docs, created summary.

Generated with [Claude Code](https://claude.ai/code)
via [Happy](https://happy.engineering)

Co-Authored-By: Claude <noreply@anthropic.com>
Co-Authored-By: Happy <yesreply@happy.engineering>
```

---

## Commit Approval Flow

All git commits in the pilot system require @git-reviewer approval before they can be committed.
This ensures quality, security, and consistency across all changes.

### Why Review is Required

- **Quality Gate**: Catches naming issues, missing tests, incomplete implementations
- **Security**: Prevents accidental commit of secrets, credentials, or sensitive data
- **Consistency**: Enforces project conventions and patterns
- **Audit Trail**: Every change has a review on record

### Step-by-Step Flow

1. **Stage changes**: `git add -A`
2. **Request review**: `uv run python -m pilot_core.invoke git-reviewer "Review staged changes" -v`
3. **Wait for verdict**: APPROVED or NEEDS_CHANGES
4. **If APPROVED**: `uv run python -m pilot_core.approve`
5. **Commit**: `git commit -m "your message"`

### Hash Verification (Security Feature)

The approval system uses SHA-256 hashing to prevent approval gaming:

1. When you run `uv run python -m pilot_core.approve`:
   - Computes SHA-256 hash of `git diff --cached` output
   - Stores hash in `.git/REVIEW_APPROVED` marker

2. When you run `git commit`:
   - Pre-commit hook recomputes hash of current staged diff
   - Compares against stored hash
   - **Blocks commit if hashes don't match**

### Approval Expiry

Approvals expire after **1 hour** to prevent stale approvals.

### Bypass (Emergency Only)

In emergencies, bypass the review requirement:

```bash
PILOT_SKIP_REVIEW=1 git commit -m "Emergency fix"
```

**Use sparingly**: Bypasses are logged and should be justified.

**Exception**: `.gitignore`-only changes automatically skip review (safe, low-risk).

---

## Post-Commit Knowledge Documentation

**After significant commits, the system automatically prompts for knowledge capture.**

The post-commit hook runs `lib/knowledge_check.py` which analyzes commits for significance:
- **Files changed**: More than 5 files triggers a prompt
- **Lines added**: More than 100 lines triggers a prompt
- **New modules**: Any new Python module triggers a prompt
- **Architectural changes**: Changes to `lib/`, `agents/`, `system/` trigger a prompt
- **Commit message**: Keywords like "refactor", "implement", "redesign" trigger a prompt

### Capture Types

| Type | Trigger | Location |
|------|---------|----------|
| **Decision** | Changes to `system/rules/`, `agents/`, `lib/` | `knowledge/decisions/NNN-name.yaml` |
| **Lesson** | Significant implementation work | `knowledge/lessons/YYYY-MM-DD-name.yaml` |
| **Both** | Large architectural changes | Both locations |

### Bypassing Knowledge Check

For bulk commits or automated operations:

```bash
PILOT_SKIP_KNOWLEDGE_CHECK=1 git commit -m "Bulk update"
```

---

## Session Resume System (Error Recovery)

> **Advanced Feature**: This system is for recovering from crashed or interrupted sessions.
> Use when: session crashed, network issues caused context loss, or resuming after terminal closed unexpectedly.
> Not needed for: normal daily workflow, starting new tasks.

Claude Code sessions can get stuck or interrupted (network issues, crashes, user closing terminal).
The resume system (`lib/session.py` and `lib/resume.py`) helps recover from these situations.

### Checking for Stuck Sessions

If you suspect a previous session was interrupted, check for stuck sessions:

```bash
uv run python -m pilot_core.resume --list
```

### CLI Commands

```bash
# List stuck/errored sessions (default)
uv run python -m pilot_core.resume --list

# List all recent sessions
uv run python -m pilot_core.resume --all

# Generate resume prompt for a session
uv run python -m pilot_core.resume <session-id>

# Copy resume prompt to clipboard (macOS)
uv run python -m pilot_core.resume <session-id> --clipboard
```

### Session States

- **in_progress**: Active session with recent activity
- **stuck**: Has pending todos but no activity for >5 minutes
- **error**: Last tool call resulted in an error
- **abandoned**: No pending todos but no activity for >30 minutes
- **completed**: All todos marked completed

---

## Feature-Based Projects

For projects with `feature_list.json`, use this workflow. This applies when a project has a structured feature list that tracks implementation progress across sessions.

### Detecting Feature-Based Projects

Check if a project uses feature tracking:

```bash
# Check for feature_list.json in project
ls projects/<project>/feature_list.json 2>/dev/null && echo "Feature-based project"
```

If `feature_list.json` exists, follow the Session Start Protocol below.

---

### Session Start Protocol (REQUIRED)

**At the START of every session working on a feature-based project**, follow these steps in order:

```
+-------------------------------------------------------------+
|                   SESSION START PROTOCOL                     |
+-------------------------------------------------------------+
|  1. READ PROGRESS    ->  Understand current state            |
|  2. GET NEXT FEATURE ->  Know what to implement              |
|  3. RUN INIT (once)  ->  Set up environment if needed        |
+-------------------------------------------------------------+
```

#### Step 1: Read Progress Summary

```bash
# Read progress.txt to understand what's been done
cat projects/<project>/progress.txt
```

This file contains:
- Previous session summaries
- Completed features
- Known issues
- What's next

**Why**: Context from previous sessions prevents duplicate work and informs decisions.

#### Step 2: Get Next Feature

```bash
# Get the next feature to implement
uv run python -m pilot_tools feature_tracker '{"action": "next", "project": "<project>"}'
```

The feature tracker:
- Returns the next incomplete feature
- Respects dependency order (won't return a feature if its dependencies aren't done)
- Shows feature ID, name, description, and test_command

**Why**: Ensures you work on the right feature in the right order.

#### Step 3: Run Project Init (First Time Only)

```bash
# If init.sh exists and this is first session
if [ -f projects/<project>/init.sh ]; then
    bash projects/<project>/init.sh
fi
```

**Why**: Ensures the environment is properly configured before implementation.

### Complete Feature Workflow

After session start, follow this workflow for each feature:

```
SESSION START
     |
     v
+-----------------+
| 1. Read         |  cat projects/<project>/progress.txt
|    progress.txt |
+--------+--------+
         |
         v
+-----------------+
| 2. Get next     |  uv run python -m pilot_tools feature_tracker \
|    feature      |    '{"action": "next", "project": "<project>"}'
+--------+--------+
         |
         v
+-----------------+
| 3. Run init.sh  |  bash projects/<project>/init.sh
|    (if exists)  |  (first time only)
+--------+--------+
         |
         v
+-----------------+
| 4. IMPLEMENT    |  Write code for the feature
|    the feature  |  (delegate to @builder)
+--------+--------+
         |
         v
+-----------------+
| 5. TEST         |  Run the test_command from feature spec
|    the feature  |  (if provided)
+--------+--------+
         |
         v
+-----------------+
| 6. MARK         |  uv run python -m pilot_tools feature_tracker \
|    PASSING      |    '{"action": "mark_passing", ...}'
+--------+--------+
         |
         v
+-----------------+
| 7. UPDATE       |  Add session summary to TOP of
|    progress.txt |  projects/<project>/progress.txt
+--------+--------+
         |
         v
+-----------------+
| 8. GIT REVIEW   |  uv run python -m pilot_core.invoke git-reviewer \
|    & COMMIT     |    "Review changes"
+--------+--------+
         |
         v
    SESSION END
    (one feature per session)
```

### Feature Tracker Commands

```bash
# List all features with status
uv run python -m pilot_tools feature_tracker '{"action": "list", "project": "<project>"}'

# Get next incomplete feature (respects dependencies)
uv run python -m pilot_tools feature_tracker '{"action": "next", "project": "<project>"}'

# Mark feature as passing (after implementation verified)
uv run python -m pilot_tools feature_tracker '{"action": "mark_passing", "project": "<project>", "feature_id": "core-001"}'
```

### Progress.txt Format

When updating progress.txt, add a new section at the TOP:

```markdown
## Session YYYY-MM-DD HH:MM (<feature-id> Complete)

### Completed
- <feature-id>: <feature description>
  - Brief notes on what was done

### In Progress
- None (clean state)

### Next Up
- <next-feature-id>: <next feature description>

### Known Issues
- Any issues discovered (or "None")
```

### One Feature Per Session Rule

**IMPORTANT**: Implement exactly ONE feature per session.

Why:
- Long sessions accumulate errors
- Clean handoffs produce better results
- Each feature gets focused attention
- Progress is always committed

When a feature is complete:
1. Mark it passing
2. Update progress.txt
3. Commit changes
4. End session

### Feature Tracker vs Session Resume

| Aspect | Session Resume | Feature Tracker |
|--------|----------------|-----------------|
| **Purpose** | Recover crashed/stuck sessions | Track deliberate multi-session work |
| **Trigger** | Session interruption | "Continue implementing" requests |
| **State stored in** | `~/.claude/` (Claude Code logs) | `projects/<project>/feature_list.json` |
| **Commands** | `uv run python -m pilot_core.resume` | `uv run python -m pilot_tools feature_tracker` |
| **When to use** | Agent detects stuck session | Human says "continue next feature" |

**Rule**: "continue the next feature" -> Feature Tracker. Session crashed -> Session Resume.

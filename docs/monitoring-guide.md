# Agent Monitoring Guide for Pilot

## Overview

This guide explains the enhanced monitoring capabilities for background agents, including:
- Adaptive polling based on historical latencies
- Automatic progress tracking
- Patient monitoring strategies

## Quick Start

### Monitor All Active Agents

```python
from lib.monitor import monitor_agents

# Monitor all agents in a project
results = monitor_agents("my-project")
```

### Spawn and Monitor

```python
from lib.monitor import spawn_and_monitor

# Spawn agent and monitor until completion
result = spawn_and_monitor(
    agent_name="web-researcher",
    task="Research AI safety",
    project="research",
    verbose=True
)
```

## Adaptive Polling

The system now uses **historical agent latencies** to set intelligent polling intervals:

| Agent Type | Typical Duration | Initial Poll | After 2m | Timeout |
|------------|-----------------|--------------|----------|---------|
| git-reviewer | 81s | 8s | 24s | 280s |
| builder | 448s | 30s | 90s | 2692s |
| web-researcher | 198s | 20s | 60s | 3337s |
| academic-researcher | 1190s | 30s | 90s | 4404s |

### How It Works

1. **Initial Phase (0-30s)**: Frequent polling at base interval
2. **Middle Phase (30s-2m)**: Gradual backoff with multiplier
3. **Late Phase (2m+)**: Maximum interval to conserve resources
4. **Past Expected Time**: Resume frequent polling if exceeding median

## Progress Tracking

The invoke_agent function now **automatically tracks progress**:

- Creates progress file before spawning
- Updates heartbeat every 5 messages
- Tracks tool usage phases
- Records completion/failure status

### Progress File Structure

```yaml
run_id: run_abc123
agent: web-researcher
project: my-project
status: running
phase: "Using tool: web_search"
messages_processed: 42
last_heartbeat: "2025-12-07T10:30:45"
artifacts_created:
  - "research_report.md"
```

## Monitoring Strategies

### 1. Patient Single Agent

```python
from lib.progress_enhanced import wait_for_agent_adaptive

# Wait with adaptive polling based on historical data
progress = wait_for_agent_adaptive(
    project="my-project",
    run_id="run_abc123",
    agent_name="builder",  # Uses builder-specific timings
    verbose=True  # Shows progress updates
)
```

### 2. Multiple Parallel Agents

```python
from lib.monitor import monitor_agents

# Launch multiple agents
run_ids = []
for task in tasks:
    result = invoke_agent("builder", task, background=True)
    run_ids.append(result["run_id"])

# Monitor all at once
results = monitor_agents("my-project", run_ids)
```

### 3. First-to-Complete

```python
# Return as soon as any agent completes
results = monitor_agents(
    "my-project",
    run_ids=["run_1", "run_2", "run_3"],
    return_on_first_complete=True
)
```

## CLI Tools

### Check Agent Status

```bash
# All agents in project
uv run python -m pilot_tools agent_status '{"project": "my-project"}'

# Specific agents
uv run python -m pilot_tools agent_status '{"run_ids": ["run_abc"], "project": "my-project"}'

# All active agents across all projects
uv run python -m pilot_tools agent_status '{"list_all": true}'
```

### Analyze Historical Latencies

```bash
# Generate/update polling configuration
uv run python tools/analyze_agent_latencies.py
```

## Best Practices for Pilot

### 1. Always Use Project Names

When delegating, always specify the project to enable monitoring:

```python
# GOOD - enables monitoring
invoke_agent("builder", task, background=True, project="my-project")

# BAD - no monitoring possible
invoke_agent("builder", task, background=True)
```

### 2. Batch Status Checks

Instead of checking agents one by one, use batch monitoring:

```python
# GOOD - single call for all agents
results = monitor_agents("my-project")

# AVOID - multiple individual checks
for run_id in run_ids:
    wait_for_agent(project, run_id)  # Inefficient
```

### 3. Set Realistic Timeouts

Use historical data to set timeouts:

```python
from lib.monitor import suggest_polling_strategy

# Get recommended strategy
print(suggest_polling_strategy("academic-researcher"))
# Output: Expected 1190s typical, 2202s 95%, timeout 4404s
```

### 4. Handle Stale Agents

Agents are considered stale if no heartbeat for:
- Default: 5 minutes
- Academic-researcher: 73 minutes (due to long tasks)
- Web-researcher: 56 minutes

```python
try:
    progress = wait_for_agent_adaptive(project, run_id)
except StaleAgentError:
    print("Agent appears stuck - investigate or restart")
```

## Progress Hooks for Long Commands

For long-running commands that aren't agents, use progress contexts:

```python
from lib.progress_enhanced import create_progress_context

with create_progress_context("my-project", "data-processor") as progress:
    progress.update_phase("Loading data")
    # ... work ...

    progress.update_phase("Processing records", messages=1000)
    # ... work ...

    progress.add_artifact("output.csv")
    # Context automatically marks complete on exit
```

## Configuration

The polling configuration is stored in `system/agent_polling_config.yaml`:

```yaml
builder:
  initial_poll_interval: 30
  backoff_multiplier: 2.0
  max_poll_interval: 60
  expected_median_sec: 448
  expected_95_percentile_sec: 1346
  stale_threshold_min: 45
```

This is automatically generated from historical data and updated by:
```bash
uv run python tools/analyze_agent_latencies.py
```

## Summary

The enhanced monitoring system provides:

1. **Patient polling** - Adapts to each agent's typical duration
2. **Automatic tracking** - Progress files created/updated automatically
3. **Batch monitoring** - Efficient multi-agent status checks
4. **Historical awareness** - Uses past performance to set expectations
5. **Stale detection** - Identifies stuck agents needing attention

This allows Pilot to delegate more efficiently without wasting tokens on excessive status checks or missing important updates.
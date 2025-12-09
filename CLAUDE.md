# Pilot Core - Agent Infrastructure

This is the core infrastructure for building Claude-based agent systems using the Claude Agent SDK.

## Overview

Pilot Core provides:
- **Agent Invocation**: SDK-based agent execution via `lib/invoke.py`
- **Context Building**: Automatic context assembly for agents
- **Run Management**: Track and link agent executions
- **Repository Search**: DuckDB-indexed search across your codebase
- **Git Workflow**: Pre-commit hooks, approval workflow, worktree management
- **Core Agents**: Builder, Git-Reviewer, Verifier, Web-Researcher, etc.

## Quick Start

### Invoke an Agent

```bash
uv run python -m lib.invoke builder "Create a new feature"
uv run python -m lib.invoke git-reviewer "Review my changes"
```

### Use Repository Search

```bash
# Search before any task
uv run python -m lib.repo_search --context "your task description"

# Quick search
uv run python -m lib.repo_search "keyword"
```

### Run Tools

```bash
uv run python -m tools web_search '{"objective": "query"}'
uv run python -m tools feature_tracker '{"action": "next", "project": "myproject"}'
```

## Available Agents

| Agent | Purpose |
|-------|---------|
| `builder` | Code creation, file editing, implementation |
| `git-reviewer` | Pre-commit review (required before all commits) |
| `verifier` | Read-only testing and verification |
| `initializer` | Bootstrap new projects with feature lists |
| `web-researcher` | External research via Parallel API |
| `academic-researcher` | Deep analysis and synthesis |
| `parallel-results-searcher` | Query stored Parallel.ai results |

## Directory Structure

```
pilot-core/
├── lib/                 # Core Python modules
│   ├── invoke.py        # Agent invocation
│   ├── context.py       # Context builder
│   ├── run.py           # Run management
│   ├── search.py        # Search utilities
│   └── ...
├── tools/               # CLI tools
├── agents/              # Agent definitions (YAML)
├── system/              # Rules, queries, schemas
│   ├── rules/           # Behavioral rules
│   ├── queries/         # SQL templates
│   └── schemas/         # YAML schemas
├── docs/                # Documentation
└── tests/               # Test suite
```

## Core Rules

1. **Delegation**: The orchestrator (Pilot) delegates to specialist agents
2. **Git Review**: All commits require `@git-reviewer` approval
3. **Web Access**: All web access goes through Parallel API tools
4. **Runs Link Everything**: Each unit of work gets a unique run ID

## Extending Pilot Core

To use pilot-core in your own project:

1. Add as dependency: `pip install pilot-core` or git submodule
2. Create your own `CLAUDE.md` that extends this
3. Add custom agents in your local `agents/` directory
4. Add custom tools in your local `tools/` directory

Agent discovery merges core + local directories automatically.

## Documentation

- [Core Configuration](docs/core-config.md) - Agent config, delegation rules
- [Workflows](docs/workflows.md) - Run management, commits, features
- [Tools](docs/tools.md) - Tool documentation, directory structure

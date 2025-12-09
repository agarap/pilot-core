# Code Enforcement Rules

*Generated: 2025-12-03 18:13*

> **Principle**: Prompts inform; code enforces.

## Summary

**Coverage**: 35.7% (5/14 rules enforced)

| Status | Count |
|--------|------:|
| ✅ Enforced | 5 |
| 🔄 Pending | 4 |
| 🟡 Partial | 2 |
| ⚠️ Warning | 1 |
| ❌ Gap | 2 |

## Pre-Commit Rules

These rules are enforced at commit time via pre-commit hook.

| Status | Rule | Description | Mechanism | Bypass |
|:------:|------|-------------|-----------|--------|
| ✅ | git-reviewer-approval | Require @git-reviewer approval before commits | `.git/hooks/pre-commit marker file check` | PILOT_SKIP_REVIEW=1 |
| ✅ | validation-no-logs | Block commits containing logs/, workspaces/, output/ files | `lib/validate.py check_no_logs_or_workspaces()` | none |
| ✅ | validation-yaml-format | Validate system/rules and knowledge/decisions YAML structure | `lib/validate.py check_yaml_format()` | none |
| ✅ | validation-agent-yaml | Validate agents/*.yaml required fields (name, type, description, prompt) | `lib/validate.py check_agent_yaml()` | none |
| ⚠️ | project-structure-runs | Warn on projects without .runs/ directory | `lib/validate.py check_project_structure()` | none |
| 🔄 | web-imports-scan | Block commits with forbidden HTTP library imports | `tools/scan_web_imports.py` | EXEMPTED_FILES list |
| 🔄 | task-tool-detection | Block commits when Task tool usage detected in logs | `tools/detect_task_tool.py` | none |

## Runtime Rules

These rules are enforced at runtime during code execution.

| Status | Rule | Description | Mechanism | Bypass |
|:------:|------|-------------|-----------|--------|
| 🔄 | import-blocker | Block runtime import of forbidden web libraries | `lib/guards.py WebImportBlocker` | ALLOWED_CALLERS list |
| 🔄 | pre-invocation-guard | Check task legitimacy before agent invocation | `lib/invoke.py check_task_legitimacy()` | none |

## Prompt-Only Rules (Gaps)

These rules exist only as CLAUDE.md instructions and need code enforcement.

| Status | Rule | Description | Target Mechanism | Current |
|:------:|------|-------------|------------------|--------|
| ❌ | task-tool-ban | NEVER use Claude Code's built-in Task tool | Session-scoped detection + pre-commit block | CLAUDE.md instruction only |
| ❌ | mandatory-delegation | Pilot orchestrates, delegates to @builder/@web-researcher | Run manifest validation | CLAUDE.md instruction only |
| ✅ | git-review-all | All commits require @git-reviewer | Already enforced via pre-commit | enforced |
| 🟡 | web-access-policy | All web access through Parallel API tools | Runtime import blocker + static scan | CLAUDE.md instruction + scan_web_imports.py (not wired) |
| 🟡 | worktree-isolation | Feature projects must be in dedicated worktrees | Pre-commit validation | feature_tracker enforcement |

## Reference

### Forbidden Libraries

These libraries must not be imported directly (use Parallel API tools instead):

- `requests`
- `httpx`
- `urllib`
- `urllib3`
- `aiohttp`
- `httplib`
- `http.client`
- `bs4`
- `BeautifulSoup`
- `scrapy`
- `selenium`
- `playwright`

### Banned Task Subagent Types

These Claude Code Task tool subagent types are banned:

- `general-purpose`
- `Explore`
- `Plan`
- `code-architect-reviewer`
- `statusline-setup`

### Known Agents

Valid agents for delegation:

- `@builder`
- `@git-reviewer`
- `@web-researcher`
- `@academic-researcher`
- `@verifier`
- `@initializer`
- `@parallel-results-searcher`
- `@company-researcher`
- `@email-agent`

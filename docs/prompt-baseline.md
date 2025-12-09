# Prompt Baseline Report

**Generated**: 2025-12-03
**Purpose**: Track prompt sizes and set reduction targets for optimization

> **Note**: Line/token counts measure the `prompt:` field content in each agent YAML,
> not the total file size. This reflects actual context sent to the model.

## Executive Summary

| Metric | Value |
|--------|-------|
| Total Agents | 9 |
| Total Prompt Lines | 3,994 |
| Total Tokens | ~32,107 |
| Avg Lines/Agent | 444 |
| Largest Agent | academic-researcher (789 lines) |

## Agent Baseline Metrics

| Agent | Lines | Tokens | Sections | Target Lines | Target Tokens | Reduction |
|-------|-------|--------|----------|--------------|---------------|-----------|
| academic-researcher | 789 | 7,539 | 89 | 250 | 2,500 | 68% |
| initializer | 685 | 5,001 | 73 | 250 | 2,000 | 64% |
| web-researcher | 515 | 4,180 | 70 | 200 | 1,600 | 61% |
| git-reviewer | 487 | 4,239 | 69 | 180 | 1,600 | 63% |
| builder | 421 | 3,119 | 44 | 150 | 1,200 | 64% |
| company-researcher | 406 | 2,930 | 70 | 150 | 1,200 | 63% |
| email-agent | 283 | 2,391 | 51 | 120 | 1,000 | 58% |
| parallel-results-searcher | 230 | 1,551 | 39 | 100 | 700 | 57% |
| verifier | 178 | 1,157 | 27 | 100 | 600 | 44% |
| **TOTAL** | **3,994** | **32,107** | **531** | **1,500** | **12,400** | **62%** |

## Reduction Strategy

### High-Impact Agents (Target: 60%+ reduction)

#### 1. academic-researcher (789 -> 250 lines)
- **Current state**: 89 sections, highly verbose
- **Code-enforced rules**: 9 (can reference enforcement.yaml)
- **Prompt-only rules**: 69 (candidates for consolidation)
- **Strategy**:
  - Reference shared enforcement rules instead of inline
  - Consolidate methodology sections
  - Move example code to separate documentation

#### 2. initializer (685 -> 250 lines)
- **Current state**: 73 sections, template-heavy
- **Code-enforced rules**: 24
- **Prompt-only rules**: 24
- **Strategy**:
  - Move templates to separate files
  - Reference shared rules
  - Consolidate workflow steps

#### 3. web-researcher (515 -> 200 lines)
- **Current state**: 70 sections
- **Code-enforced rules**: 10
- **Prompt-only rules**: 77 (highest prompt-only count)
- **Strategy**:
  - Parallel API docs can be referenced externally
  - Consolidate caching instructions

#### 4. git-reviewer (487 -> 180 lines)
- **Current state**: 69 sections
- **Code-enforced rules**: 51 (highest code-enforced!)
- **Prompt-only rules**: 49
- **Strategy**:
  - Review checklists -> separate config file
  - Many rules already enforced - remove redundant text

#### 5. builder (421 -> 150 lines)
- **Current state**: 44 sections, verbose examples
- **Code-enforced rules**: 32
- **Prompt-only rules**: 47
- **Strategy**:
  - Feature workflow can reference feature_tracker docs
  - Tool/agent creation templates -> separate files

### Medium-Impact Agents (Target: 55-60% reduction)

#### 6. company-researcher (406 -> 150 lines)
- **Code-enforced**: 7 | **Prompt-only**: 24
- **Strategy**: Schema examples -> templates

#### 7. email-agent (283 -> 120 lines)
- **Code-enforced**: 7 | **Prompt-only**: 10
- **Strategy**: Already relatively concise, light optimization

### Lower-Impact Agents (Target: 45-55% reduction)

#### 8. parallel-results-searcher (230 -> 100 lines)
- **Code-enforced**: 6 | **Prompt-only**: 39
- **Strategy**: Consolidate search examples

#### 9. verifier (178 -> 100 lines)
- **Code-enforced**: 9 | **Prompt-only**: 16
- **Strategy**: Focused scope, minor consolidation

## Code Enforcement Coverage

Current state of rule enforcement across agents:

| Enforcement Mechanism | Status | Agents Using |
|-----------------------|--------|--------------|
| git-reviewer-approval | enforced | 8/9 agents |
| worktree-isolation | partial | 9/9 agents |
| web-access-policy | partial | 5/9 agents |
| mandatory-delegation | gap | 2/9 agents |
| validation-yaml-format | enforced | 1/9 agents |

**Key Finding**: Rules with code enforcement appear in multiple agent prompts.
Once enforcement is reliable, verbose prompt explanations can be replaced with brief references.

## Code Enforcement Opportunities

The following rules appear across multiple agents and should be enforced via code:

| Rule Category | Agents Affected | Current State | Target Mechanism |
|---------------|-----------------|---------------|------------------|
| Git reviewer required | 8 | enforced | pre-commit hook |
| Web access policy | 5 | partial | import blocker |
| Worktree isolation | 9 | partial | pre-commit check |
| Feature tracker workflow | 3 | prompt-only | CLI enforcement |
| Task tool ban | 3 | prompt-only | static analysis |
| One feature per session | 2 | prompt-only | tracker enforcement |

**Estimated savings from code enforcement**: 100-150 lines per agent

## Token Budget Targets

Based on typical context window constraints:

| Model | Context | Target per Agent | Max Agents Active |
|-------|---------|------------------|-------------------|
| Opus | 200K | 2,500 tokens | 40+ |
| Sonnet | 200K | 1,500 tokens | 60+ |
| Haiku | 200K | 1,000 tokens | 100+ |

**Current average**: 3,567 tokens/agent
**Target average**: 1,378 tokens/agent (61% reduction)

## Success Metrics

After optimization, measure:

1. **Line count** - Target: 1,500 total (from 3,994)
2. **Token count** - Target: 12,400 total (from 32,107)
3. **Code-enforced %** - Target: 80%+ of rules
4. **Agent response time** - Baseline: measure before/after
5. **Rule compliance** - Track violations before/after

## Next Steps

1. [ ] Implement enforcement.yaml code hooks (analyze-003)
2. [ ] Create shared documentation for common patterns
3. [ ] Refactor largest agents first (academic-researcher, initializer)
4. [ ] Measure compliance before/after
5. [ ] Iterate on remaining agents

---

*Generated by: `uv run python -m pilot_tools prompt_analyzer`*
*Re-run analysis: `uv run python -m pilot_tools prompt_analyzer '{"format": "summary"}'`*

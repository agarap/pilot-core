# Schema Migrations

This directory contains migration definitions for evolving pilot-core schemas.

## Migration Format

Each migration is a YAML file with:

```yaml
schema_type: agent        # What type of file this migrates
from_version: 1           # Source version
to_version: 2             # Target version
description: |
  Brief description of what this migration does

guidance: |
  Detailed instructions for the agent performing the migration.

  - What fields to add/remove/rename
  - How to transform values
  - What to preserve

examples:
  - before: |
      # Example v1 content
      name: example
      model: opus
    after: |
      # Example v2 content
      name: example
      model:
        name: opus
      _schema_version: 2
```

## How Migrations Work

1. **Detection**: The evolution system checks `_schema_version` in each file
2. **Path Finding**: It finds the migration path (v1 -> v2 -> v3 if needed)
3. **Agent Execution**: An agent is invoked with the migration guidance
4. **Validation**: The agent writes the migrated file

## Creating a New Migration

When you change a schema in `system/schemas/`:

1. Bump the version in `system/schemas/versions.yaml`
2. Create the new schema file (e.g., `agent.v2.yaml`)
3. Create a migration file here (e.g., `agent_v1_to_v2.yaml`)
4. Provide clear guidance and examples

## Migration Philosophy

Migrations are **agent-first**:
- Guidance is written for an intelligent model to follow
- Examples teach the agent what to do
- The agent handles edge cases intelligently

This is more robust than hardcoded transforms because:
- Handles variations in formatting
- Adapts to unexpected structures
- Can ask for clarification if truly ambiguous

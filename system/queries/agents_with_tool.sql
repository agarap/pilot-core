-- Find all agents/subagents that have access to a specific tool
-- Usage: Replace :tool_name with the tool name (e.g., 'Bash', 'Read')

SELECT
    unnest.name as name,
    unnest.type as type,
    unnest.model as model,
    unnest.tools as tools
FROM read_json_auto('data/index.json'),
UNNEST(items) as unnest
WHERE unnest.type IN ('agent', 'subagent')
AND list_contains(unnest.tools, :tool_name)
ORDER BY unnest.type, unnest.name;

-- Query rules applicable to a specific agent
-- Usage: Replace :agent_name with the agent name
-- Returns rules ordered by priority (highest first)

SELECT
    unnest.name as name,
    unnest.description as description,
    unnest.priority as priority,
    unnest.rule_text as rule,
    unnest.applies_to as applies_to
FROM read_json_auto('data/index.json'),
UNNEST(items) as unnest
WHERE unnest.type = 'rule'
AND (
    list_contains(unnest.applies_to, :agent_name)
    OR list_contains(unnest.applies_to, '*')
)
ORDER BY unnest.priority DESC;

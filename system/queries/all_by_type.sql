-- Query all items of a specific type
-- Usage: Replace :item_type with: subagent, agent, rule, tool, lib, decision, fact, lesson

SELECT
    unnest.name as name,
    unnest.description as description,
    unnest.path as path,
    unnest.tags as tags
FROM read_json_auto('data/index.json'),
UNNEST(items) as unnest
WHERE unnest.type = :item_type
ORDER BY unnest.name;

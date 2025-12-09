-- Get a complete overview of the system
-- Shows counts by type and lists key items

WITH type_counts AS (
    SELECT
        unnest.type as type,
        count(*) as count
    FROM read_json_auto('data/index.json'),
    UNNEST(items) as unnest
    GROUP BY unnest.type
)
SELECT * FROM type_counts ORDER BY count DESC;

-- Subagents
SELECT '--- Subagents ---' as section;
SELECT unnest.name, unnest.model, unnest.description
FROM read_json_auto('data/index.json'),
UNNEST(items) as unnest
WHERE unnest.type = 'subagent';

-- Tools
SELECT '--- Tools ---' as section;
SELECT unnest.name, unnest.description
FROM read_json_auto('data/index.json'),
UNNEST(items) as unnest
WHERE unnest.type = 'tool';

-- Rules (by priority)
SELECT '--- Rules ---' as section;
SELECT unnest.name, unnest.priority, unnest.description
FROM read_json_auto('data/index.json'),
UNNEST(items) as unnest
WHERE unnest.type = 'rule'
ORDER BY unnest.priority DESC;

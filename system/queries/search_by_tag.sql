-- Search items by tag
-- Usage: Replace :tag with the tag to search for

SELECT
    unnest.name as name,
    unnest.type as type,
    unnest.description as description,
    unnest.tags as tags,
    unnest.path as path
FROM read_json_auto('data/index.json'),
UNNEST(items) as unnest
WHERE list_contains(unnest.tags, :tag)
ORDER BY unnest.type, unnest.name;

-- Search code files by pattern
-- Parameters: :pattern (search pattern), :limit (max results)
SELECT
    item.path as path,
    item.name as name,
    item.type as type,
    item.description as description,
    item.content.functions as functions,
    item.content.classes as classes,
    item.content.imports as imports
FROM (
    SELECT unnest(items) as item
    FROM read_json_auto('data/index.json', maximum_object_size=100000000)
) sub
WHERE item.type IN ('code', 'tool', 'lib')
AND (
    lower(COALESCE(item.text, '')) LIKE lower('%' || :pattern || '%')
    OR lower(item.name) LIKE lower('%' || :pattern || '%')
    OR lower(item.description) LIKE lower('%' || :pattern || '%')
)
LIMIT :limit

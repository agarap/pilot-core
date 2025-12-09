-- Exhaustive search across all fields with combined scoring
-- Parameters: :query (search term), :limit (max results)
SELECT
    item.path as path,
    item.name as name,
    item.type as type,
    item.description as description,
    (
        CASE WHEN lower(item.name) LIKE lower('%' || :query || '%') THEN 10 ELSE 0 END +
        CASE WHEN lower(item.description) LIKE lower('%' || :query || '%') THEN 5 ELSE 0 END +
        CASE WHEN lower(COALESCE(item.text, '')) LIKE lower('%' || :query || '%') THEN 3 ELSE 0 END +
        CASE WHEN lower(CAST(item.content AS VARCHAR)) LIKE lower('%' || :query || '%') THEN 2 ELSE 0 END +
        CASE WHEN lower(CAST(item.tags AS VARCHAR)) LIKE lower('%' || :query || '%') THEN 1 ELSE 0 END
    ) as score,
    left(COALESCE(item.text, CAST(item.content AS VARCHAR)), 500) as content
FROM (
    SELECT unnest(items) as item
    FROM read_json_auto('data/index.json', maximum_object_size=100000000)
) sub
WHERE (
    lower(item.name) LIKE lower('%' || :query || '%')
    OR lower(item.description) LIKE lower('%' || :query || '%')
    OR lower(COALESCE(item.text, '')) LIKE lower('%' || :query || '%')
    OR lower(CAST(item.content AS VARCHAR)) LIKE lower('%' || :query || '%')
    OR lower(CAST(item.tags AS VARCHAR)) LIKE lower('%' || :query || '%')
)
ORDER BY score DESC
LIMIT :limit

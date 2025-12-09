-- Regex search across all indexed content
-- Parameters: :pattern (regex pattern), :limit (max results)
SELECT
    item.path as path,
    item.name as name,
    item.type as type,
    item.description as description,
    1.0 as score
FROM (
    SELECT unnest(items) as item
    FROM read_json_auto('data/index.json', maximum_object_size=100000000)
) sub
WHERE regexp_matches(COALESCE(item.text, ''), :pattern)
   OR regexp_matches(CAST(item.content AS VARCHAR), :pattern)
   OR regexp_matches(item.name, :pattern)
LIMIT :limit

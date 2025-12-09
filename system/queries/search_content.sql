-- Search content across all types
-- Usage: Replace :query with search term, :limit with max results
-- Optional: Add type filter by modifying WHERE clause
--
-- Examples:
--   :query = 'parallel', :limit = 20
--   :query = 'auth', :limit = 10

SELECT
    unnest.path,
    unnest.name,
    unnest.type,
    unnest.description,
    unnest.tags
FROM read_json_auto('data/index.json', maximum_object_size=50000000),
UNNEST(items) as unnest
WHERE
    lower(unnest.name) LIKE lower('%' || :query || '%')
    OR lower(unnest.description) LIKE lower('%' || :query || '%')
    OR lower(CAST(unnest.text AS VARCHAR)) LIKE lower('%' || :query || '%')
ORDER BY
    CASE WHEN lower(unnest.name) LIKE lower('%' || :query || '%') THEN 1 ELSE 2 END,
    unnest.name
LIMIT :limit;

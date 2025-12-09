-- Find research findings matching a query
-- Searches across all Parallel API results (parallel_task, parallel_findall)
-- Also includes deep_research type if present
--
-- Usage: Replace :query with search term, :limit with max results
--
-- Examples:
--   :query = 'claude', :limit = 10  -- Find Claude-related research
--   :query = 'api', :limit = 20     -- Find API research

SELECT
    unnest.path,
    unnest.name,
    unnest.type,
    unnest.description,
    unnest.content
FROM read_json_auto('data/index.json', maximum_object_size=50000000),
UNNEST(items) as unnest
WHERE unnest.type IN ('parallel_task', 'parallel_findall', 'deep_research')
  AND (
    lower(unnest.name) LIKE lower('%' || :query || '%')
    OR lower(unnest.description) LIKE lower('%' || :query || '%')
    OR lower(CAST(unnest.text AS VARCHAR)) LIKE lower('%' || :query || '%')
  )
ORDER BY unnest.type, unnest.name
LIMIT :limit;

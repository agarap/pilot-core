-- Find all files with a specific field in their content
-- Useful for discovering what items have certain attributes
--
-- Usage: Replace :field with JSON field name to search for
--
-- Examples:
--   :field = 'model'      -- Find all items with a model field
--   :field = 'processor'  -- Find items with processor config
--   :field = 'priority'   -- Find items with priority settings
--   :field = 'tools'      -- Find items that specify tools
--
-- Note: Returns items where the field exists and is not null

SELECT
    unnest.path,
    unnest.name,
    unnest.type,
    unnest.content->>:field as field_value
FROM read_json_auto('data/index.json', maximum_object_size=50000000),
UNNEST(items) as unnest
WHERE unnest.content->>:field IS NOT NULL
ORDER BY unnest.type, unnest.name;

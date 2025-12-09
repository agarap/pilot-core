-- Search for specific JSON field value in content
-- Usage: Replace :field with JSON field name, :value with target value
--
-- Examples:
--   :field = 'model', :value = 'opus'  -- Find agents using opus model
--   :field = 'priority', :value = '90' -- Find high-priority rules
--   :field = 'type', :value = 'subagent'
--
-- Note: JSON field access uses ->> for string extraction

SELECT
    unnest.path,
    unnest.name,
    unnest.type,
    unnest.content->>:field as field_value
FROM read_json_auto('data/index.json', maximum_object_size=50000000),
UNNEST(items) as unnest
WHERE unnest.content->>:field = :value
ORDER BY unnest.type, unnest.name;

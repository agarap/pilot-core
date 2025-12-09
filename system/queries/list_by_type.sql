-- List all items of a given type
-- Usage: Replace :type with target type
--
-- Available types: agent, config, decision, fact, file, lesson, lib,
--                  parallel_findall, parallel_task, project, rule, tool
--
-- Examples:
--   :type = 'agent'    -- List all agents
--   :type = 'rule'     -- List all rules
--   :type = 'tool'     -- List all tools
--   :type = 'project'  -- List all projects
--   :type = 'lesson'   -- List all lessons learned

SELECT
    unnest.path,
    unnest.name,
    unnest.description,
    unnest.tags
FROM read_json_auto('data/index.json', maximum_object_size=50000000),
UNNEST(items) as unnest
WHERE unnest.type = :type
ORDER BY unnest.name;

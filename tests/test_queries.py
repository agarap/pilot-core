"""Tests for lib/queries.py and lib/query_builder.py."""

import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from pilot_core.queries import (
    load_query,
    execute_query,
    execute_sql,
    _convert_params_to_duckdb,
    _fix_json_read_size,
    list_templates,
    clear_cache,
    get_template_info,
    QueryError,
    TemplateNotFoundError,
    _template_cache,
    QUERIES_DIR,
)

from pilot_core.query_builder import QueryBuilder, query


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def tmp_queries_dir(tmp_path):
    """Create a temporary queries directory with sample templates."""
    queries_dir = tmp_path / "system" / "queries"
    queries_dir.mkdir(parents=True)
    return queries_dir


@pytest.fixture
def sample_template(tmp_queries_dir):
    """Create a sample SQL template."""
    template_content = """-- Sample query for testing
-- Usage: :name = 'test', :limit = 10

SELECT unnest.name, unnest.type
FROM read_json_auto('data/index.json'),
UNNEST(items) as unnest
WHERE unnest.name = :name
LIMIT :limit;
"""
    template_file = tmp_queries_dir / "sample_query.sql"
    template_file.write_text(template_content)
    return template_file


@pytest.fixture
def tmp_index_file(tmp_path):
    """Create a temporary index.json file for testing."""
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True)

    index_data = {
        "items": [
            {
                "path": "agents/builder.yaml",
                "name": "builder",
                "type": "agent",
                "description": "Builds code and tools",
                "content": {"model": "opus", "tools": ["Read", "Write"]},
                "text": "Builder agent for creating code",
            },
            {
                "path": "agents/web-researcher.yaml",
                "name": "web-researcher",
                "type": "agent",
                "description": "Researches web content",
                "content": {"model": "sonnet"},
                "text": "Web researcher for external lookups",
            },
            {
                "path": "tools/web_search.py",
                "name": "web_search",
                "type": "tool",
                "description": "Search the web",
                "content": "def main(): pass",
                "text": "Tool for web searching",
            },
            {
                "path": "system/rules/git-review.yaml",
                "name": "git-review-required",
                "type": "rule",
                "description": "All commits require review",
                "content": {"priority": 90},
                "text": "Git review rule for commits",
            },
        ]
    }

    index_file = data_dir / "index.json"
    index_file.write_text(json.dumps(index_data))
    return index_file


@pytest.fixture(autouse=True)
def clear_template_cache():
    """Clear template cache before and after each test."""
    clear_cache()
    yield
    clear_cache()


# =============================================================================
# Tests for lib/queries.py
# =============================================================================


class TestLoadQuery:
    """Tests for load_query() function."""

    def test_load_existing_template(self, tmp_queries_dir, sample_template, monkeypatch):
        """Loading an existing template should return its content."""
        monkeypatch.setattr("lib.queries.QUERIES_DIR", tmp_queries_dir)

        sql = load_query("sample_query")

        assert "SELECT unnest.name" in sql
        assert ":name" in sql
        assert ":limit" in sql

    def test_load_nonexistent_template_raises_error(self, tmp_queries_dir, monkeypatch):
        """Loading a nonexistent template should raise TemplateNotFoundError."""
        monkeypatch.setattr("lib.queries.QUERIES_DIR", tmp_queries_dir)

        with pytest.raises(TemplateNotFoundError) as exc_info:
            load_query("nonexistent_template")

        assert "nonexistent_template" in str(exc_info.value)
        assert "not found" in str(exc_info.value).lower()

    def test_template_caching(self, tmp_queries_dir, sample_template, monkeypatch):
        """Template should be cached after first load."""
        monkeypatch.setattr("lib.queries.QUERIES_DIR", tmp_queries_dir)

        # First load
        sql1 = load_query("sample_query")
        assert "sample_query" in _template_cache

        # Modify the file
        sample_template.write_text("-- Modified content")

        # Second load should return cached version
        sql2 = load_query("sample_query")
        assert sql1 == sql2
        assert "Modified" not in sql2

    def test_bypass_cache(self, tmp_queries_dir, sample_template, monkeypatch):
        """use_cache=False should bypass the cache."""
        monkeypatch.setattr("lib.queries.QUERIES_DIR", tmp_queries_dir)

        # First load
        sql1 = load_query("sample_query")

        # Modify the file
        sample_template.write_text("-- Modified content\nSELECT 1;")

        # Load with cache bypass
        sql2 = load_query("sample_query", use_cache=False)
        assert "Modified" in sql2
        assert sql1 != sql2

    def test_error_message_lists_available_templates(self, tmp_queries_dir, monkeypatch):
        """Error message should list available templates when not found."""
        monkeypatch.setattr("lib.queries.QUERIES_DIR", tmp_queries_dir)

        # Create some templates
        (tmp_queries_dir / "template_a.sql").write_text("SELECT 1;")
        (tmp_queries_dir / "template_b.sql").write_text("SELECT 2;")

        with pytest.raises(TemplateNotFoundError) as exc_info:
            load_query("missing")

        error_msg = str(exc_info.value)
        assert "template_a" in error_msg
        assert "template_b" in error_msg


class TestExecuteQuery:
    """Tests for execute_query() function."""

    def test_execute_simple_query(self, tmp_queries_dir, tmp_index_file, monkeypatch):
        """Execute a simple query with parameters."""
        monkeypatch.setattr("lib.queries.QUERIES_DIR", tmp_queries_dir)

        # Create a simple template that works with our test data
        template = f"""SELECT unnest.name, unnest.type
FROM read_json_auto('{tmp_index_file}'),
UNNEST(items) as unnest
WHERE unnest.type = :item_type
LIMIT :limit;
"""
        (tmp_queries_dir / "by_type.sql").write_text(template)

        results = execute_query("by_type", {"item_type": "agent", "limit": 10})

        assert len(results) == 2
        assert all(r["type"] == "agent" for r in results)

    def test_execute_query_template_not_found(self, tmp_queries_dir, monkeypatch):
        """Execute with missing template should raise TemplateNotFoundError."""
        monkeypatch.setattr("lib.queries.QUERIES_DIR", tmp_queries_dir)

        with pytest.raises(TemplateNotFoundError):
            execute_query("missing_template", {})


class TestExecuteSql:
    """Tests for execute_sql() function."""

    def test_execute_direct_sql(self, tmp_index_file):
        """Execute SQL directly without template."""
        sql = f"""
        SELECT unnest.name, unnest.type
        FROM read_json_auto('{tmp_index_file}'),
        UNNEST(items) as unnest
        WHERE unnest.type = :type_filter
        """

        results = execute_sql(sql, {"type_filter": "tool"})

        assert len(results) == 1
        assert results[0]["name"] == "web_search"
        assert results[0]["type"] == "tool"

    def test_execute_without_params(self, tmp_index_file):
        """Execute SQL without parameters."""
        sql = f"""
        SELECT COUNT(*) as count
        FROM read_json_auto('{tmp_index_file}'),
        UNNEST(items) as unnest
        """

        results = execute_sql(sql)

        assert len(results) == 1
        assert results[0]["count"] == 4

    def test_execute_invalid_sql_raises_error(self):
        """Invalid SQL should raise QueryError."""
        with pytest.raises(QueryError) as exc_info:
            execute_sql("SELECT * FROM nonexistent_table")

        assert "execution failed" in str(exc_info.value).lower()

    def test_execute_with_syntax_error(self):
        """SQL syntax error should raise QueryError."""
        with pytest.raises(QueryError):
            execute_sql("SELECTT * FORM table")

    def test_results_as_dicts(self, tmp_index_file):
        """Results should be returned as list of dictionaries."""
        sql = f"""
        SELECT unnest.name, unnest.type, unnest.description
        FROM read_json_auto('{tmp_index_file}'),
        UNNEST(items) as unnest
        LIMIT 1
        """

        results = execute_sql(sql)

        assert isinstance(results, list)
        assert len(results) == 1
        assert isinstance(results[0], dict)
        assert "name" in results[0]
        assert "type" in results[0]
        assert "description" in results[0]


class TestConvertParamsToDuckdb:
    """Tests for _convert_params_to_duckdb() function."""

    def test_convert_single_param(self):
        """Single :param should convert to $param."""
        sql = "SELECT * FROM table WHERE name = :name"
        converted_sql, params = _convert_params_to_duckdb(sql, {"name": "test"})

        assert converted_sql == "SELECT * FROM table WHERE name = $name"
        assert params == {"name": "test"}

    def test_convert_multiple_params(self):
        """Multiple :params should all convert."""
        sql = "SELECT * FROM t WHERE a = :first AND b = :second"
        converted_sql, params = _convert_params_to_duckdb(
            sql, {"first": 1, "second": 2}
        )

        assert "$first" in converted_sql
        assert "$second" in converted_sql
        assert ":first" not in converted_sql
        assert ":second" not in converted_sql

    def test_preserve_cast_operator(self):
        """Double colon (::) for casting should not be converted."""
        sql = "SELECT value::INTEGER FROM table WHERE name = :name"
        converted_sql, _ = _convert_params_to_duckdb(sql, {"name": "test"})

        assert "::INTEGER" in converted_sql
        assert "$name" in converted_sql

    def test_underscore_in_param_name(self):
        """Parameter names with underscores should convert correctly."""
        sql = "SELECT * FROM t WHERE col = :my_param_name"
        converted_sql, _ = _convert_params_to_duckdb(sql, {"my_param_name": "value"})

        assert "$my_param_name" in converted_sql

    def test_numeric_suffix_in_param(self):
        """Parameter names with numbers should convert correctly."""
        sql = "SELECT * FROM t WHERE a = :param1 AND b = :param2"
        converted_sql, _ = _convert_params_to_duckdb(sql, {"param1": 1, "param2": 2})

        assert "$param1" in converted_sql
        assert "$param2" in converted_sql

    def test_params_dict_unchanged(self):
        """Original params dict should pass through unchanged."""
        original_params = {"key1": "value1", "key2": 42}
        _, returned_params = _convert_params_to_duckdb("SELECT :key1, :key2", original_params)

        assert returned_params == original_params


class TestFixJsonReadSize:
    """Tests for _fix_json_read_size() function."""

    def test_add_size_to_simple_read_json(self):
        """Add maximum_object_size to read_json_auto without options."""
        sql = "SELECT * FROM read_json_auto('data/index.json')"
        fixed = _fix_json_read_size(sql)

        assert "maximum_object_size=50000000" in fixed

    def test_preserve_existing_size_option(self):
        """Don't modify if maximum_object_size already present."""
        sql = "SELECT * FROM read_json_auto('data/index.json', maximum_object_size=100)"
        fixed = _fix_json_read_size(sql)

        assert fixed == sql
        assert "maximum_object_size=100" in fixed
        assert fixed.count("maximum_object_size") == 1

    def test_multiple_read_json_calls(self):
        """Handle multiple read_json_auto calls."""
        sql = """
        SELECT * FROM read_json_auto('a.json')
        UNION ALL
        SELECT * FROM read_json_auto('b.json')
        """
        fixed = _fix_json_read_size(sql)

        assert fixed.count("maximum_object_size=50000000") == 2

    def test_no_modification_needed(self):
        """SQL without read_json_auto should pass through unchanged."""
        sql = "SELECT * FROM my_table WHERE id = 1"
        fixed = _fix_json_read_size(sql)

        assert fixed == sql


class TestListTemplates:
    """Tests for list_templates() function."""

    def test_list_templates_returns_names(self, tmp_queries_dir, monkeypatch):
        """list_templates should return template names without .sql extension."""
        monkeypatch.setattr("lib.queries.QUERIES_DIR", tmp_queries_dir)

        (tmp_queries_dir / "query_a.sql").write_text("SELECT 1;")
        (tmp_queries_dir / "query_b.sql").write_text("SELECT 2;")
        (tmp_queries_dir / "query_c.sql").write_text("SELECT 3;")

        templates = list_templates()

        assert "query_a" in templates
        assert "query_b" in templates
        assert "query_c" in templates
        assert len(templates) == 3

    def test_list_templates_sorted(self, tmp_queries_dir, monkeypatch):
        """Templates should be returned in sorted order."""
        monkeypatch.setattr("lib.queries.QUERIES_DIR", tmp_queries_dir)

        (tmp_queries_dir / "zebra.sql").write_text("SELECT 1;")
        (tmp_queries_dir / "alpha.sql").write_text("SELECT 2;")
        (tmp_queries_dir / "middle.sql").write_text("SELECT 3;")

        templates = list_templates()

        assert templates == ["alpha", "middle", "zebra"]

    def test_list_templates_empty_dir(self, tmp_queries_dir, monkeypatch):
        """Empty directory should return empty list."""
        monkeypatch.setattr("lib.queries.QUERIES_DIR", tmp_queries_dir)

        templates = list_templates()

        assert templates == []

    def test_list_templates_nonexistent_dir(self, tmp_path, monkeypatch):
        """Nonexistent directory should return empty list."""
        monkeypatch.setattr("lib.queries.QUERIES_DIR", tmp_path / "nonexistent")

        templates = list_templates()

        assert templates == []

    def test_ignore_non_sql_files(self, tmp_queries_dir, monkeypatch):
        """Non-.sql files should be ignored."""
        monkeypatch.setattr("lib.queries.QUERIES_DIR", tmp_queries_dir)

        (tmp_queries_dir / "query.sql").write_text("SELECT 1;")
        (tmp_queries_dir / "readme.md").write_text("# Readme")
        (tmp_queries_dir / "notes.txt").write_text("Notes")

        templates = list_templates()

        assert templates == ["query"]


class TestClearCache:
    """Tests for clear_cache() function."""

    def test_clear_cache_empties_cache(self, tmp_queries_dir, sample_template, monkeypatch):
        """clear_cache should empty the template cache."""
        monkeypatch.setattr("lib.queries.QUERIES_DIR", tmp_queries_dir)

        # Load a template to populate cache
        load_query("sample_query")
        assert "sample_query" in _template_cache

        # Clear cache
        clear_cache()

        assert "sample_query" not in _template_cache
        assert len(_template_cache) == 0

    def test_clear_cache_allows_reload(self, tmp_queries_dir, sample_template, monkeypatch):
        """After clearing cache, templates should be reloaded from disk."""
        monkeypatch.setattr("lib.queries.QUERIES_DIR", tmp_queries_dir)

        # First load
        sql1 = load_query("sample_query")

        # Modify file
        sample_template.write_text("-- New content\nSELECT 42;")

        # Clear cache and reload
        clear_cache()
        sql2 = load_query("sample_query")

        assert "New content" in sql2
        assert sql1 != sql2


class TestGetTemplateInfo:
    """Tests for get_template_info() function."""

    def test_get_info_with_description(self, tmp_queries_dir, monkeypatch):
        """get_template_info should extract description from first comment."""
        monkeypatch.setattr("lib.queries.QUERIES_DIR", tmp_queries_dir)

        template = """-- This is the description line
-- Second line of comments
SELECT * FROM table WHERE id = :id;
"""
        (tmp_queries_dir / "test_query.sql").write_text(template)

        info = get_template_info("test_query")

        assert info["name"] == "test_query"
        assert info["description"] == "This is the description line"
        assert "id" in info["parameters"]

    def test_get_info_extracts_parameters(self, tmp_queries_dir, monkeypatch):
        """get_template_info should extract all :param_name parameters."""
        monkeypatch.setattr("lib.queries.QUERIES_DIR", tmp_queries_dir)

        template = """SELECT * FROM t
WHERE name = :name
AND type = :type_filter
AND id > :min_id
LIMIT :limit;
"""
        (tmp_queries_dir / "multi_param.sql").write_text(template)

        info = get_template_info("multi_param")

        assert set(info["parameters"]) == {"name", "type_filter", "min_id", "limit"}

    def test_get_info_includes_path(self, tmp_queries_dir, monkeypatch):
        """get_template_info should include the template path."""
        monkeypatch.setattr("lib.queries.QUERIES_DIR", tmp_queries_dir)

        (tmp_queries_dir / "path_test.sql").write_text("SELECT 1;")

        info = get_template_info("path_test")

        assert "path_test.sql" in info["path"]

    def test_get_info_includes_sql(self, tmp_queries_dir, monkeypatch):
        """get_template_info should include the raw SQL."""
        monkeypatch.setattr("lib.queries.QUERIES_DIR", tmp_queries_dir)

        template = "SELECT * FROM table;"
        (tmp_queries_dir / "raw.sql").write_text(template)

        info = get_template_info("raw")

        assert info["sql"] == template

    def test_get_info_empty_description(self, tmp_queries_dir, monkeypatch):
        """Template without comments should have empty description."""
        monkeypatch.setattr("lib.queries.QUERIES_DIR", tmp_queries_dir)

        (tmp_queries_dir / "no_comment.sql").write_text("SELECT 1;")

        info = get_template_info("no_comment")

        assert info["description"] == ""

    def test_get_info_no_parameters(self, tmp_queries_dir, monkeypatch):
        """Template without parameters should have empty parameters list."""
        monkeypatch.setattr("lib.queries.QUERIES_DIR", tmp_queries_dir)

        (tmp_queries_dir / "static.sql").write_text("SELECT COUNT(*) FROM table;")

        info = get_template_info("static")

        assert info["parameters"] == []


class TestExceptionHierarchy:
    """Tests for exception classes."""

    def test_template_not_found_is_query_error(self):
        """TemplateNotFoundError should be a subclass of QueryError."""
        assert issubclass(TemplateNotFoundError, QueryError)

    def test_can_catch_all_with_query_error(self, tmp_queries_dir, monkeypatch):
        """Both error types should be catchable with QueryError."""
        monkeypatch.setattr("lib.queries.QUERIES_DIR", tmp_queries_dir)

        # TemplateNotFoundError
        with pytest.raises(QueryError):
            load_query("nonexistent")

        # QueryError from bad SQL
        with pytest.raises(QueryError):
            execute_sql("INVALID SQL SYNTAX HERE")


# =============================================================================
# Tests for lib/query_builder.py
# =============================================================================


class TestQueryBuilderType:
    """Tests for QueryBuilder.type() method."""

    def test_type_filter_in_sql(self):
        """Type filter should appear in generated SQL."""
        sql, params = QueryBuilder().type("agent").to_sql()

        assert "unnest.type = :type_filter" in sql
        assert params["type_filter"] == "agent"

    def test_type_filter_different_types(self):
        """Different type values should be parameterized."""
        for type_name in ["agent", "tool", "rule", "decision", "lesson"]:
            sql, params = QueryBuilder().type(type_name).to_sql()
            assert params["type_filter"] == type_name


class TestQueryBuilderWhere:
    """Tests for QueryBuilder.where() method."""

    def test_where_exact_match(self):
        """where() should generate exact match condition."""
        sql, params = QueryBuilder().where("name", "builder").to_sql()

        assert "unnest.name = :p1" in sql
        assert params["p1"] == "builder"

    def test_where_multiple_conditions(self):
        """Multiple where() calls should create AND conditions."""
        sql, params = (
            QueryBuilder()
            .where("name", "test")
            .where("type", "agent")
            .to_sql()
        )

        assert "unnest.name = :p1" in sql
        assert "unnest.type = :p2" in sql
        assert "AND" in sql

    def test_where_standard_fields(self):
        """Standard fields should use unnest. prefix."""
        for field in ["name", "path", "type", "description"]:
            sql, _ = QueryBuilder().where(field, "value").to_sql()
            assert f"unnest.{field} = :p1" in sql


class TestQueryBuilderWhereLike:
    """Tests for QueryBuilder.where_like() method."""

    def test_where_like_pattern(self):
        """where_like() should generate LIKE condition."""
        sql, params = QueryBuilder().where_like("name", "web%").to_sql()

        assert "unnest.name LIKE :p1" in sql
        assert params["p1"] == "web%"

    def test_where_like_with_wildcards(self):
        """Wildcards should be preserved in pattern."""
        sql, params = QueryBuilder().where_like("description", "%search%").to_sql()

        assert params["p1"] == "%search%"


class TestQueryBuilderSearch:
    """Tests for QueryBuilder.search() method."""

    def test_search_generates_multi_field_condition(self):
        """search() should search across name, description, and text."""
        sql, params = QueryBuilder().search("test").to_sql()

        assert "lower(unnest.name) LIKE lower(:search_term)" in sql
        assert "lower(COALESCE(unnest.description, ''))" in sql
        assert params["search_term"] == "%test%"

    def test_search_adds_wildcards(self):
        """Search term should be wrapped in wildcards."""
        _, params = QueryBuilder().search("query").to_sql()

        assert params["search_term"] == "%query%"

    def test_search_ordering(self):
        """Search should prioritize name matches in ordering."""
        sql, _ = QueryBuilder().search("web").to_sql()

        assert "ORDER BY" in sql
        assert "CASE WHEN" in sql


class TestQueryBuilderContentContains:
    """Tests for QueryBuilder.content_contains() method."""

    def test_content_contains_searches_content_field(self):
        """content_contains() should search in content field."""
        sql, params = QueryBuilder().content_contains("parallel").to_sql()

        assert "unnest.content" in sql
        assert "LIKE" in sql
        assert params["content_search"] == "%parallel%"


class TestQueryBuilderOrderBy:
    """Tests for QueryBuilder.order_by() method."""

    def test_order_by_ascending(self):
        """Default ordering should be ascending."""
        sql, _ = QueryBuilder().order_by("name").to_sql()

        assert "ORDER BY unnest.name ASC" in sql

    def test_order_by_descending(self):
        """desc=True should order descending."""
        sql, _ = QueryBuilder().order_by("name", desc=True).to_sql()

        assert "ORDER BY unnest.name DESC" in sql

    def test_order_by_different_fields(self):
        """Should support ordering by different fields."""
        for field in ["name", "type", "path"]:
            sql, _ = QueryBuilder().order_by(field).to_sql()
            assert f"ORDER BY unnest.{field}" in sql


class TestQueryBuilderLimit:
    """Tests for QueryBuilder.limit() method."""

    def test_limit_in_sql(self):
        """limit() should add LIMIT clause."""
        sql, _ = QueryBuilder().limit(10).to_sql()

        assert "LIMIT 10" in sql

    def test_limit_zero(self):
        """Limit of 0 should still appear in SQL."""
        sql, _ = QueryBuilder().limit(0).to_sql()

        assert "LIMIT 0" in sql


class TestQueryBuilderOffset:
    """Tests for QueryBuilder.offset() method."""

    def test_offset_in_sql(self):
        """offset() should add OFFSET clause."""
        sql, _ = QueryBuilder().offset(5).to_sql()

        assert "OFFSET 5" in sql

    def test_offset_zero(self):
        """Offset of 0 should still appear in SQL."""
        sql, _ = QueryBuilder().offset(0).to_sql()

        assert "OFFSET 0" in sql


class TestQueryBuilderToSql:
    """Tests for QueryBuilder.to_sql() method."""

    def test_to_sql_returns_tuple(self):
        """to_sql() should return (sql, params) tuple."""
        result = QueryBuilder().to_sql()

        assert isinstance(result, tuple)
        assert len(result) == 2
        assert isinstance(result[0], str)
        assert isinstance(result[1], dict)

    def test_to_sql_base_query_structure(self):
        """Base query should have correct structure."""
        sql, _ = QueryBuilder().to_sql()

        assert "SELECT" in sql
        assert "unnest.path" in sql
        assert "unnest.name" in sql
        assert "unnest.type" in sql
        assert "unnest.description" in sql
        assert "unnest.content" in sql
        assert "FROM read_json_auto" in sql
        assert "UNNEST(items)" in sql

    def test_to_sql_includes_object_size(self):
        """Generated SQL should include maximum_object_size."""
        sql, _ = QueryBuilder().to_sql()

        assert "maximum_object_size" in sql

    def test_default_ordering_by_name(self):
        """Without order_by or search, should order by name."""
        sql, _ = QueryBuilder().type("agent").to_sql()

        assert "ORDER BY unnest.name" in sql


class TestQueryBuilderChaining:
    """Tests for method chaining."""

    def test_all_methods_return_self(self):
        """All builder methods should return self for chaining."""
        builder = QueryBuilder()

        assert builder.type("agent") is builder
        assert builder.where("name", "test") is builder
        assert builder.where_like("desc", "%x%") is builder
        assert builder.search("query") is builder
        assert builder.content_contains("text") is builder
        assert builder.order_by("name") is builder
        assert builder.limit(10) is builder
        assert builder.offset(5) is builder

    def test_complex_chain(self):
        """Complex chains should work correctly."""
        sql, params = (
            QueryBuilder()
            .type("tool")
            .where("name", "web_search")
            .search("parallel")
            .order_by("name", desc=True)
            .limit(5)
            .offset(2)
            .to_sql()
        )

        assert "unnest.type = :type_filter" in sql
        assert params["type_filter"] == "tool"
        assert "unnest.name = :p1" in sql
        assert params["p1"] == "web_search"
        assert "search_term" in params
        assert "ORDER BY unnest.name DESC" in sql
        assert "LIMIT 5" in sql
        assert "OFFSET 2" in sql

    def test_combined_where_conditions(self):
        """Multiple conditions should be AND-ed together."""
        sql, _ = (
            QueryBuilder()
            .type("agent")
            .where("name", "builder")
            .content_contains("opus")
            .to_sql()
        )

        # Count AND occurrences (should have at least 2 for 3 conditions)
        assert sql.count(" AND ") >= 2


class TestQueryBuilderExecute:
    """Tests for QueryBuilder.execute() method."""

    def test_execute_returns_list(self, tmp_index_file, monkeypatch):
        """execute() should return list of dicts."""
        # Patch the index path used by query builder
        monkeypatch.chdir(tmp_index_file.parent.parent)

        results = QueryBuilder().type("agent").execute()

        assert isinstance(results, list)
        assert len(results) == 2
        assert all(isinstance(r, dict) for r in results)

    def test_execute_with_filters(self, tmp_index_file, monkeypatch):
        """execute() should respect filters."""
        monkeypatch.chdir(tmp_index_file.parent.parent)

        results = QueryBuilder().type("tool").execute()

        assert len(results) == 1
        assert results[0]["name"] == "web_search"

    def test_execute_with_limit(self, tmp_index_file, monkeypatch):
        """execute() should respect limit."""
        monkeypatch.chdir(tmp_index_file.parent.parent)

        results = QueryBuilder().limit(1).execute()

        assert len(results) == 1


class TestQueryConvenienceFunction:
    """Tests for query() convenience function."""

    def test_query_returns_builder(self):
        """query() should return a QueryBuilder instance."""
        result = query()

        assert isinstance(result, QueryBuilder)

    def test_query_is_chainable(self):
        """query() result should be chainable."""
        sql, params = query().type("agent").limit(5).to_sql()

        assert "type_filter" in params
        assert "LIMIT 5" in sql

    def test_multiple_query_calls_independent(self):
        """Each query() call should return independent builder."""
        builder1 = query().type("agent")
        builder2 = query().type("tool")

        _, params1 = builder1.to_sql()
        _, params2 = builder2.to_sql()

        assert params1["type_filter"] == "agent"
        assert params2["type_filter"] == "tool"


class TestQueryBuilderParamGeneration:
    """Tests for parameter name generation."""

    def test_unique_param_names(self):
        """Each where/where_like should get unique param name."""
        sql, params = (
            QueryBuilder()
            .where("name", "a")
            .where("type", "b")
            .where_like("description", "%c%")
            .to_sql()
        )

        # Should have p1, p2, p3
        assert "p1" in params
        assert "p2" in params
        assert "p3" in params
        assert params["p1"] == "a"
        assert params["p2"] == "b"
        assert params["p3"] == "%c%"

    def test_param_names_dont_conflict_with_builtins(self):
        """Generated params shouldn't conflict with type_filter, search_term."""
        _, params = (
            QueryBuilder()
            .type("agent")
            .where("name", "test")
            .search("query")
            .to_sql()
        )

        # Built-in params
        assert "type_filter" in params
        assert "search_term" in params
        # Generated param
        assert "p1" in params


# =============================================================================
# Integration Tests
# =============================================================================


class TestIntegration:
    """Integration tests combining queries.py and query_builder.py."""

    def test_builder_uses_execute_sql(self, tmp_index_file, monkeypatch):
        """QueryBuilder.execute() should use execute_sql internally."""
        monkeypatch.chdir(tmp_index_file.parent.parent)

        # Patch at lib.queries since that's where execute_sql is imported from
        with patch("lib.queries.execute_sql") as mock_execute:
            mock_execute.return_value = [{"name": "test"}]

            results = QueryBuilder().type("agent").execute()

            mock_execute.assert_called_once()
            assert results == [{"name": "test"}]

    def test_end_to_end_query(self, tmp_index_file, monkeypatch):
        """Full end-to-end query should work."""
        monkeypatch.chdir(tmp_index_file.parent.parent)

        results = (
            QueryBuilder()
            .type("agent")
            .order_by("name")
            .execute()
        )

        assert len(results) == 2
        # Should be ordered by name
        assert results[0]["name"] == "builder"
        assert results[1]["name"] == "web-researcher"

    def test_search_finds_matches(self, tmp_index_file, monkeypatch):
        """Search should find items matching the term."""
        monkeypatch.chdir(tmp_index_file.parent.parent)

        results = QueryBuilder().search("web").execute()

        names = [r["name"] for r in results]
        assert "web-researcher" in names
        assert "web_search" in names

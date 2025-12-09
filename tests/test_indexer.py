"""
Unit tests for incremental indexing features (idx-001 to idx-006).

Tests:
- Single item indexing with incremental_index()
- Index item creation for deep_research
- Atomic index updates
- Index rebuild functionality
- Index status reporting
"""

import json
import pytest
import tempfile
from pathlib import Path
from datetime import datetime
from unittest.mock import patch, MagicMock

import yaml

# Import the functions we're testing
from lib.indexer import (
    incremental_index,
    create_deep_research_index_item,
    update_index,
    rebuild_deep_research_index,
    get_index_status,
    INDEX_PATH,
    DEEP_RESEARCH_RESULTS_DIR,
)


class TestIncrementalIndex:
    """Tests for incremental_index function (idx-001)."""

    def test_incremental_index_returns_dict(self, tmp_path, monkeypatch):
        """incremental_index should return a dict with success status."""
        # Create a test YAML file in a recognized location
        agents_dir = tmp_path / "agents"
        agents_dir.mkdir()
        test_file = agents_dir / "test.yaml"
        test_file.write_text(yaml.dump({'name': 'test', 'description': 'A test agent'}))

        # Set up index path
        index_path = tmp_path / "data" / "index.json"
        monkeypatch.setattr('lib.indexer.INDEX_PATH', index_path)

        # Change to tmp_path so relative paths work
        monkeypatch.chdir(tmp_path)

        result = incremental_index(str(test_file))

        assert isinstance(result, dict)
        assert 'success' in result

    def test_incremental_index_with_nonexistent_path(self):
        """incremental_index should handle non-existent paths."""
        result = incremental_index('/nonexistent/path/file.yaml')

        assert result['success'] is False
        assert 'error' in result

    def test_incremental_index_with_deep_research_metadata(self, tmp_path, monkeypatch):
        """incremental_index should process deep_research metadata.yaml files."""
        # Create mock result directory structure
        results_dir = tmp_path / "data" / "deep_research" / "results"
        result_dir = results_dir / "trun_test_idx"
        result_dir.mkdir(parents=True)

        metadata = {
            'run_id': 'trun_test_idx',
            'query': 'Test indexing query',
            'processor': 'ultra',
            'status': 'completed',
        }
        (result_dir / 'metadata.yaml').write_text(yaml.dump(metadata))

        output = {'basis': [{'field': 'Test'}]}
        (result_dir / 'output.yaml').write_text(yaml.dump(output))

        # Monkeypatch the results dir and index path
        monkeypatch.setattr('lib.indexer.DEEP_RESEARCH_RESULTS_DIR', results_dir)
        index_path = tmp_path / "data" / "index.json"
        monkeypatch.setattr('lib.indexer.INDEX_PATH', index_path)

        # Change to tmp_path so derive_type works correctly
        monkeypatch.chdir(tmp_path)

        result = incremental_index(str(result_dir / 'metadata.yaml'))

        assert result['success'] is True
        assert result['type'] == 'deep_research'

    def test_incremental_index_updates_index_file(self, tmp_path, monkeypatch):
        """incremental_index should update index.json."""
        # Create a test YAML file
        agents_dir = tmp_path / "agents"
        agents_dir.mkdir()
        test_file = agents_dir / "test-agent.yaml"
        test_file.write_text(yaml.dump({
            'name': 'test-agent',
            'description': 'A test agent for indexing',
            'type': 'subagent',
        }))

        # Set up index path
        index_path = tmp_path / "data" / "index.json"
        monkeypatch.setattr('lib.indexer.INDEX_PATH', index_path)
        monkeypatch.chdir(tmp_path)

        result = incremental_index(str(test_file))

        assert result['success'] is True
        assert index_path.exists()

        # Verify index content
        index_data = json.loads(index_path.read_text())
        assert index_data['count'] == 1
        assert len(index_data['items']) == 1


class TestCreateDeepResearchIndexItem:
    """Tests for create_deep_research_index_item function (idx-002)."""

    def test_creates_index_item_with_required_fields(self, tmp_path):
        """Index item should have all required fields."""
        result_dir = tmp_path / "trun_item_test"
        result_dir.mkdir()

        metadata = {
            'run_id': 'trun_item_test',
            'query': 'What is machine learning?',
            'processor': 'ultra2x',
            'status': 'completed',
            'completed_at': '2025-12-01T12:00:00',
        }
        (result_dir / 'metadata.yaml').write_text(yaml.dump(metadata))

        item = create_deep_research_index_item(result_dir)

        assert item is not None
        assert 'path' in item
        assert 'type' in item
        assert 'name' in item
        assert 'description' in item
        assert 'content' in item
        assert 'text' in item
        assert 'embedding' in item
        assert 'tags' in item

    def test_item_has_correct_type(self, tmp_path):
        """Index item should have type 'deep_research'."""
        result_dir = tmp_path / "trun_type_test"
        result_dir.mkdir()

        metadata = {'run_id': 'trun_type_test', 'query': 'Test', 'processor': 'ultra'}
        (result_dir / 'metadata.yaml').write_text(yaml.dump(metadata))

        item = create_deep_research_index_item(result_dir)

        assert item['type'] == 'deep_research'

    def test_item_uses_query_as_description(self, tmp_path):
        """Index item should use query as description."""
        result_dir = tmp_path / "trun_desc_test"
        result_dir.mkdir()

        query = 'What are the benefits of AI?'
        metadata = {'run_id': 'trun_desc_test', 'query': query, 'processor': 'ultra'}
        (result_dir / 'metadata.yaml').write_text(yaml.dump(metadata))

        item = create_deep_research_index_item(result_dir)

        assert item['description'] == query

    def test_item_includes_output_in_text(self, tmp_path):
        """Index item text should include query and output summary."""
        result_dir = tmp_path / "trun_text_test"
        result_dir.mkdir()

        metadata = {'run_id': 'trun_text_test', 'query': 'AI query', 'processor': 'ultra'}
        (result_dir / 'metadata.yaml').write_text(yaml.dump(metadata))

        output = {'summary': 'AI is transforming industries', 'basis': []}
        (result_dir / 'output.yaml').write_text(yaml.dump(output))

        item = create_deep_research_index_item(result_dir)

        # Text should contain query
        assert 'AI query' in item['text']

    def test_returns_none_if_metadata_missing(self, tmp_path):
        """Should return None if metadata.yaml doesn't exist."""
        result_dir = tmp_path / "trun_no_metadata"
        result_dir.mkdir()

        item = create_deep_research_index_item(result_dir)

        assert item is None

    def test_item_has_tags(self, tmp_path):
        """Index item should have appropriate tags."""
        result_dir = tmp_path / "trun_tags_test"
        result_dir.mkdir()

        metadata = {'run_id': 'trun_tags_test', 'query': 'Test', 'processor': 'ultra8x'}
        (result_dir / 'metadata.yaml').write_text(yaml.dump(metadata))

        item = create_deep_research_index_item(result_dir)

        assert 'research' in item['tags']
        assert 'deep_research' in item['tags']

    def test_item_includes_processor_in_tags(self, tmp_path):
        """Index item should include processor in tags."""
        result_dir = tmp_path / "trun_processor_tag_test"
        result_dir.mkdir()

        metadata = {'run_id': 'trun_processor_tag_test', 'query': 'Test', 'processor': 'ultra4x'}
        (result_dir / 'metadata.yaml').write_text(yaml.dump(metadata))

        item = create_deep_research_index_item(result_dir)

        assert 'ultra4x' in item['tags']

    def test_item_uses_run_id_as_name(self, tmp_path):
        """Index item should use run_id as name."""
        result_dir = tmp_path / "trun_name_test"
        result_dir.mkdir()

        metadata = {'run_id': 'trun_name_test', 'query': 'Test', 'processor': 'ultra'}
        (result_dir / 'metadata.yaml').write_text(yaml.dump(metadata))

        item = create_deep_research_index_item(result_dir)

        assert item['name'] == 'trun_name_test'

    def test_handles_malformed_yaml(self, tmp_path):
        """Should return None if metadata.yaml is malformed."""
        result_dir = tmp_path / "trun_malformed"
        result_dir.mkdir()

        (result_dir / 'metadata.yaml').write_text("invalid: yaml: content: [")

        item = create_deep_research_index_item(result_dir)

        assert item is None


class TestUpdateIndex:
    """Tests for update_index function (idx-003)."""

    def test_update_index_creates_file_if_not_exists(self, tmp_path, monkeypatch):
        """update_index should create index.json if it doesn't exist."""
        index_path = tmp_path / "data" / "index.json"
        monkeypatch.setattr('lib.indexer.INDEX_PATH', index_path)

        item = {'path': 'test/path', 'type': 'test', 'name': 'test'}
        result = update_index(item)

        assert result['success'] is True
        assert index_path.exists()

    def test_update_index_adds_new_item(self, tmp_path, monkeypatch):
        """update_index should add new item to index."""
        index_path = tmp_path / "data" / "index.json"
        index_path.parent.mkdir(parents=True)

        # Create initial index
        initial = {'count': 0, 'items': [], 'generated_at': ''}
        index_path.write_text(json.dumps(initial))

        monkeypatch.setattr('lib.indexer.INDEX_PATH', index_path)

        item = {'path': 'new/path', 'type': 'test', 'name': 'new'}
        update_index(item)

        index = json.loads(index_path.read_text())
        assert index['count'] == 1
        assert len(index['items']) == 1
        assert index['items'][0]['path'] == 'new/path'

    def test_update_index_deduplicates_by_path(self, tmp_path, monkeypatch):
        """update_index should remove existing entry with same path."""
        index_path = tmp_path / "data" / "index.json"
        index_path.parent.mkdir(parents=True)

        # Create index with existing item
        initial = {
            'count': 1,
            'items': [{'path': 'same/path', 'type': 'old', 'name': 'old'}],
            'generated_at': ''
        }
        index_path.write_text(json.dumps(initial))

        monkeypatch.setattr('lib.indexer.INDEX_PATH', index_path)

        # Update with same path
        item = {'path': 'same/path', 'type': 'new', 'name': 'new'}
        update_index(item)

        index = json.loads(index_path.read_text())
        assert index['count'] == 1
        assert index['items'][0]['type'] == 'new'

    def test_update_index_updates_generated_at(self, tmp_path, monkeypatch):
        """update_index should update generated_at timestamp."""
        index_path = tmp_path / "data" / "index.json"
        index_path.parent.mkdir(parents=True)

        initial = {'count': 0, 'items': [], 'generated_at': '2000-01-01T00:00:00'}
        index_path.write_text(json.dumps(initial))

        monkeypatch.setattr('lib.indexer.INDEX_PATH', index_path)

        item = {'path': 'test/path', 'type': 'test', 'name': 'test'}
        update_index(item)

        index = json.loads(index_path.read_text())
        assert index['generated_at'] != '2000-01-01T00:00:00'

    def test_update_index_returns_removed_count(self, tmp_path, monkeypatch):
        """update_index should report how many items were removed."""
        index_path = tmp_path / "data" / "index.json"
        index_path.parent.mkdir(parents=True)

        # Create index with existing item
        initial = {
            'count': 1,
            'items': [{'path': 'existing/path', 'type': 'old', 'name': 'old'}],
            'generated_at': ''
        }
        index_path.write_text(json.dumps(initial))

        monkeypatch.setattr('lib.indexer.INDEX_PATH', index_path)

        # Update with same path
        item = {'path': 'existing/path', 'type': 'new', 'name': 'new'}
        result = update_index(item)

        assert result['removed_count'] == 1
        assert result['updated_count'] == 1

    def test_update_index_fails_without_path(self, tmp_path, monkeypatch):
        """update_index should fail if item has no path field."""
        index_path = tmp_path / "data" / "index.json"
        monkeypatch.setattr('lib.indexer.INDEX_PATH', index_path)

        item = {'type': 'test', 'name': 'test'}  # Missing 'path'
        result = update_index(item)

        assert result['success'] is False
        assert 'error' in result

    def test_update_index_handles_invalid_json(self, tmp_path, monkeypatch):
        """update_index should handle corrupted index file."""
        index_path = tmp_path / "data" / "index.json"
        index_path.parent.mkdir(parents=True)
        index_path.write_text("not valid json {{{")

        monkeypatch.setattr('lib.indexer.INDEX_PATH', index_path)

        item = {'path': 'test/path', 'type': 'test', 'name': 'test'}
        result = update_index(item)

        assert result['success'] is False
        assert 'error' in result


class TestRebuildDeepResearchIndex:
    """Tests for rebuild_deep_research_index function (idx-005)."""

    def test_rebuild_scans_results_directory(self, tmp_path, monkeypatch):
        """rebuild should scan data/deep_research/results/."""
        results_dir = tmp_path / "results"
        results_dir.mkdir()
        index_path = tmp_path / "index.json"

        monkeypatch.setattr('lib.indexer.DEEP_RESEARCH_RESULTS_DIR', results_dir)
        monkeypatch.setattr('lib.indexer.INDEX_PATH', index_path)

        # Create some result directories
        for i in range(3):
            result_dir = results_dir / f"trun_rebuild_{i}"
            result_dir.mkdir()
            metadata = {'run_id': f'trun_rebuild_{i}', 'query': f'Query {i}', 'processor': 'ultra'}
            (result_dir / 'metadata.yaml').write_text(yaml.dump(metadata))

        result = rebuild_deep_research_index()

        assert result['items_added'] == 3

    def test_rebuild_removes_stale_items(self, tmp_path, monkeypatch):
        """rebuild should remove stale deep_research items."""
        results_dir = tmp_path / "results"
        results_dir.mkdir()
        index_path = tmp_path / "index.json"
        index_path.parent.mkdir(parents=True, exist_ok=True)

        monkeypatch.setattr('lib.indexer.DEEP_RESEARCH_RESULTS_DIR', results_dir)
        monkeypatch.setattr('lib.indexer.INDEX_PATH', index_path)

        # Create initial index with stale item
        initial = {
            'count': 1,
            'items': [{'path': 'stale/path', 'type': 'deep_research', 'name': 'stale'}],
            'generated_at': ''
        }
        index_path.write_text(json.dumps(initial))

        # Empty results dir means all items are stale
        result = rebuild_deep_research_index()

        assert result['items_removed'] >= 1

    def test_rebuild_preserves_other_types(self, tmp_path, monkeypatch):
        """rebuild should preserve non-deep_research items."""
        results_dir = tmp_path / "results"
        results_dir.mkdir()
        index_path = tmp_path / "index.json"

        monkeypatch.setattr('lib.indexer.DEEP_RESEARCH_RESULTS_DIR', results_dir)
        monkeypatch.setattr('lib.indexer.INDEX_PATH', index_path)

        # Create initial index with different type
        initial = {
            'count': 1,
            'items': [{'path': 'agent/path', 'type': 'agent', 'name': 'builder'}],
            'generated_at': ''
        }
        index_path.write_text(json.dumps(initial))

        rebuild_deep_research_index()

        index = json.loads(index_path.read_text())
        agent_items = [i for i in index['items'] if i['type'] == 'agent']
        assert len(agent_items) == 1

    def test_rebuild_handles_missing_results_dir(self, tmp_path, monkeypatch):
        """rebuild should handle missing results directory gracefully."""
        results_dir = tmp_path / "nonexistent_results"
        index_path = tmp_path / "index.json"

        monkeypatch.setattr('lib.indexer.DEEP_RESEARCH_RESULTS_DIR', results_dir)
        monkeypatch.setattr('lib.indexer.INDEX_PATH', index_path)

        result = rebuild_deep_research_index()

        assert result['success'] is True
        assert result['items_added'] == 0

    def test_rebuild_returns_total_count(self, tmp_path, monkeypatch):
        """rebuild should return total count of items in index."""
        results_dir = tmp_path / "results"
        results_dir.mkdir()
        index_path = tmp_path / "index.json"

        monkeypatch.setattr('lib.indexer.DEEP_RESEARCH_RESULTS_DIR', results_dir)
        monkeypatch.setattr('lib.indexer.INDEX_PATH', index_path)

        # Create index with existing non-deep_research item
        initial = {
            'count': 2,
            'items': [
                {'path': 'agent/a', 'type': 'agent', 'name': 'a'},
                {'path': 'tool/b', 'type': 'tool', 'name': 'b'},
            ],
            'generated_at': ''
        }
        index_path.write_text(json.dumps(initial))

        # Create one deep_research result
        result_dir = results_dir / "trun_count_test"
        result_dir.mkdir()
        metadata = {'run_id': 'trun_count_test', 'query': 'Test', 'processor': 'ultra'}
        (result_dir / 'metadata.yaml').write_text(yaml.dump(metadata))

        result = rebuild_deep_research_index()

        assert result['total_count'] == 3  # 2 existing + 1 new

    def test_rebuild_skips_dirs_without_metadata(self, tmp_path, monkeypatch):
        """rebuild should skip directories without metadata.yaml."""
        results_dir = tmp_path / "results"
        results_dir.mkdir()
        index_path = tmp_path / "index.json"

        monkeypatch.setattr('lib.indexer.DEEP_RESEARCH_RESULTS_DIR', results_dir)
        monkeypatch.setattr('lib.indexer.INDEX_PATH', index_path)

        # Create directory without metadata
        (results_dir / "trun_no_meta").mkdir()

        # Create directory with metadata
        valid_dir = results_dir / "trun_valid"
        valid_dir.mkdir()
        metadata = {'run_id': 'trun_valid', 'query': 'Test', 'processor': 'ultra'}
        (valid_dir / 'metadata.yaml').write_text(yaml.dump(metadata))

        result = rebuild_deep_research_index()

        assert result['items_added'] == 1  # Only the valid one


class TestGetIndexStatus:
    """Tests for get_index_status function (idx-006)."""

    def test_status_returns_dict(self, tmp_path, monkeypatch):
        """get_index_status should return a dict."""
        index_path = tmp_path / "index.json"
        monkeypatch.setattr('lib.indexer.INDEX_PATH', index_path)

        result = get_index_status()

        assert isinstance(result, dict)

    def test_status_reports_exists_false_when_no_file(self, tmp_path, monkeypatch):
        """get_index_status should report exists=False when index.json missing."""
        index_path = tmp_path / "nonexistent" / "index.json"
        monkeypatch.setattr('lib.indexer.INDEX_PATH', index_path)

        result = get_index_status()

        assert result['exists'] is False

    def test_status_reports_count_by_type(self, tmp_path, monkeypatch):
        """get_index_status should report count by type."""
        index_path = tmp_path / "index.json"

        index = {
            'count': 5,
            'items': [
                {'type': 'deep_research', 'path': 'a'},
                {'type': 'deep_research', 'path': 'b'},
                {'type': 'agent', 'path': 'c'},
                {'type': 'tool', 'path': 'd'},
                {'type': 'tool', 'path': 'e'},
            ],
            'generated_at': '2025-12-01T12:00:00'
        }
        index_path.write_text(json.dumps(index))

        monkeypatch.setattr('lib.indexer.INDEX_PATH', index_path)

        result = get_index_status()

        assert result['exists'] is True
        assert result['count'] == 5
        assert result['by_type']['deep_research'] == 2
        assert result['by_type']['agent'] == 1
        assert result['by_type']['tool'] == 2

    def test_status_reports_generated_at(self, tmp_path, monkeypatch):
        """get_index_status should report generated_at timestamp."""
        index_path = tmp_path / "index.json"

        index = {
            'count': 0,
            'items': [],
            'generated_at': '2025-06-15T10:30:00'
        }
        index_path.write_text(json.dumps(index))

        monkeypatch.setattr('lib.indexer.INDEX_PATH', index_path)

        result = get_index_status()

        assert result['generated_at'] == '2025-06-15T10:30:00'

    def test_status_handles_empty_index(self, tmp_path, monkeypatch):
        """get_index_status should handle empty index gracefully."""
        index_path = tmp_path / "index.json"

        index = {'count': 0, 'items': [], 'generated_at': ''}
        index_path.write_text(json.dumps(index))

        monkeypatch.setattr('lib.indexer.INDEX_PATH', index_path)

        result = get_index_status()

        assert result['exists'] is True
        assert result['count'] == 0
        assert result['by_type'] == {}

    def test_status_handles_invalid_json(self, tmp_path, monkeypatch):
        """get_index_status should handle corrupted index file."""
        index_path = tmp_path / "index.json"
        index_path.write_text("not valid json")

        monkeypatch.setattr('lib.indexer.INDEX_PATH', index_path)

        result = get_index_status()

        assert result['success'] is False
        assert 'error' in result

    def test_status_handles_unknown_types(self, tmp_path, monkeypatch):
        """get_index_status should count items with unknown types."""
        index_path = tmp_path / "index.json"

        index = {
            'count': 2,
            'items': [
                {'path': 'a'},  # Missing type
                {'type': 'custom_type', 'path': 'b'},
            ],
            'generated_at': ''
        }
        index_path.write_text(json.dumps(index))

        monkeypatch.setattr('lib.indexer.INDEX_PATH', index_path)

        result = get_index_status()

        assert result['count'] == 2
        assert 'unknown' in result['by_type']
        assert result['by_type']['custom_type'] == 1


class TestIntegration:
    """Integration tests for the incremental indexing workflow."""

    def test_full_incremental_indexing_workflow(self, tmp_path, monkeypatch):
        """Test the complete flow: create item -> index -> verify in status."""
        # Set up paths
        results_dir = tmp_path / "data" / "deep_research" / "results"
        results_dir.mkdir(parents=True)
        index_path = tmp_path / "data" / "index.json"

        monkeypatch.setattr('lib.indexer.DEEP_RESEARCH_RESULTS_DIR', results_dir)
        monkeypatch.setattr('lib.indexer.INDEX_PATH', index_path)
        monkeypatch.chdir(tmp_path)

        # Step 1: Create a deep_research result
        result_dir = results_dir / "trun_integration"
        result_dir.mkdir()

        metadata = {
            'run_id': 'trun_integration',
            'query': 'What is the meaning of life?',
            'processor': 'ultra8x',
            'status': 'completed',
        }
        (result_dir / 'metadata.yaml').write_text(yaml.dump(metadata))

        output = {'answer': '42', 'basis': []}
        (result_dir / 'output.yaml').write_text(yaml.dump(output))

        # Step 2: Index the item incrementally
        result = incremental_index(str(result_dir / 'metadata.yaml'))

        assert result['success'] is True
        assert result['type'] == 'deep_research'

        # Step 3: Verify status reflects the new item
        status = get_index_status()

        assert status['exists'] is True
        assert status['count'] == 1
        assert status['by_type']['deep_research'] == 1

    def test_rebuild_after_incremental_updates(self, tmp_path, monkeypatch):
        """Test that rebuild correctly handles incremental updates."""
        # Set up paths
        results_dir = tmp_path / "results"
        results_dir.mkdir()
        index_path = tmp_path / "index.json"

        monkeypatch.setattr('lib.indexer.DEEP_RESEARCH_RESULTS_DIR', results_dir)
        monkeypatch.setattr('lib.indexer.INDEX_PATH', index_path)

        # Create initial index with mixed items
        initial = {
            'count': 2,
            'items': [
                {'path': 'agent/builder.yaml', 'type': 'agent', 'name': 'builder'},
                {'path': 'stale/deep_research', 'type': 'deep_research', 'name': 'stale'},
            ],
            'generated_at': ''
        }
        index_path.write_text(json.dumps(initial))

        # Create new result
        result_dir = results_dir / "trun_new"
        result_dir.mkdir()
        metadata = {'run_id': 'trun_new', 'query': 'New query', 'processor': 'ultra'}
        (result_dir / 'metadata.yaml').write_text(yaml.dump(metadata))

        # Rebuild
        result = rebuild_deep_research_index()

        # Should have removed stale item and added new one
        assert result['items_removed'] == 1
        assert result['items_added'] == 1
        assert result['total_count'] == 2  # 1 agent + 1 deep_research

        # Verify the agent is still there
        index = json.loads(index_path.read_text())
        types = [item['type'] for item in index['items']]
        assert 'agent' in types
        assert 'deep_research' in types


# Run with: pytest tests/test_indexer.py -v
if __name__ == '__main__':
    pytest.main([__file__, '-v'])

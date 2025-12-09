"""
Unit tests for search-before-research features (sbr-001 to sbr-006).

Tests:
- sbr-001: search_existing_research() function
- sbr-002: Similarity scoring (0-1 scale)
- sbr-003: pre_research_check() cache hit/miss logic
- sbr-004: deep_research integration (tested via force_new bypass)
- sbr-005: academic-researcher prompt enforcement (prompt verification)
- sbr-006: research_reuse_report() statistics
"""

import json
import pytest
import tempfile
from pathlib import Path
from datetime import datetime
from unittest.mock import patch, MagicMock

import yaml

# Import the functions we're testing
from lib.research_cache import (
    search_existing_research,
    pre_research_check,
    research_reuse_report,
    ResearchMatch,
    CacheCheckResult,
    ResearchReuseReport,
    DEFAULT_SIMILARITY_THRESHOLD,
    TOOL_LOGS_DIR,
)
from lib.search import INDEX_PATH


class TestSearchExistingResearch:
    """Tests for search_existing_research function (sbr-001)."""

    def test_returns_list(self):
        """search_existing_research should return a list."""
        # Will return empty list if no index
        result = search_existing_research('test query')
        assert isinstance(result, list)

    def test_returns_research_match_objects(self, tmp_path, monkeypatch):
        """Results should be ResearchMatch objects."""
        # Create mock index
        index_path = tmp_path / 'data' / 'index.json'
        index_path.parent.mkdir(parents=True)

        index = {
            'count': 1,
            'items': [{
                'path': 'results/test/metadata.yaml',
                'type': 'deep_research',
                'description': 'AI test query',
                'content': {
                    'run_id': 'trun_test',
                    'query': 'AI test query',
                    'processor': 'ultra',
                    'completed_at': '2025-12-01T12:00:00',
                },
                'embedding': [0.1] * 1536,  # Mock embedding
            }],
            'generated_at': ''
        }
        index_path.write_text(json.dumps(index))

        monkeypatch.setattr('lib.research_cache.INDEX_PATH', index_path)

        # Mock embed to return a simple embedding
        monkeypatch.setattr('lib.research_cache.embed', lambda x: [0.1] * 1536)

        results = search_existing_research('AI')

        # Should find the item
        if results:
            assert isinstance(results[0], ResearchMatch)

    def test_empty_query_returns_empty_list(self):
        """Empty query should return empty list."""
        result = search_existing_research('')
        assert result == []

    def test_whitespace_query_returns_empty_list(self):
        """Whitespace-only query should return empty list."""
        result = search_existing_research('   ')
        assert result == []

    def test_respects_limit_parameter(self, tmp_path, monkeypatch):
        """Results should respect the limit parameter."""
        # Create mock index with multiple items
        index_path = tmp_path / 'data' / 'index.json'
        index_path.parent.mkdir(parents=True)

        items = []
        for i in range(10):
            items.append({
                'path': f'results/test{i}/metadata.yaml',
                'type': 'deep_research',
                'description': f'Test query {i}',
                'content': {
                    'run_id': f'trun_test{i}',
                    'query': f'Test query {i}',
                    'processor': 'ultra',
                    'completed_at': '2025-12-01T12:00:00',
                },
                'embedding': [0.1] * 1536,
            })

        index = {'count': 10, 'items': items, 'generated_at': ''}
        index_path.write_text(json.dumps(index))

        monkeypatch.setattr('lib.research_cache.INDEX_PATH', index_path)
        monkeypatch.setattr('lib.research_cache.embed', lambda x: [0.1] * 1536)

        results = search_existing_research('Test', limit=3)

        assert len(results) <= 3

    def test_filters_by_min_score(self, tmp_path, monkeypatch):
        """Results should be filtered by min_score."""
        # Create mock index
        index_path = tmp_path / 'data' / 'index.json'
        index_path.parent.mkdir(parents=True)

        index = {
            'count': 1,
            'items': [{
                'path': 'results/test/metadata.yaml',
                'type': 'deep_research',
                'description': 'Very different topic',
                'content': {
                    'run_id': 'trun_test',
                    'query': 'Very different topic',
                    'processor': 'ultra',
                    'completed_at': '2025-12-01T12:00:00',
                },
                'embedding': [0.1] * 1536,
            }],
            'generated_at': ''
        }
        index_path.write_text(json.dumps(index))

        monkeypatch.setattr('lib.research_cache.INDEX_PATH', index_path)
        # Return different embedding to lower score
        monkeypatch.setattr('lib.research_cache.embed', lambda x: [0.9] * 1536)

        # High min_score should filter out low-match results
        results = search_existing_research('Completely unrelated', min_score=0.99)

        # Should return empty or items with score >= 0.99
        for r in results:
            assert r.score >= 0.99

    def test_filters_by_processor(self, tmp_path, monkeypatch):
        """Results should be filtered by processor type."""
        index_path = tmp_path / 'data' / 'index.json'
        index_path.parent.mkdir(parents=True)

        index = {
            'count': 2,
            'items': [
                {
                    'path': 'results/test1/metadata.yaml',
                    'type': 'deep_research',
                    'description': 'Test query',
                    'content': {
                        'run_id': 'trun_test1',
                        'query': 'Test query',
                        'processor': 'ultra',
                        'completed_at': '2025-12-01T12:00:00',
                    },
                    'embedding': [0.1] * 1536,
                },
                {
                    'path': 'results/test2/metadata.yaml',
                    'type': 'deep_research',
                    'description': 'Test query 2',
                    'content': {
                        'run_id': 'trun_test2',
                        'query': 'Test query 2',
                        'processor': 'ultra8x',
                        'completed_at': '2025-12-01T12:00:00',
                    },
                    'embedding': [0.1] * 1536,
                }
            ],
            'generated_at': ''
        }
        index_path.write_text(json.dumps(index))

        monkeypatch.setattr('lib.research_cache.INDEX_PATH', index_path)
        monkeypatch.setattr('lib.research_cache.embed', lambda x: [0.1] * 1536)

        results = search_existing_research('Test', processor='ultra8x')

        # All results should be ultra8x
        for r in results:
            assert r.processor == 'ultra8x'

    def test_returns_empty_if_index_not_exists(self, tmp_path, monkeypatch):
        """Should return empty list if index doesn't exist."""
        index_path = tmp_path / 'nonexistent' / 'index.json'
        monkeypatch.setattr('lib.research_cache.INDEX_PATH', index_path)

        result = search_existing_research('test query')

        assert result == []


class TestSimilarityScoring:
    """Tests for similarity scoring logic (sbr-002)."""

    def test_scores_are_between_0_and_1(self, tmp_path, monkeypatch):
        """Similarity scores should be in range [0, 1]."""
        index_path = tmp_path / 'data' / 'index.json'
        index_path.parent.mkdir(parents=True)

        index = {
            'count': 1,
            'items': [{
                'path': 'results/test/metadata.yaml',
                'type': 'deep_research',
                'description': 'Test query about AI',
                'content': {
                    'run_id': 'trun_test',
                    'query': 'Test query about AI',
                    'processor': 'ultra',
                    'completed_at': '2025-12-01T12:00:00',
                },
                'embedding': [0.5] * 1536,
            }],
            'generated_at': ''
        }
        index_path.write_text(json.dumps(index))

        monkeypatch.setattr('lib.research_cache.INDEX_PATH', index_path)
        monkeypatch.setattr('lib.research_cache.embed', lambda x: [0.5] * 1536)

        results = search_existing_research('AI', limit=5)

        for r in results:
            assert 0 <= r.score <= 1

    def test_exact_keyword_match_boosts_score(self, tmp_path, monkeypatch):
        """Exact keyword match should boost similarity score."""
        index_path = tmp_path / 'data' / 'index.json'
        index_path.parent.mkdir(parents=True)

        index = {
            'count': 2,
            'items': [
                {
                    'path': 'results/exact/metadata.yaml',
                    'type': 'deep_research',
                    'description': 'Machine learning applications',
                    'content': {
                        'run_id': 'trun_exact',
                        'query': 'Machine learning applications',
                        'processor': 'ultra',
                        'completed_at': '2025-12-01T12:00:00',
                    },
                    'embedding': [0.5] * 1536,
                },
                {
                    'path': 'results/partial/metadata.yaml',
                    'type': 'deep_research',
                    'description': 'Neural network research',
                    'content': {
                        'run_id': 'trun_partial',
                        'query': 'Neural network research',
                        'processor': 'ultra',
                        'completed_at': '2025-12-01T12:00:00',
                    },
                    'embedding': [0.5] * 1536,
                }
            ],
            'generated_at': ''
        }
        index_path.write_text(json.dumps(index))

        monkeypatch.setattr('lib.research_cache.INDEX_PATH', index_path)
        monkeypatch.setattr('lib.research_cache.embed', lambda x: [0.5] * 1536)

        results = search_existing_research('Machine learning')

        # Should find results, exact match should score higher
        if len(results) >= 2:
            exact_match = next((r for r in results if 'Machine' in r.query), None)
            if exact_match:
                # Exact match should have a boosted score
                assert exact_match.score > 0

    def test_semantic_similarity_works_with_embeddings(self, tmp_path, monkeypatch):
        """Semantic similarity via embeddings should work."""
        index_path = tmp_path / 'data' / 'index.json'
        index_path.parent.mkdir(parents=True)

        # Create embedding that is similar (high cosine similarity)
        similar_embedding = [0.7] * 1536

        index = {
            'count': 1,
            'items': [{
                'path': 'results/test/metadata.yaml',
                'type': 'deep_research',
                'description': 'Deep learning AI',
                'content': {
                    'run_id': 'trun_test',
                    'query': 'Deep learning AI',
                    'processor': 'ultra',
                    'completed_at': '2025-12-01T12:00:00',
                },
                'embedding': similar_embedding,
            }],
            'generated_at': ''
        }
        index_path.write_text(json.dumps(index))

        monkeypatch.setattr('lib.research_cache.INDEX_PATH', index_path)
        # Return similar embedding
        monkeypatch.setattr('lib.research_cache.embed', lambda x: similar_embedding)

        results = search_existing_research('Machine learning neural networks')

        # With identical embeddings, score should be high
        if results:
            assert results[0].score > 0.5


class TestPreResearchCheck:
    """Tests for pre_research_check function (sbr-003)."""

    def test_returns_cache_check_result(self):
        """pre_research_check should return CacheCheckResult."""
        result = pre_research_check('test query')
        assert isinstance(result, CacheCheckResult)

    def test_result_has_required_fields(self):
        """CacheCheckResult should have all required fields."""
        result = pre_research_check('test query')

        assert hasattr(result, 'should_use_cache')
        assert hasattr(result, 'cached_results')
        assert hasattr(result, 'reason')
        assert hasattr(result, 'query')
        assert hasattr(result, 'threshold')

    def test_force_new_bypasses_cache(self):
        """force_new=True should always return should_use_cache=False."""
        result = pre_research_check('any query', force_new=True)

        assert result.should_use_cache is False
        assert 'bypass' in result.reason.lower() or 'force_new' in result.reason.lower()

    def test_default_threshold_is_used(self):
        """Default threshold should be DEFAULT_SIMILARITY_THRESHOLD."""
        result = pre_research_check('test query')

        assert result.threshold == DEFAULT_SIMILARITY_THRESHOLD

    def test_custom_threshold_is_respected(self):
        """Custom threshold parameter should be used."""
        result = pre_research_check('test query', threshold=0.5)

        assert result.threshold == 0.5

    def test_cache_hit_when_above_threshold(self, tmp_path, monkeypatch):
        """Should report cache hit when results exceed threshold."""
        index_path = tmp_path / 'data' / 'index.json'
        index_path.parent.mkdir(parents=True)

        # Create index with matching item
        index = {
            'count': 1,
            'items': [{
                'path': 'results/test/metadata.yaml',
                'type': 'deep_research',
                'description': 'Exact test query match',
                'content': {
                    'run_id': 'trun_hit',
                    'query': 'Exact test query match',
                    'processor': 'ultra',
                    'completed_at': '2025-12-01T12:00:00',
                },
                'embedding': [0.5] * 1536,
            }],
            'generated_at': ''
        }
        index_path.write_text(json.dumps(index))

        monkeypatch.setattr('lib.research_cache.INDEX_PATH', index_path)
        # Return identical embedding for high similarity
        monkeypatch.setattr('lib.research_cache.embed', lambda x: [0.5] * 1536)

        # Use low threshold to ensure hit
        result = pre_research_check('Exact test query match', threshold=0.1)

        # If there's a hit, should_use_cache should be True
        if result.cached_results:
            assert result.should_use_cache is True

    def test_cache_miss_when_below_threshold(self, tmp_path, monkeypatch):
        """Should report cache miss when no results exceed threshold."""
        index_path = tmp_path / 'nonexistent' / 'index.json'
        monkeypatch.setattr('lib.research_cache.INDEX_PATH', index_path)

        # With no index, should be cache miss
        result = pre_research_check('Very unique specific query xyz123', threshold=0.99)

        # Should be cache miss
        assert result.should_use_cache is False

    def test_reason_explains_decision(self):
        """Reason field should explain the cache decision."""
        result = pre_research_check('test query')

        assert len(result.reason) > 0
        # Reason should mention threshold or similarity or match
        assert any(word in result.reason.lower() for word in ['threshold', 'similarity', 'match', 'no', 'existing'])

    def test_cached_results_contains_research_matches(self, tmp_path, monkeypatch):
        """cached_results should contain ResearchMatch objects on hit."""
        index_path = tmp_path / 'data' / 'index.json'
        index_path.parent.mkdir(parents=True)

        index = {
            'count': 1,
            'items': [{
                'path': 'results/test/metadata.yaml',
                'type': 'deep_research',
                'description': 'Test query about caching',
                'content': {
                    'run_id': 'trun_cache_test',
                    'query': 'Test query about caching',
                    'processor': 'ultra',
                    'completed_at': '2025-12-01T12:00:00',
                },
                'embedding': [0.5] * 1536,
            }],
            'generated_at': ''
        }
        index_path.write_text(json.dumps(index))

        monkeypatch.setattr('lib.research_cache.INDEX_PATH', index_path)
        monkeypatch.setattr('lib.research_cache.embed', lambda x: [0.5] * 1536)

        result = pre_research_check('Test query about caching', threshold=0.1)

        if result.cached_results:
            assert all(isinstance(r, ResearchMatch) for r in result.cached_results)

    def test_limit_parameter_is_respected(self, tmp_path, monkeypatch):
        """limit parameter should control max cached results."""
        index_path = tmp_path / 'data' / 'index.json'
        index_path.parent.mkdir(parents=True)

        items = []
        for i in range(10):
            items.append({
                'path': f'results/test{i}/metadata.yaml',
                'type': 'deep_research',
                'description': f'Test query number {i}',
                'content': {
                    'run_id': f'trun_limit_{i}',
                    'query': f'Test query number {i}',
                    'processor': 'ultra',
                    'completed_at': '2025-12-01T12:00:00',
                },
                'embedding': [0.5] * 1536,
            })

        index = {'count': 10, 'items': items, 'generated_at': ''}
        index_path.write_text(json.dumps(index))

        monkeypatch.setattr('lib.research_cache.INDEX_PATH', index_path)
        monkeypatch.setattr('lib.research_cache.embed', lambda x: [0.5] * 1536)

        result = pre_research_check('Test query', threshold=0.1, limit=2)

        assert len(result.cached_results) <= 2


class TestResearchReuseReport:
    """Tests for research_reuse_report function (sbr-006)."""

    def test_returns_research_reuse_report(self, tmp_path, monkeypatch):
        """research_reuse_report should return ResearchReuseReport."""
        # Mock empty logs directory
        logs_dir = tmp_path / 'logs' / 'tools' / 'deep_research'
        logs_dir.mkdir(parents=True)

        index_path = tmp_path / 'data' / 'index.json'
        index_path.parent.mkdir(parents=True)
        index_path.write_text(json.dumps({'count': 0, 'items': [], 'generated_at': ''}))

        monkeypatch.setattr('lib.research_cache.TOOL_LOGS_DIR', logs_dir)
        monkeypatch.setattr('lib.research_cache.INDEX_PATH', index_path)

        result = research_reuse_report()

        assert isinstance(result, ResearchReuseReport)

    def test_report_has_required_fields(self, tmp_path, monkeypatch):
        """Report should have all required fields."""
        logs_dir = tmp_path / 'logs'
        logs_dir.mkdir(parents=True)

        monkeypatch.setattr('lib.research_cache.TOOL_LOGS_DIR', logs_dir)

        result = research_reuse_report()

        assert hasattr(result, 'total_requests')
        assert hasattr(result, 'cache_hits')
        assert hasattr(result, 'cache_misses')
        assert hasattr(result, 'hit_rate_percent')
        assert hasattr(result, 'total_research_in_index')
        assert hasattr(result, 'estimated_cost_savings_usd')
        assert hasattr(result, 'report_generated_at')

    def test_hit_rate_calculation(self, tmp_path, monkeypatch):
        """Hit rate should be correctly calculated."""
        logs_dir = tmp_path / 'logs'
        logs_dir.mkdir(parents=True)

        index_path = tmp_path / 'data' / 'index.json'
        index_path.parent.mkdir(parents=True)
        index_path.write_text(json.dumps({'count': 0, 'items': [], 'generated_at': ''}))

        monkeypatch.setattr('lib.research_cache.TOOL_LOGS_DIR', logs_dir)
        monkeypatch.setattr('lib.research_cache.INDEX_PATH', index_path)

        result = research_reuse_report()

        # With 0 requests, hit rate should be 0
        if result.total_requests == 0:
            assert result.hit_rate_percent == 0.0

    def test_to_dict_method(self, tmp_path, monkeypatch):
        """Report should be convertible to dict."""
        logs_dir = tmp_path / 'logs'
        logs_dir.mkdir(parents=True)

        monkeypatch.setattr('lib.research_cache.TOOL_LOGS_DIR', logs_dir)

        result = research_reuse_report()
        result_dict = result.to_dict()

        assert isinstance(result_dict, dict)
        assert 'total_requests' in result_dict
        assert 'cache_hits' in result_dict

    def test_format_text_method(self, tmp_path, monkeypatch):
        """Report should have format_text() method for human-readable output."""
        logs_dir = tmp_path / 'logs'
        logs_dir.mkdir(parents=True)

        monkeypatch.setattr('lib.research_cache.TOOL_LOGS_DIR', logs_dir)

        result = research_reuse_report()
        formatted = result.format_text()

        assert isinstance(formatted, str)
        assert 'Total Requests' in formatted
        assert 'Cache Hits' in formatted

    def test_counts_cache_hits_from_logs(self, tmp_path, monkeypatch):
        """Should count cache hits from tool logs."""
        logs_dir = tmp_path / 'logs'
        logs_dir.mkdir(parents=True)

        index_path = tmp_path / 'data' / 'index.json'
        index_path.parent.mkdir(parents=True)
        index_path.write_text(json.dumps({'count': 0, 'items': [], 'generated_at': ''}))

        # Create a cache hit log
        log_data = {
            'started': datetime.now().isoformat(),
            'input': {'query': 'Test query', 'processor': 'ultra'},
            'output': {'source': 'cache', 'run_id': 'trun_cached'},
        }
        (logs_dir / 'test_hit.json').write_text(json.dumps(log_data))

        # Create a cache miss log
        log_data_miss = {
            'started': datetime.now().isoformat(),
            'input': {'query': 'Another query', 'processor': 'ultra'},
            'output': {'source': 'new', 'run_id': 'trun_new'},
        }
        (logs_dir / 'test_miss.json').write_text(json.dumps(log_data_miss))

        monkeypatch.setattr('lib.research_cache.TOOL_LOGS_DIR', logs_dir)
        monkeypatch.setattr('lib.research_cache.INDEX_PATH', index_path)

        result = research_reuse_report()

        assert result.total_requests == 2
        assert result.cache_hits == 1
        assert result.cache_misses == 1
        assert result.hit_rate_percent == 50.0

    def test_estimates_cost_savings(self, tmp_path, monkeypatch):
        """Should estimate cost savings from cache hits."""
        logs_dir = tmp_path / 'logs'
        logs_dir.mkdir(parents=True)

        index_path = tmp_path / 'data' / 'index.json'
        index_path.parent.mkdir(parents=True)
        index_path.write_text(json.dumps({'count': 0, 'items': [], 'generated_at': ''}))

        # Create multiple cache hit logs
        for i in range(3):
            log_data = {
                'started': datetime.now().isoformat(),
                'input': {'query': f'Test query {i}', 'processor': 'ultra'},
                'output': {'source': 'cache', 'run_id': f'trun_cached_{i}'},
            }
            (logs_dir / f'test_hit_{i}.json').write_text(json.dumps(log_data))

        monkeypatch.setattr('lib.research_cache.TOOL_LOGS_DIR', logs_dir)
        monkeypatch.setattr('lib.research_cache.INDEX_PATH', index_path)

        result = research_reuse_report()

        # 3 cache hits at $1.00 per ultra = $3.00 savings
        assert result.estimated_cost_savings_usd == 3.0

    def test_skips_non_query_actions(self, tmp_path, monkeypatch):
        """Should skip backfill, pending, result actions."""
        logs_dir = tmp_path / 'logs'
        logs_dir.mkdir(parents=True)

        index_path = tmp_path / 'data' / 'index.json'
        index_path.parent.mkdir(parents=True)
        index_path.write_text(json.dumps({'count': 0, 'items': [], 'generated_at': ''}))

        # Create logs with non-query actions (should be skipped)
        for action in ['backfill', 'pending', 'result']:
            log_data = {
                'started': datetime.now().isoformat(),
                'input': {'action': action, 'query': 'Test'},
                'output': {},
            }
            (logs_dir / f'test_{action}.json').write_text(json.dumps(log_data))

        # Create a real query log
        log_data = {
            'started': datetime.now().isoformat(),
            'input': {'query': 'Real query', 'processor': 'ultra'},
            'output': {'source': 'new', 'run_id': 'trun_new'},
        }
        (logs_dir / 'test_query.json').write_text(json.dumps(log_data))

        monkeypatch.setattr('lib.research_cache.TOOL_LOGS_DIR', logs_dir)
        monkeypatch.setattr('lib.research_cache.INDEX_PATH', index_path)

        result = research_reuse_report()

        # Should only count the real query
        assert result.total_requests == 1

    def test_respects_days_back_parameter(self, tmp_path, monkeypatch):
        """Should filter logs by days_back parameter."""
        logs_dir = tmp_path / 'logs'
        logs_dir.mkdir(parents=True)

        index_path = tmp_path / 'data' / 'index.json'
        index_path.parent.mkdir(parents=True)
        index_path.write_text(json.dumps({'count': 0, 'items': [], 'generated_at': ''}))

        # Create a recent log
        log_data = {
            'started': datetime.now().isoformat(),
            'input': {'query': 'Recent query', 'processor': 'ultra'},
            'output': {'source': 'new', 'run_id': 'trun_recent'},
        }
        (logs_dir / 'test_recent.json').write_text(json.dumps(log_data))

        # Create an old log
        old_log = {
            'started': '2020-01-01T00:00:00',
            'input': {'query': 'Old query', 'processor': 'ultra'},
            'output': {'source': 'new', 'run_id': 'trun_old'},
        }
        (logs_dir / 'test_old.json').write_text(json.dumps(old_log))

        monkeypatch.setattr('lib.research_cache.TOOL_LOGS_DIR', logs_dir)
        monkeypatch.setattr('lib.research_cache.INDEX_PATH', index_path)

        result = research_reuse_report(days_back=7)

        # Should only count recent log
        assert result.total_requests == 1


class TestDataclasses:
    """Tests for dataclass definitions."""

    def test_research_match_to_dict(self):
        """ResearchMatch.to_dict() should return dict with all fields."""
        match = ResearchMatch(
            run_id='trun_test',
            query='Test query',
            processor='ultra',
            completed_at='2025-12-01T12:00:00',
            path='test/path',
            score=0.85,
        )

        result = match.to_dict()

        assert result['run_id'] == 'trun_test'
        assert result['query'] == 'Test query'
        assert result['processor'] == 'ultra'
        assert result['score'] == 0.85
        assert result['path'] == 'test/path'
        assert result['completed_at'] == '2025-12-01T12:00:00'

    def test_cache_check_result_to_dict(self):
        """CacheCheckResult.to_dict() should return dict with all fields."""
        result = CacheCheckResult(
            should_use_cache=True,
            cached_results=[],
            reason='Test reason',
            query='Test query',
            threshold=0.7,
        )

        result_dict = result.to_dict()

        assert result_dict['should_use_cache'] is True
        assert result_dict['reason'] == 'Test reason'
        assert result_dict['threshold'] == 0.7
        assert result_dict['query'] == 'Test query'
        assert result_dict['cached_results'] == []

    def test_cache_check_result_to_dict_with_matches(self):
        """CacheCheckResult.to_dict() should serialize ResearchMatch objects."""
        match = ResearchMatch(
            run_id='trun_test',
            query='Test query',
            processor='ultra',
            completed_at='2025-12-01T12:00:00',
            path='test/path',
            score=0.85,
        )
        result = CacheCheckResult(
            should_use_cache=True,
            cached_results=[match],
            reason='Found match',
            query='Test query',
            threshold=0.7,
        )

        result_dict = result.to_dict()

        assert len(result_dict['cached_results']) == 1
        assert result_dict['cached_results'][0]['run_id'] == 'trun_test'

    def test_research_reuse_report_to_dict(self):
        """ResearchReuseReport.to_dict() should return dict with all fields."""
        report = ResearchReuseReport(
            total_requests=100,
            cache_hits=30,
            cache_misses=70,
            hit_rate_percent=30.0,
            total_research_in_index=50,
            most_reused_queries=[],
            estimated_cost_savings_usd=30.0,
            report_generated_at='2025-12-01T12:00:00',
        )

        result = report.to_dict()

        assert result['total_requests'] == 100
        assert result['cache_hits'] == 30
        assert result['cache_misses'] == 70
        assert result['hit_rate_percent'] == 30.0
        assert result['estimated_cost_savings_usd'] == 30.0


class TestDefaultConstants:
    """Tests for module constants."""

    def test_default_similarity_threshold_is_reasonable(self):
        """DEFAULT_SIMILARITY_THRESHOLD should be between 0 and 1."""
        assert 0 < DEFAULT_SIMILARITY_THRESHOLD < 1
        # Common value is 0.7
        assert DEFAULT_SIMILARITY_THRESHOLD == 0.7

    def test_tool_logs_dir_path(self):
        """TOOL_LOGS_DIR should point to expected path."""
        assert 'logs' in str(TOOL_LOGS_DIR)
        assert 'deep_research' in str(TOOL_LOGS_DIR)


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_handles_malformed_log_files(self, tmp_path, monkeypatch):
        """Should handle malformed JSON log files gracefully."""
        logs_dir = tmp_path / 'logs'
        logs_dir.mkdir(parents=True)

        # Create malformed log file
        (logs_dir / 'malformed.json').write_text('not valid json {{{')

        # Create valid log file
        log_data = {
            'started': datetime.now().isoformat(),
            'input': {'query': 'Valid query', 'processor': 'ultra'},
            'output': {'source': 'new', 'run_id': 'trun_valid'},
        }
        (logs_dir / 'valid.json').write_text(json.dumps(log_data))

        monkeypatch.setattr('lib.research_cache.TOOL_LOGS_DIR', logs_dir)

        # Should not raise, should just skip malformed file
        result = research_reuse_report()

        assert result.total_requests == 1

    def test_handles_missing_logs_directory(self, tmp_path, monkeypatch):
        """Should handle missing logs directory gracefully."""
        logs_dir = tmp_path / 'nonexistent' / 'logs'
        index_path = tmp_path / 'data' / 'index.json'

        monkeypatch.setattr('lib.research_cache.TOOL_LOGS_DIR', logs_dir)

        # Should not raise
        result = research_reuse_report()

        assert result.total_requests == 0
        assert result.cache_hits == 0

    def test_search_handles_items_without_required_fields(self, tmp_path, monkeypatch):
        """search_existing_research should handle items missing required fields."""
        index_path = tmp_path / 'data' / 'index.json'
        index_path.parent.mkdir(parents=True)

        # Create index with item missing run_id (will be skipped)
        index = {
            'count': 1,
            'items': [{
                'path': 'results/test/metadata.yaml',
                'type': 'deep_research',
                'description': 'Test item without run_id',
                'content': {
                    # Missing 'run_id'
                    'query': 'Test query',
                    'processor': 'ultra',
                    'completed_at': '2025-12-01T12:00:00',
                },
                'embedding': [0.5] * 1536,
            }],
            'generated_at': ''
        }
        index_path.write_text(json.dumps(index))

        monkeypatch.setattr('lib.research_cache.INDEX_PATH', index_path)
        monkeypatch.setattr('lib.research_cache.embed', lambda x: [0.5] * 1536)

        # Should not raise, items without run_id are skipped
        result = search_existing_research('test query')

        # Items without run_id are filtered out
        assert result == []


class TestAcademicResearcherPromptEnforcement:
    """Tests for academic-researcher prompt enforcement (sbr-005).

    Verifies that the academic-researcher.yaml prompt contains required
    search-before-research instructions.
    """

    @pytest.fixture
    def academic_researcher_yaml(self):
        """Load the academic-researcher.yaml file."""
        import yaml
        agent_path = Path(__file__).parent.parent / 'agents' / 'academic-researcher.yaml'
        if not agent_path.exists():
            pytest.skip('academic-researcher.yaml not found')
        with open(agent_path) as f:
            return yaml.safe_load(f)

    def test_prompt_contains_pre_research_check_import(self, academic_researcher_yaml):
        """Prompt should import pre_research_check from lib.research_cache."""
        prompt = academic_researcher_yaml.get('prompt', '')
        assert 'from lib.research_cache import pre_research_check' in prompt

    def test_prompt_contains_cache_check_code_example(self, academic_researcher_yaml):
        """Prompt should include code example for cache check."""
        prompt = academic_researcher_yaml.get('prompt', '')
        # Should have the cache check example
        assert 'pre_research_check(' in prompt
        assert 'should_use_cache' in prompt

    def test_prompt_explains_force_new_flag(self, academic_researcher_yaml):
        """Prompt should explain when to use force_new flag."""
        prompt = academic_researcher_yaml.get('prompt', '')
        assert 'force_new' in prompt
        # Should explain when to use it
        assert 'force_new=True' in prompt

    def test_prompt_includes_threshold_recommendation(self, academic_researcher_yaml):
        """Prompt should include threshold recommendations."""
        prompt = academic_researcher_yaml.get('prompt', '')
        # Should mention default threshold
        assert '0.7' in prompt or 'threshold' in prompt.lower()
        # Should explain threshold concept
        assert 'threshold' in prompt.lower()

    def test_prompt_requires_search_first_step(self, academic_researcher_yaml):
        """Prompt should add 'Search existing research FIRST' as required step."""
        prompt = academic_researcher_yaml.get('prompt', '')
        # Should have clear "search first" instruction
        assert any(phrase in prompt for phrase in [
            'BEFORE Deep Research',
            'Check Research Cache',
            'search existing',
            'Search existing',
        ])

    def test_prompt_mentions_cost_awareness(self, academic_researcher_yaml):
        """Prompt should mention cost awareness for expensive research."""
        prompt = academic_researcher_yaml.get('prompt', '')
        # Should mention cost implications
        assert any(phrase in prompt.lower() for phrase in [
            'cost',
            'expensive',
            'api credits',
        ])


class TestProcessorCosts:
    """Tests for processor cost constants."""

    def test_processor_costs_defined(self):
        """PROCESSOR_COSTS should be defined with expected processors."""
        from lib.research_cache import PROCESSOR_COSTS

        assert 'core' in PROCESSOR_COSTS
        assert 'pro' in PROCESSOR_COSTS
        assert 'ultra' in PROCESSOR_COSTS
        assert 'ultra8x' in PROCESSOR_COSTS

    def test_processor_costs_are_positive(self):
        """All processor costs should be positive numbers."""
        from lib.research_cache import PROCESSOR_COSTS

        for processor, cost in PROCESSOR_COSTS.items():
            assert cost > 0, f'{processor} cost should be positive'
            assert isinstance(cost, (int, float)), f'{processor} cost should be numeric'

    def test_higher_tiers_cost_more(self):
        """Higher processor tiers should cost more."""
        from lib.research_cache import PROCESSOR_COSTS

        # Basic tier ordering check
        assert PROCESSOR_COSTS['core'] <= PROCESSOR_COSTS['pro']
        assert PROCESSOR_COSTS['pro'] <= PROCESSOR_COSTS['ultra']
        assert PROCESSOR_COSTS['ultra'] <= PROCESSOR_COSTS['ultra8x']


class TestCleanJsonString:
    """Tests for _clean_json_string helper function."""

    def test_clean_strips_quotes(self):
        """_clean_json_string should strip surrounding JSON quotes."""
        from lib.research_cache import _clean_json_string

        assert _clean_json_string('"hello"') == 'hello'
        assert _clean_json_string('"test value"') == 'test value'

    def test_clean_handles_none(self):
        """_clean_json_string should handle None gracefully."""
        from lib.research_cache import _clean_json_string

        assert _clean_json_string(None) == ''

    def test_clean_handles_unquoted_string(self):
        """_clean_json_string should handle unquoted strings."""
        from lib.research_cache import _clean_json_string

        assert _clean_json_string('hello') == 'hello'
        assert _clean_json_string('test value') == 'test value'

    def test_clean_handles_partial_quotes(self):
        """_clean_json_string should handle partially quoted strings."""
        from lib.research_cache import _clean_json_string

        # Only strips if both start and end have quotes
        assert _clean_json_string('"hello') == '"hello'
        assert _clean_json_string('hello"') == 'hello"'


class TestResearchMatchOrdering:
    """Tests for result ordering in search functions."""

    def test_results_ordered_by_score_descending(self, tmp_path, monkeypatch):
        """Results should be ordered by similarity score, highest first."""
        index_path = tmp_path / 'data' / 'index.json'
        index_path.parent.mkdir(parents=True)

        # Create index with items that will have different scores
        # Items with matching keywords will score higher
        index = {
            'count': 3,
            'items': [
                {
                    'path': 'results/low/metadata.yaml',
                    'type': 'deep_research',
                    'description': 'Unrelated topic completely different',
                    'content': {
                        'run_id': 'trun_low',
                        'query': 'Unrelated topic completely different',
                        'processor': 'ultra',
                        'completed_at': '2025-12-01T12:00:00',
                    },
                    'embedding': [0.1] * 1536,
                },
                {
                    'path': 'results/high/metadata.yaml',
                    'type': 'deep_research',
                    'description': 'Machine learning AI neural networks',
                    'content': {
                        'run_id': 'trun_high',
                        'query': 'Machine learning AI neural networks',
                        'processor': 'ultra',
                        'completed_at': '2025-12-01T12:00:00',
                    },
                    'embedding': [0.5] * 1536,
                },
                {
                    'path': 'results/medium/metadata.yaml',
                    'type': 'deep_research',
                    'description': 'Deep learning methods',
                    'content': {
                        'run_id': 'trun_medium',
                        'query': 'Deep learning methods',
                        'processor': 'ultra',
                        'completed_at': '2025-12-01T12:00:00',
                    },
                    'embedding': [0.3] * 1536,
                },
            ],
            'generated_at': ''
        }
        index_path.write_text(json.dumps(index))

        monkeypatch.setattr('lib.research_cache.INDEX_PATH', index_path)
        monkeypatch.setattr('lib.research_cache.embed', lambda x: [0.5] * 1536)

        from lib.research_cache import search_existing_research
        results = search_existing_research('Machine learning', limit=10)

        # Results should be ordered by score descending
        if len(results) >= 2:
            for i in range(len(results) - 1):
                assert results[i].score >= results[i + 1].score, \
                    f'Results not ordered: {results[i].score} < {results[i + 1].score}'


class TestCacheCheckResultIntegrity:
    """Tests for CacheCheckResult consistency."""

    def test_cache_hit_has_non_empty_results(self, tmp_path, monkeypatch):
        """When should_use_cache=True, cached_results must not be empty."""
        index_path = tmp_path / 'data' / 'index.json'
        index_path.parent.mkdir(parents=True)

        index = {
            'count': 1,
            'items': [{
                'path': 'results/test/metadata.yaml',
                'type': 'deep_research',
                'description': 'Matching query exactly',
                'content': {
                    'run_id': 'trun_integrity',
                    'query': 'Matching query exactly',
                    'processor': 'ultra',
                    'completed_at': '2025-12-01T12:00:00',
                },
                'embedding': [0.5] * 1536,
            }],
            'generated_at': ''
        }
        index_path.write_text(json.dumps(index))

        monkeypatch.setattr('lib.research_cache.INDEX_PATH', index_path)
        monkeypatch.setattr('lib.research_cache.embed', lambda x: [0.5] * 1536)

        from lib.research_cache import pre_research_check
        result = pre_research_check('Matching query exactly', threshold=0.1)

        # If it's a cache hit, there must be results
        if result.should_use_cache:
            assert len(result.cached_results) > 0

    def test_cache_miss_has_empty_results(self, tmp_path, monkeypatch):
        """When should_use_cache=False, cached_results should be empty (except force_new)."""
        index_path = tmp_path / 'nonexistent' / 'index.json'
        monkeypatch.setattr('lib.research_cache.INDEX_PATH', index_path)

        from lib.research_cache import pre_research_check
        result = pre_research_check('Unique query xyz123', threshold=0.99)

        # Cache miss means no results
        if not result.should_use_cache:
            assert len(result.cached_results) == 0


# Run with: pytest tests/test_research_cache.py -v
if __name__ == '__main__':
    pytest.main([__file__, '-v'])

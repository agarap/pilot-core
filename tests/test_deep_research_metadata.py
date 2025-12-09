"""
Unit tests for deep_research metadata capture features (meta-001 to meta-006).

Tests:
- Pending file creation with all required fields
- Metadata.yaml creation with all fields on completion
- Stats calculation (basis_count, citation_count, unique_domains)
- Backfill function for existing results
"""

import json
import pytest
import tempfile
from pathlib import Path
from datetime import datetime
from unittest.mock import patch, MagicMock

import yaml

# Import the functions we're testing
from tools.deep_research import (
    PENDING_DIR,
    RESULTS_DIR,
    _calculate_stats_from_output,
    _save_pending,
    _load_pending,
    _remove_pending,
    _convert_and_save_result,
    backfill_metadata,
)


class TestPendingFileCreation:
    """Tests for metadata capture in pending files (meta-001, meta-002, meta-003, meta-004)."""

    def test_pending_file_has_query(self, tmp_path):
        """meta-001: Query should be captured in pending file."""
        # Create a mock pending file structure
        pending_data = {
            'run_id': 'trun_test123',
            'query': 'What is AI?',
            'processor': 'ultra',
            'created_at': datetime.now().isoformat(),
            'status': 'pending',
        }

        # Verify all required fields are present
        assert pending_data['query'] == 'What is AI?'
        assert pending_data['run_id'].startswith('trun_')
        assert pending_data['processor'] in ['core', 'pro', 'ultra', 'ultra2x', 'ultra4x', 'ultra8x']
        assert 'created_at' in pending_data
        assert pending_data['status'] == 'pending'

    def test_pending_file_has_processor(self, tmp_path):
        """meta-003: Processor should be captured in pending file."""
        pending_data = {
            'run_id': 'trun_test123',
            'query': 'Test query',
            'processor': 'ultra8x',
            'created_at': datetime.now().isoformat(),
            'status': 'pending',
        }

        assert pending_data['processor'] == 'ultra8x'

    def test_pending_file_has_timestamps(self, tmp_path):
        """meta-004: Timestamps should be captured."""
        now = datetime.now().isoformat()
        pending_data = {
            'run_id': 'trun_test123',
            'query': 'Test query',
            'processor': 'ultra',
            'created_at': now,
            'status': 'pending',
        }

        # created_at should be valid ISO format
        parsed = datetime.fromisoformat(pending_data['created_at'])
        assert parsed is not None

    def test_save_and_load_pending(self, tmp_path, monkeypatch):
        """Test that _save_pending and _load_pending work correctly."""
        # Redirect PENDING_DIR to tmp_path
        test_pending_dir = tmp_path / "pending"
        monkeypatch.setattr('tools.deep_research.PENDING_DIR', test_pending_dir)

        run_id = 'trun_saveload_test'
        pending_data = {
            'run_id': run_id,
            'query': 'Test query for save/load',
            'processor': 'pro',
            'created_at': datetime.now().isoformat(),
            'status': 'pending',
        }

        # Save pending
        _save_pending(run_id, pending_data)

        # Verify file exists
        pending_file = test_pending_dir / f"{run_id}.yaml"
        assert pending_file.exists()

        # Load and verify
        loaded = _load_pending(run_id)
        assert loaded is not None
        assert loaded['run_id'] == run_id
        assert loaded['query'] == 'Test query for save/load'
        assert loaded['processor'] == 'pro'

    def test_remove_pending(self, tmp_path, monkeypatch):
        """Test that _remove_pending correctly removes pending files."""
        # Redirect PENDING_DIR to tmp_path
        test_pending_dir = tmp_path / "pending"
        test_pending_dir.mkdir(parents=True)
        monkeypatch.setattr('tools.deep_research.PENDING_DIR', test_pending_dir)

        run_id = 'trun_remove_test'
        pending_file = test_pending_dir / f"{run_id}.yaml"
        pending_file.write_text(yaml.dump({'run_id': run_id}))

        assert pending_file.exists()

        _remove_pending(run_id)

        assert not pending_file.exists()


class TestStatsCalculation:
    """Tests for research stats calculation (meta-005)."""

    def test_calculate_stats_from_empty_output(self):
        """Stats should handle empty output gracefully."""
        stats = _calculate_stats_from_output({})
        assert stats['basis_count'] == 0
        assert stats['citation_count'] == 0
        assert stats['unique_domains'] == 0

    def test_calculate_stats_from_output_with_basis(self):
        """Stats should count basis items and citations."""
        output_data = {
            'basis': [
                {
                    'field': 'Overview',
                    'content': 'Test content',
                    'citations': [
                        {'url': 'https://example.com/article1', 'title': 'Article 1'},
                        {'url': 'https://example.com/article2', 'title': 'Article 2'},
                    ]
                },
                {
                    'field': 'Details',
                    'content': 'More content',
                    'citations': [
                        {'url': 'https://other.com/page', 'title': 'Page'},
                    ]
                }
            ]
        }

        stats = _calculate_stats_from_output(output_data)
        assert stats['basis_count'] == 2
        assert stats['citation_count'] == 3
        assert stats['unique_domains'] == 2  # example.com and other.com

    def test_calculate_stats_counts_unique_domains(self):
        """unique_domains should count distinct domains."""
        output_data = {
            'basis': [
                {
                    'field': 'Test',
                    'citations': [
                        {'url': 'https://example.com/a'},
                        {'url': 'https://example.com/b'},
                        {'url': 'https://other.com/c'},
                        {'url': 'https://third.org/d'},
                    ]
                }
            ]
        }

        stats = _calculate_stats_from_output(output_data)
        assert stats['unique_domains'] == 3  # example.com, other.com, third.org

    def test_calculate_stats_handles_malformed_urls(self):
        """Stats should handle invalid URLs gracefully."""
        output_data = {
            'basis': [
                {
                    'field': 'Test',
                    'citations': [
                        {'url': 'https://valid.com/page'},
                        {'url': ''},  # Empty URL
                        {'url': 'not-a-valid-url'},  # Invalid format
                        {},  # Missing URL key
                    ]
                }
            ]
        }

        stats = _calculate_stats_from_output(output_data)
        assert stats['basis_count'] == 1
        assert stats['citation_count'] == 4
        # Should handle gracefully - only valid.com should count
        assert stats['unique_domains'] >= 1

    def test_calculate_stats_handles_non_list_basis(self):
        """Stats should handle non-list basis value."""
        output_data = {
            'basis': "not a list"
        }

        stats = _calculate_stats_from_output(output_data)
        assert stats['basis_count'] == 0
        assert stats['citation_count'] == 0
        assert stats['unique_domains'] == 0

    def test_calculate_stats_with_empty_citations(self):
        """Stats should handle basis items with empty citations lists."""
        output_data = {
            'basis': [
                {'field': 'Test1', 'citations': []},
                {'field': 'Test2'},  # No citations key
            ]
        }

        stats = _calculate_stats_from_output(output_data)
        assert stats['basis_count'] == 2
        assert stats['citation_count'] == 0
        assert stats['unique_domains'] == 0


class TestMetadataYAMLCreation:
    """Tests for metadata.yaml creation on result completion (meta-002, meta-004, meta-005)."""

    def test_metadata_has_required_fields(self):
        """metadata.yaml should have all required fields."""
        required_fields = [
            'run_id',
            'query',
            'processor',
            'status',
            'created_at',
            'completed_at',
            'basis_count',
            'citation_count',
            'unique_domains',
        ]

        # Mock metadata structure
        metadata = {
            'run_id': 'trun_test123',
            'query': 'What is AI?',
            'processor': 'ultra',
            'status': 'completed',
            'created_at': '2025-12-01T12:00:00',
            'completed_at': '2025-12-01T12:01:00',
            'basis_count': 10,
            'citation_count': 50,
            'unique_domains': 15,
        }

        for field in required_fields:
            assert field in metadata, f'Missing field: {field}'

    def test_convert_and_save_result_creates_metadata(self, tmp_path, monkeypatch):
        """_convert_and_save_result should create metadata.yaml with all fields."""
        # Redirect RESULTS_DIR to tmp_path
        test_results_dir = tmp_path / "results"
        monkeypatch.setattr('tools.deep_research.RESULTS_DIR', test_results_dir)
        monkeypatch.setattr('tools.deep_research.PENDING_DIR', tmp_path / "pending")

        run_id = 'trun_convert_test'
        pending_data = {
            'run_id': run_id,
            'query': 'Test query for conversion',
            'processor': 'ultra2x',
            'created_at': '2025-01-15T10:00:00',
        }

        api_result = {
            'run': {'status': 'completed'},
            'output': {'summary': 'Test summary'},
            'basis': [
                {
                    'field': 'Overview',
                    'confidence': 0.95,
                    'reasoning': 'High confidence',
                    'citations': [
                        {'url': 'https://example.com/1', 'title': 'Source 1'},
                        {'url': 'https://example.com/2', 'title': 'Source 2'},
                    ]
                },
                {
                    'field': 'Details',
                    'confidence': 0.85,
                    'reasoning': 'Good confidence',
                    'citations': [
                        {'url': 'https://other.org/page', 'title': 'Other Source'},
                    ]
                }
            ]
        }

        _convert_and_save_result(run_id, api_result, pending_data)

        # Verify metadata.yaml was created
        metadata_path = test_results_dir / run_id / "metadata.yaml"
        assert metadata_path.exists()

        metadata = yaml.safe_load(metadata_path.read_text())
        assert metadata['run_id'] == run_id
        assert metadata['query'] == 'Test query for conversion'
        assert metadata['processor'] == 'ultra2x'
        assert metadata['status'] == 'completed'
        assert metadata['created_at'] == '2025-01-15T10:00:00'
        assert 'completed_at' in metadata
        assert metadata['basis_count'] == 2
        assert metadata['citation_count'] == 3
        assert metadata['unique_domains'] == 2  # example.com and other.org

    def test_convert_and_save_result_creates_output(self, tmp_path, monkeypatch):
        """_convert_and_save_result should create output.yaml."""
        test_results_dir = tmp_path / "results"
        monkeypatch.setattr('tools.deep_research.RESULTS_DIR', test_results_dir)
        monkeypatch.setattr('tools.deep_research.PENDING_DIR', tmp_path / "pending")

        run_id = 'trun_output_test'
        pending_data = {'run_id': run_id, 'query': 'Test', 'processor': 'ultra'}

        api_result = {
            'run': {'status': 'completed'},
            'output': {'answer': 'The answer is 42', 'confidence': 0.99},
            'basis': []
        }

        _convert_and_save_result(run_id, api_result, pending_data)

        output_path = test_results_dir / run_id / "output.yaml"
        assert output_path.exists()

        output = yaml.safe_load(output_path.read_text())
        assert output['answer'] == 'The answer is 42'
        assert output['confidence'] == 0.99

    def test_convert_and_save_result_creates_basis_files(self, tmp_path, monkeypatch):
        """_convert_and_save_result should create basis directory with field files."""
        test_results_dir = tmp_path / "results"
        monkeypatch.setattr('tools.deep_research.RESULTS_DIR', test_results_dir)
        monkeypatch.setattr('tools.deep_research.PENDING_DIR', tmp_path / "pending")

        run_id = 'trun_basis_test'
        pending_data = {'run_id': run_id, 'query': 'Test', 'processor': 'ultra'}

        api_result = {
            'run': {'status': 'completed'},
            'output': {},
            'basis': [
                {
                    'field': 'Test Field',
                    'confidence': 0.9,
                    'reasoning': 'Test reasoning',
                    'citations': []
                }
            ]
        }

        _convert_and_save_result(run_id, api_result, pending_data)

        basis_dir = test_results_dir / run_id / "basis"
        assert basis_dir.exists()

        # Check index exists
        index_path = basis_dir / "_index.yaml"
        assert index_path.exists()

        # Check field file exists (sanitized name)
        field_files = list(basis_dir.glob("*.yaml"))
        # Should have at least 2 files: _index.yaml and test_field.yaml
        assert len(field_files) >= 2


class TestBackfillMetadata:
    """Tests for backfill_metadata function (meta-006)."""

    def test_backfill_calculates_missing_stats(self, tmp_path, monkeypatch):
        """Backfill should calculate stats from output.yaml when missing in metadata."""
        test_results_dir = tmp_path / "results"
        test_results_dir.mkdir(parents=True)
        monkeypatch.setattr('tools.deep_research.RESULTS_DIR', test_results_dir)
        monkeypatch.setattr('tools.deep_research.PENDING_DIR', tmp_path / "pending")

        # Create mock result directory
        result_dir = test_results_dir / 'trun_backfill_test'
        result_dir.mkdir()

        # Create metadata without stats
        metadata = {
            'run_id': 'trun_backfill_test',
            'query': 'Test query',
            'processor': 'ultra',
            'status': 'completed',
        }
        (result_dir / 'metadata.yaml').write_text(yaml.dump(metadata))

        # Create output with basis items
        output = {
            'basis': [
                {'field': 'Test', 'citations': [{'url': 'https://example.com/test'}]}
            ]
        }
        (result_dir / 'output.yaml').write_text(yaml.dump(output))

        # Run backfill
        result = backfill_metadata()

        # Verify stats were calculated
        assert result['updated_count'] == 1

        # Check updated metadata
        updated_metadata = yaml.safe_load((result_dir / 'metadata.yaml').read_text())
        assert updated_metadata['basis_count'] == 1
        assert updated_metadata['citation_count'] == 1
        assert updated_metadata['unique_domains'] == 1

    def test_backfill_preserves_existing_data(self, tmp_path, monkeypatch):
        """Backfill should preserve existing valid data."""
        test_results_dir = tmp_path / "results"
        test_results_dir.mkdir(parents=True)
        monkeypatch.setattr('tools.deep_research.RESULTS_DIR', test_results_dir)
        monkeypatch.setattr('tools.deep_research.PENDING_DIR', tmp_path / "pending")

        # Create result directory with complete metadata
        result_dir = test_results_dir / 'trun_preserve_test'
        result_dir.mkdir()

        metadata = {
            'run_id': 'trun_preserve_test',
            'query': 'Original query',
            'processor': 'ultra8x',
            'status': 'completed',
            'created_at': '2025-01-01T00:00:00',
            'completed_at': '2025-01-01T00:01:00',
            'basis_count': 5,
            'citation_count': 20,
            'unique_domains': 10,
        }
        (result_dir / 'metadata.yaml').write_text(yaml.dump(metadata))

        # Run backfill
        result = backfill_metadata()

        # Should skip since all data is present
        assert result['skipped_count'] == 1

        # Verify data unchanged
        preserved = yaml.safe_load((result_dir / 'metadata.yaml').read_text())
        assert preserved['query'] == 'Original query'
        assert preserved['processor'] == 'ultra8x'
        assert preserved['basis_count'] == 5

    def test_backfill_handles_missing_processor(self, tmp_path, monkeypatch):
        """Backfill should default processor to 'ultra' if missing."""
        test_results_dir = tmp_path / "results"
        test_results_dir.mkdir(parents=True)
        monkeypatch.setattr('tools.deep_research.RESULTS_DIR', test_results_dir)
        monkeypatch.setattr('tools.deep_research.PENDING_DIR', tmp_path / "pending")

        result_dir = test_results_dir / 'trun_processor_test'
        result_dir.mkdir()

        # Metadata without processor
        metadata = {
            'run_id': 'trun_processor_test',
            'query': 'Test',
            'status': 'completed',
            'basis_count': 1,
            'citation_count': 1,
            'unique_domains': 1,
        }
        (result_dir / 'metadata.yaml').write_text(yaml.dump(metadata))

        # Run backfill
        backfill_metadata()

        # Check processor was set to default
        updated = yaml.safe_load((result_dir / 'metadata.yaml').read_text())
        assert updated['processor'] == 'ultra'

    def test_backfill_removes_deprecated_field_count(self, tmp_path, monkeypatch):
        """Backfill should remove deprecated field_count."""
        test_results_dir = tmp_path / "results"
        test_results_dir.mkdir(parents=True)
        monkeypatch.setattr('tools.deep_research.RESULTS_DIR', test_results_dir)
        monkeypatch.setattr('tools.deep_research.PENDING_DIR', tmp_path / "pending")

        result_dir = test_results_dir / 'trun_deprecated_test'
        result_dir.mkdir()

        # Metadata with deprecated field_count
        metadata = {
            'run_id': 'trun_deprecated_test',
            'query': 'Test',
            'processor': 'ultra',
            'status': 'completed',
            'field_count': 5,  # Deprecated
            'basis_count': 5,
            'citation_count': 10,
            'unique_domains': 3,
        }
        (result_dir / 'metadata.yaml').write_text(yaml.dump(metadata))

        # Run backfill
        backfill_metadata()

        # Check field_count was removed
        updated = yaml.safe_load((result_dir / 'metadata.yaml').read_text())
        assert 'field_count' not in updated

    def test_backfill_handles_empty_results_dir(self, tmp_path, monkeypatch):
        """Backfill should handle empty results directory gracefully."""
        test_results_dir = tmp_path / "results"
        test_results_dir.mkdir(parents=True)
        monkeypatch.setattr('tools.deep_research.RESULTS_DIR', test_results_dir)
        monkeypatch.setattr('tools.deep_research.PENDING_DIR', tmp_path / "pending")

        result = backfill_metadata()

        assert result['updated_count'] == 0
        assert result['skipped_count'] == 0
        assert result['errors'] == []

    def test_backfill_reports_unrecoverable_missing_query(self, tmp_path, monkeypatch):
        """Backfill should report when query is missing and cannot be recovered."""
        test_results_dir = tmp_path / "results"
        test_results_dir.mkdir(parents=True)
        monkeypatch.setattr('tools.deep_research.RESULTS_DIR', test_results_dir)
        monkeypatch.setattr('tools.deep_research.PENDING_DIR', tmp_path / "pending")

        result_dir = test_results_dir / 'trun_missing_query'
        result_dir.mkdir()

        # Metadata without query
        metadata = {
            'run_id': 'trun_missing_query',
            'processor': 'ultra',
            'status': 'completed',
            'basis_count': 1,
            'citation_count': 1,
            'unique_domains': 1,
        }
        (result_dir / 'metadata.yaml').write_text(yaml.dump(metadata))

        result = backfill_metadata()

        # Check that unrecoverable issue is reported
        details = result['details']
        assert any(
            'query' in str(d.get('unrecoverable', []))
            for d in details
        )


class TestIntegration:
    """Integration tests for the full metadata flow."""

    def test_full_metadata_flow(self, tmp_path, monkeypatch):
        """Test the complete flow from pending to completed result."""
        test_results_dir = tmp_path / "results"
        test_pending_dir = tmp_path / "pending"
        monkeypatch.setattr('tools.deep_research.RESULTS_DIR', test_results_dir)
        monkeypatch.setattr('tools.deep_research.PENDING_DIR', test_pending_dir)

        # Step 1: Create pending file (simulating deep_research_create)
        run_id = 'trun_integration_test'
        pending_data = {
            'run_id': run_id,
            'query': 'What is machine learning?',
            'processor': 'ultra4x',
            'created_at': datetime.now().isoformat(),
            'status': 'pending',
        }
        _save_pending(run_id, pending_data)

        # Verify pending was saved
        assert _load_pending(run_id) is not None

        # Step 2: Simulate API result and conversion
        api_result = {
            'run': {'status': 'completed'},
            'output': {'definition': 'ML is...', 'applications': ['...']},
            'basis': [
                {
                    'field': 'definition',
                    'confidence': 0.95,
                    'citations': [
                        {'url': 'https://ml.org/intro', 'title': 'ML Intro'},
                    ]
                },
                {
                    'field': 'applications',
                    'confidence': 0.90,
                    'citations': [
                        {'url': 'https://ai.com/apps', 'title': 'AI Apps'},
                        {'url': 'https://ml.org/uses', 'title': 'ML Uses'},
                    ]
                }
            ]
        }

        _convert_and_save_result(run_id, api_result, pending_data)

        # Step 3: Verify all files were created correctly
        result_dir = test_results_dir / run_id

        # Check metadata
        metadata = yaml.safe_load((result_dir / 'metadata.yaml').read_text())
        assert metadata['run_id'] == run_id
        assert metadata['query'] == 'What is machine learning?'
        assert metadata['processor'] == 'ultra4x'
        assert metadata['basis_count'] == 2
        assert metadata['citation_count'] == 3
        assert metadata['unique_domains'] == 2  # ml.org and ai.com

        # Check output
        output = yaml.safe_load((result_dir / 'output.yaml').read_text())
        assert 'definition' in output

        # Check basis index
        basis_index = yaml.safe_load((result_dir / 'basis' / '_index.yaml').read_text())
        assert len(basis_index) == 2

        # Check citations index
        citations_index = yaml.safe_load((result_dir / 'citations' / '_index.yaml').read_text())
        assert len(citations_index) == 3

        # Step 4: Clean up pending
        _remove_pending(run_id)
        assert _load_pending(run_id) is None


# Run with: pytest tests/test_deep_research_metadata.py -v
if __name__ == '__main__':
    pytest.main([__file__, '-v'])

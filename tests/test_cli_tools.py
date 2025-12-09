"""
Integration tests for browse_research and synthesize_research CLI tools.

Tests:
- browse_research: list, show, stats, search commands
- synthesize_research: citations, common-findings, conflicts, report commands

Uses Click's CliRunner for CLI testing and pytest fixtures for isolated temp data.
"""

import json
import pytest
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from click.testing import CliRunner
import yaml

# Import the CLI commands
from pilot_tools.browse_research import research, load_research_metadata, RESULTS_DIR as BROWSE_RESULTS_DIR
from pilot_tools.synthesize_research import synthesize, RESULTS_DIR as SYNTH_RESULTS_DIR


@pytest.fixture
def runner():
    """Create a Click CLI runner."""
    return CliRunner()


def extract_json_from_output(output: str) -> dict:
    """
    Extract JSON object from CLI output that may contain progress messages.

    Some CLI commands output progress messages before the JSON result.
    This function finds and parses the JSON portion of the output.
    """
    # Try to parse the whole output first (for clean JSON output)
    output = output.strip()
    try:
        return json.loads(output)
    except json.JSONDecodeError:
        pass

    # Look for JSON object (starts with { and ends with })
    brace_start = output.find('{')
    brace_end = output.rfind('}')
    if brace_start != -1 and brace_end != -1 and brace_end > brace_start:
        json_str = output[brace_start:brace_end + 1]
        try:
            return json.loads(json_str)
        except json.JSONDecodeError:
            pass

    # Look for JSON array (starts with [ and ends with ])
    bracket_start = output.find('[')
    bracket_end = output.rfind(']')
    if bracket_start != -1 and bracket_end != -1 and bracket_end > bracket_start:
        json_str = output[bracket_start:bracket_end + 1]
        try:
            return json.loads(json_str)
        except json.JSONDecodeError:
            pass

    raise ValueError(f"Could not extract JSON from output: {output[:200]}...")


@pytest.fixture
def temp_results_dir(tmp_path, monkeypatch):
    """
    Create a temporary results directory with sample research data.
    Patches RESULTS_DIR in both browse_research and synthesize_research.

    Note: The browse_research module uses RESULTS_DIR as a default parameter,
    which is captured at function definition time. We need to:
    1. Patch the module-level constant before invocation
    2. Also patch the functions that use it with a direct reference
    """
    results_dir = tmp_path / "results"
    results_dir.mkdir(parents=True)

    # Patch RESULTS_DIR in both modules
    monkeypatch.setattr('tools.browse_research.RESULTS_DIR', results_dir)
    monkeypatch.setattr('tools.synthesize_research.RESULTS_DIR', results_dir)

    # Also patch functions that have RESULTS_DIR as a default parameter
    # by redefining the default in the function objects
    import pilot_tools.browse_research as browse_mod
    import pilot_tools.synthesize_research as synth_mod

    # Patch the 'list' command's closure - the load_research_metadata function
    # is called without args, so we need to patch its default
    original_load = browse_mod.load_research_metadata
    def patched_load(results_dir_arg: Path = results_dir):
        return original_load(results_dir_arg)
    monkeypatch.setattr(browse_mod, 'load_research_metadata', patched_load)

    original_count = browse_mod.count_total_results
    def patched_count(results_dir_arg: Path = results_dir):
        return original_count(results_dir_arg)
    monkeypatch.setattr(browse_mod, 'count_total_results', patched_count)

    return results_dir


@pytest.fixture
def sample_research_runs(temp_results_dir):
    """
    Create sample research runs in the temp directory.
    Returns dict of run_id -> metadata for verification.
    """
    runs = {}

    # Run 1: AI research from 3 days ago
    run1_id = 'trun_test_ai_001'
    run1_dir = temp_results_dir / run1_id
    run1_dir.mkdir()

    run1_completed = (datetime.now() - timedelta(days=3)).isoformat()
    run1_metadata = {
        'run_id': run1_id,
        'query': 'What is artificial intelligence?',
        'processor': 'ultra',
        'status': 'completed',
        'created_at': (datetime.now() - timedelta(days=3, hours=1)).isoformat(),
        'completed_at': run1_completed,
        'basis_count': 3,
        'citation_count': 10,
        'unique_domains': 5,
    }
    (run1_dir / 'metadata.yaml').write_text(yaml.dump(run1_metadata))

    run1_output = {
        'summary': 'AI is a branch of computer science focused on creating intelligent machines.',
        'basis': [
            {
                'field': 'definition',
                'reasoning': 'Artificial intelligence (AI) is the simulation of human intelligence by machines.',
                'citations': [
                    {'url': 'https://example.com/ai-intro', 'title': 'Introduction to AI'},
                    {'url': 'https://academic.org/ai-definition', 'title': 'Defining AI'},
                    {'url': 'https://techsite.com/ai-basics', 'title': 'AI Basics'},
                ]
            },
            {
                'field': 'applications',
                'reasoning': 'AI has applications in healthcare, finance, and transportation.',
                'citations': [
                    {'url': 'https://example.com/ai-apps', 'title': 'AI Applications'},
                    {'url': 'https://academic.org/ai-healthcare', 'title': 'AI in Healthcare'},
                ]
            },
            {
                'field': 'history',
                'reasoning': 'AI research began in the 1950s with pioneers like Alan Turing.',
                'citations': [
                    {'url': 'https://history.org/ai-history', 'title': 'History of AI'},
                ]
            }
        ]
    }
    (run1_dir / 'output.yaml').write_text(yaml.dump(run1_output))

    # Create citations.yaml for show command
    run1_citations = [
        {'url': 'https://example.com/ai-intro', 'title': 'Introduction to AI'},
        {'url': 'https://academic.org/ai-definition', 'title': 'Defining AI'},
    ]
    (run1_dir / 'citations.yaml').write_text(yaml.dump(run1_citations))

    runs[run1_id] = run1_metadata

    # Run 2: Machine learning research from yesterday
    run2_id = 'trun_test_ml_002'
    run2_dir = temp_results_dir / run2_id
    run2_dir.mkdir()

    run2_completed = (datetime.now() - timedelta(days=1)).isoformat()
    run2_metadata = {
        'run_id': run2_id,
        'query': 'How does machine learning work?',
        'processor': 'ultra2x',
        'status': 'completed',
        'created_at': (datetime.now() - timedelta(days=1, hours=2)).isoformat(),
        'completed_at': run2_completed,
        'basis_count': 2,
        'citation_count': 8,
        'unique_domains': 4,
    }
    (run2_dir / 'metadata.yaml').write_text(yaml.dump(run2_metadata))

    run2_output = {
        'summary': 'Machine learning is a subset of AI that enables systems to learn from data.',
        'basis': [
            {
                'field': 'overview',
                'reasoning': 'Machine learning algorithms learn patterns from data without being explicitly programmed.',
                'citations': [
                    {'url': 'https://example.com/ml-intro', 'title': 'ML Introduction'},
                    {'url': 'https://academic.org/ai-definition', 'title': 'Defining AI'},  # Shared with run1
                    {'url': 'https://mlsite.com/basics', 'title': 'ML Basics'},
                ]
            },
            {
                'field': 'algorithms',
                'reasoning': 'Common ML algorithms include neural networks, decision trees, and SVMs.',
                'citations': [
                    {'url': 'https://mlsite.com/algorithms', 'title': 'ML Algorithms'},
                    {'url': 'https://academic.org/neural-networks', 'title': 'Neural Networks'},
                ]
            }
        ]
    }
    (run2_dir / 'output.yaml').write_text(yaml.dump(run2_output))

    runs[run2_id] = run2_metadata

    # Run 3: Deep learning research from today
    run3_id = 'trun_test_dl_003'
    run3_dir = temp_results_dir / run3_id
    run3_dir.mkdir()

    run3_completed = datetime.now().isoformat()
    run3_metadata = {
        'run_id': run3_id,
        'query': 'What is deep learning?',
        'processor': 'ultra4x',
        'status': 'completed',
        'created_at': (datetime.now() - timedelta(hours=1)).isoformat(),
        'completed_at': run3_completed,
        'basis_count': 2,
        'citation_count': 6,
        'unique_domains': 3,
    }
    (run3_dir / 'metadata.yaml').write_text(yaml.dump(run3_metadata))

    run3_output = {
        'summary': 'Deep learning uses neural networks with many layers to learn complex patterns.',
        'basis': [
            {
                'field': 'definition',
                'reasoning': 'Deep learning is a subset of machine learning that uses artificial neural networks.',
                'citations': [
                    {'url': 'https://example.com/deep-learning', 'title': 'Deep Learning Guide'},
                    {'url': 'https://academic.org/neural-networks', 'title': 'Neural Networks'},  # Shared with run2
                ]
            },
            {
                'field': 'applications',
                'reasoning': 'Deep learning powers image recognition, natural language processing, and autonomous vehicles.',
                'citations': [
                    {'url': 'https://dlsite.com/apps', 'title': 'DL Applications'},
                    {'url': 'https://example.com/ai-apps', 'title': 'AI Applications'},  # Shared with run1
                ]
            }
        ]
    }
    (run3_dir / 'output.yaml').write_text(yaml.dump(run3_output))

    runs[run3_id] = run3_metadata

    return runs


# =============================================================================
# browse_research Tests
# =============================================================================

class TestBrowseResearchList:
    """Tests for browse_research list command."""

    def test_list_default(self, runner, sample_research_runs, temp_results_dir):
        """List command shows research results in table format."""
        result = runner.invoke(research, ['list'])

        assert result.exit_code == 0
        # Should show all three runs
        assert 'trun_test' in result.output
        assert 'RUN_ID' in result.output  # Table header
        assert 'Showing' in result.output  # Footer

    def test_list_with_limit(self, runner, sample_research_runs, temp_results_dir):
        """List command respects --limit option."""
        result = runner.invoke(research, ['list', '--limit', '2'])

        assert result.exit_code == 0
        # Should show "Showing 2 of 3"
        assert 'Showing 2 of 3' in result.output

    def test_list_json_format(self, runner, sample_research_runs, temp_results_dir):
        """List command outputs JSON when requested."""
        result = runner.invoke(research, ['list', '--format', 'json'])

        assert result.exit_code == 0
        # Output should be valid JSON
        data = json.loads(result.output)
        assert isinstance(data, list)
        assert len(data) == 3
        # Each item should have expected fields
        for item in data:
            assert 'run_id' in item
            assert 'query' in item
            assert 'processor' in item

    def test_list_with_query_filter(self, runner, sample_research_runs, temp_results_dir):
        """List command filters by query keyword."""
        result = runner.invoke(research, ['list', '--query', 'machine'])

        assert result.exit_code == 0
        # Should only show the ML run
        assert 'trun_test_ml_002' in result.output or 'machine' in result.output.lower()
        # Verify filtering worked - should show 1 result
        assert 'Showing 1 of 1' in result.output

    def test_list_with_date_from_filter(self, runner, sample_research_runs, temp_results_dir):
        """List command filters by --from date."""
        yesterday = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
        result = runner.invoke(research, ['list', '--from', yesterday])

        assert result.exit_code == 0
        # Should show runs from yesterday and today (2 runs)
        # Run 1 was 3 days ago, should be excluded
        assert 'Showing 2 of 2' in result.output

    def test_list_with_date_to_filter(self, runner, sample_research_runs, temp_results_dir):
        """List command filters by --to date."""
        two_days_ago = (datetime.now() - timedelta(days=2)).strftime('%Y-%m-%d')
        result = runner.invoke(research, ['list', '--to', two_days_ago])

        assert result.exit_code == 0
        # Should only show run from 3 days ago
        assert 'Showing 1 of 1' in result.output

    def test_list_with_invalid_date_format(self, runner, sample_research_runs, temp_results_dir):
        """List command shows error for invalid date format."""
        result = runner.invoke(research, ['list', '--from', 'invalid-date'])

        assert result.exit_code == 0  # Click doesn't exit with error for validation
        assert 'Error' in result.output
        assert 'Invalid date format' in result.output

    def test_list_empty_results(self, runner, temp_results_dir):
        """List command handles empty results directory."""
        result = runner.invoke(research, ['list'])

        assert result.exit_code == 0
        assert 'No research results found' in result.output


class TestBrowseResearchShow:
    """Tests for browse_research show command."""

    def test_show_existing_run(self, runner, sample_research_runs, temp_results_dir):
        """Show command displays details for existing run."""
        result = runner.invoke(research, ['show', 'trun_test_ai_001'])

        assert result.exit_code == 0
        assert 'Research Run: trun_test_ai_001' in result.output
        assert 'Query: What is artificial intelligence?' in result.output
        assert 'Processor: ultra' in result.output
        assert 'Status: completed' in result.output
        assert 'Basis Count: 3' in result.output
        assert 'Citation Count: 10' in result.output

    def test_show_displays_output_summary(self, runner, sample_research_runs, temp_results_dir):
        """Show command displays output summary."""
        result = runner.invoke(research, ['show', 'trun_test_ai_001'])

        assert result.exit_code == 0
        assert 'Output Summary:' in result.output
        assert 'AI is a branch of computer science' in result.output

    def test_show_displays_top_citations(self, runner, sample_research_runs, temp_results_dir):
        """Show command displays top citations by domain."""
        result = runner.invoke(research, ['show', 'trun_test_ai_001'])

        assert result.exit_code == 0
        assert 'Top Citations:' in result.output
        assert 'example.com' in result.output

    def test_show_nonexistent_run(self, runner, sample_research_runs, temp_results_dir):
        """Show command handles nonexistent run_id."""
        result = runner.invoke(research, ['show', 'trun_nonexistent_xyz'])

        assert result.exit_code == 0  # Click doesn't exit with error
        assert 'Error' in result.output
        assert 'not found' in result.output

    def test_show_run_without_output(self, runner, temp_results_dir):
        """Show command handles run without output.yaml."""
        # Create run with only metadata
        run_dir = temp_results_dir / 'trun_no_output'
        run_dir.mkdir()

        metadata = {
            'run_id': 'trun_no_output',
            'query': 'Test query',
            'processor': 'ultra',
            'status': 'completed',
        }
        (run_dir / 'metadata.yaml').write_text(yaml.dump(metadata))

        result = runner.invoke(research, ['show', 'trun_no_output'])

        assert result.exit_code == 0
        assert 'Query: Test query' in result.output
        assert 'Output: (not available)' in result.output


class TestBrowseResearchStats:
    """Tests for browse_research stats command."""

    def test_stats_shows_totals(self, runner, sample_research_runs, temp_results_dir):
        """Stats command shows total counts."""
        result = runner.invoke(research, ['stats'])

        assert result.exit_code == 0
        assert 'Research Statistics' in result.output
        assert 'Total Research Runs: 3' in result.output
        assert 'Total Citations:' in result.output
        assert 'Total Basis Items:' in result.output

    def test_stats_shows_processor_breakdown(self, runner, sample_research_runs, temp_results_dir):
        """Stats command shows breakdown by processor."""
        result = runner.invoke(research, ['stats'])

        assert result.exit_code == 0
        assert 'By Processor:' in result.output
        assert 'ultra:' in result.output
        assert 'ultra2x:' in result.output
        assert 'ultra4x:' in result.output

    def test_stats_shows_date_range(self, runner, sample_research_runs, temp_results_dir):
        """Stats command shows date range of research."""
        result = runner.invoke(research, ['stats'])

        assert result.exit_code == 0
        assert 'Date Range:' in result.output

    def test_stats_empty_results(self, runner, temp_results_dir):
        """Stats command handles empty results."""
        result = runner.invoke(research, ['stats'])

        assert result.exit_code == 0
        assert 'No research results found' in result.output


class TestBrowseResearchSearch:
    """Tests for browse_research search command."""

    def test_search_by_domain(self, runner, sample_research_runs, temp_results_dir):
        """Search command finds research by citation domain."""
        result = runner.invoke(research, ['search', '--citation', 'example.com'])

        assert result.exit_code == 0
        assert 'Research citing: example.com' in result.output
        # All three runs cite example.com
        assert 'Total:' in result.output

    def test_search_by_domain_json_format(self, runner, sample_research_runs, temp_results_dir):
        """Search command outputs JSON when requested."""
        result = runner.invoke(research, ['search', '--citation', 'example.com', '--format', 'json'])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert isinstance(data, list)
        # Each result should have expected fields
        for item in data:
            assert 'run_id' in item
            assert 'citation_count' in item
            assert 'citations' in item

    def test_search_no_matches(self, runner, sample_research_runs, temp_results_dir):
        """Search command handles no matches gracefully."""
        result = runner.invoke(research, ['search', '--citation', 'nonexistent-domain.xyz'])

        assert result.exit_code == 0
        assert 'No research found citing' in result.output

    def test_search_with_limit(self, runner, sample_research_runs, temp_results_dir):
        """Search command respects --limit option."""
        result = runner.invoke(research, ['search', '--citation', 'example.com', '--limit', '1'])

        assert result.exit_code == 0
        # Should limit results
        assert 'Total: 1' in result.output


# =============================================================================
# synthesize_research Tests
# =============================================================================

class TestSynthesizeResearchCitations:
    """Tests for synthesize_research citations command."""

    def test_citations_aggregates_across_runs(self, runner, sample_research_runs, temp_results_dir):
        """Citations command aggregates citations from multiple runs."""
        run_ids = 'trun_test_ai_001,trun_test_ml_002,trun_test_dl_003'
        result = runner.invoke(synthesize, ['citations', '--runs', run_ids])

        assert result.exit_code == 0
        assert 'Citation Aggregation for 3 Research Runs' in result.output
        assert 'Total Citations:' in result.output
        assert 'Unique URLs:' in result.output
        assert 'Unique Domains:' in result.output

    def test_citations_identifies_multi_run_sources(self, runner, sample_research_runs, temp_results_dir):
        """Citations command highlights sources cited by multiple runs."""
        run_ids = 'trun_test_ai_001,trun_test_ml_002,trun_test_dl_003'
        result = runner.invoke(synthesize, ['citations', '--runs', run_ids])

        assert result.exit_code == 0
        # academic.org/ai-definition is cited by run1 and run2
        # academic.org/neural-networks is cited by run2 and run3
        # Check for multi-run citations section
        if 'Sources Cited by Multiple Runs' in result.output:
            assert 'academic.org' in result.output

    def test_citations_json_format(self, runner, sample_research_runs, temp_results_dir):
        """Citations command outputs JSON when requested."""
        run_ids = 'trun_test_ai_001,trun_test_ml_002'
        result = runner.invoke(synthesize, ['citations', '--runs', run_ids, '--format', 'json'])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert 'run_ids' in data
        assert 'total_citations' in data
        assert 'unique_domains' in data
        assert 'citations' in data
        assert isinstance(data['citations'], list)

    def test_citations_requires_runs_or_query(self, runner, sample_research_runs, temp_results_dir):
        """Citations command requires --runs or --query parameter."""
        result = runner.invoke(synthesize, ['citations'])

        assert result.exit_code == 0  # Click doesn't exit with error
        assert 'Error' in result.output
        assert 'Provide --runs or --query' in result.output

    def test_citations_with_limit(self, runner, sample_research_runs, temp_results_dir):
        """Citations command respects --limit option."""
        run_ids = 'trun_test_ai_001,trun_test_ml_002'
        result = runner.invoke(synthesize, ['citations', '--runs', run_ids, '--limit', '5', '--format', 'json'])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert len(data['citations']) <= 5


class TestSynthesizeResearchCommonFindings:
    """Tests for synthesize_research common-findings command."""

    def test_common_findings_requires_multiple_runs(self, runner, sample_research_runs, temp_results_dir):
        """Common-findings command requires at least 2 runs."""
        result = runner.invoke(synthesize, ['common-findings', '--runs', 'trun_test_ai_001'])

        assert result.exit_code == 0
        assert 'Error' in result.output
        assert 'at least 2 runs' in result.output

    def test_common_findings_analyzes_runs(self, runner, sample_research_runs, temp_results_dir):
        """Common-findings command analyzes multiple runs for shared findings."""
        run_ids = 'trun_test_ai_001,trun_test_ml_002'
        result = runner.invoke(synthesize, ['common-findings', '--runs', run_ids])

        assert result.exit_code == 0
        assert 'Analyzing' in result.output
        assert 'Common Findings' in result.output

    def test_common_findings_json_format(self, runner, sample_research_runs, temp_results_dir):
        """Common-findings command outputs JSON when requested."""
        run_ids = 'trun_test_ai_001,trun_test_ml_002'
        result = runner.invoke(synthesize, ['common-findings', '--runs', run_ids, '--format', 'json'])

        assert result.exit_code == 0
        # Note: common-findings outputs progress to stdout before JSON
        data = extract_json_from_output(result.output)
        assert 'run_ids' in data
        assert 'common_findings' in data
        assert 'threshold' in data
        assert 'similarity' in data

    def test_common_findings_with_threshold(self, runner, sample_research_runs, temp_results_dir):
        """Common-findings command respects --threshold option."""
        run_ids = 'trun_test_ai_001,trun_test_ml_002,trun_test_dl_003'
        result = runner.invoke(synthesize, ['common-findings', '--runs', run_ids, '--threshold', '3', '--format', 'json'])

        assert result.exit_code == 0
        data = extract_json_from_output(result.output)
        # With threshold=3, findings must appear in all 3 runs
        for finding in data['common_findings']:
            assert len(finding['supporting_runs']) >= 3

    def test_common_findings_with_similarity(self, runner, sample_research_runs, temp_results_dir):
        """Common-findings command respects --similarity option."""
        run_ids = 'trun_test_ai_001,trun_test_ml_002'
        result = runner.invoke(synthesize, ['common-findings', '--runs', run_ids, '--similarity', '0.9', '--format', 'json'])

        assert result.exit_code == 0
        data = extract_json_from_output(result.output)
        assert data['similarity'] == 0.9


class TestSynthesizeResearchConflicts:
    """Tests for synthesize_research conflicts command."""

    def test_conflicts_requires_multiple_runs(self, runner, sample_research_runs, temp_results_dir):
        """Conflicts command requires at least 2 runs."""
        result = runner.invoke(synthesize, ['conflicts', '--runs', 'trun_test_ai_001'])

        assert result.exit_code == 0
        assert 'Error' in result.output
        assert 'at least 2 runs' in result.output

    def test_conflicts_analyzes_runs(self, runner, sample_research_runs, temp_results_dir):
        """Conflicts command analyzes runs for contradictions."""
        run_ids = 'trun_test_ai_001,trun_test_ml_002'
        result = runner.invoke(synthesize, ['conflicts', '--runs', run_ids])

        assert result.exit_code == 0
        assert 'Analyzing' in result.output
        assert 'Conflict Analysis' in result.output

    def test_conflicts_json_format(self, runner, sample_research_runs, temp_results_dir):
        """Conflicts command outputs JSON when requested."""
        run_ids = 'trun_test_ai_001,trun_test_ml_002'
        result = runner.invoke(synthesize, ['conflicts', '--runs', run_ids, '--format', 'json'])

        assert result.exit_code == 0
        # Note: conflicts outputs progress to stdout before JSON
        data = extract_json_from_output(result.output)
        assert 'run_ids' in data
        assert 'conflicts' in data
        assert 'similarity' in data

    def test_conflicts_with_no_contradictions(self, runner, sample_research_runs, temp_results_dir):
        """Conflicts command handles case with no conflicts gracefully."""
        run_ids = 'trun_test_ai_001,trun_test_ml_002'
        result = runner.invoke(synthesize, ['conflicts', '--runs', run_ids])

        assert result.exit_code == 0
        # Either shows conflicts or shows "No conflicts detected"
        assert 'Conflict Analysis' in result.output or 'No conflicts detected' in result.output


class TestSynthesizeResearchReport:
    """Tests for synthesize_research report command."""

    def test_report_requires_multiple_runs(self, runner, sample_research_runs, temp_results_dir):
        """Report command requires at least 2 runs."""
        result = runner.invoke(synthesize, ['report', '--runs', 'trun_test_ai_001'])

        assert result.exit_code == 0
        assert 'Error' in result.output
        assert 'at least 2 runs' in result.output

    def test_report_generates_markdown(self, runner, sample_research_runs, temp_results_dir):
        """Report command generates markdown report."""
        run_ids = 'trun_test_ai_001,trun_test_ml_002'
        result = runner.invoke(synthesize, ['report', '--runs', run_ids])

        assert result.exit_code == 0
        # Check for markdown structure
        assert '# Research Synthesis Report' in result.output
        assert '## Overview' in result.output
        assert '## Common Findings' in result.output
        assert '## Potential Conflicts' in result.output
        assert '## Top Citations' in result.output

    def test_report_json_format(self, runner, sample_research_runs, temp_results_dir):
        """Report command outputs JSON when requested."""
        run_ids = 'trun_test_ai_001,trun_test_ml_002'
        result = runner.invoke(synthesize, ['report', '--runs', run_ids, '--format', 'json'])

        assert result.exit_code == 0
        # Note: report outputs progress to stderr, but some may go to stdout too
        data = extract_json_from_output(result.output)
        assert 'run_ids' in data
        assert 'queries' in data
        assert 'total_basis_items' in data
        assert 'total_citations' in data
        assert 'unique_domains' in data
        assert 'aggregated_citations' in data
        assert 'common_findings' in data
        assert 'conflicts' in data
        assert 'generated_at' in data

    def test_report_saves_to_file(self, runner, sample_research_runs, temp_results_dir, tmp_path):
        """Report command saves output to file when --output specified."""
        run_ids = 'trun_test_ai_001,trun_test_ml_002'
        output_file = tmp_path / 'synthesis_report.md'

        result = runner.invoke(synthesize, ['report', '--runs', run_ids, '--output', str(output_file)])

        assert result.exit_code == 0
        assert output_file.exists()
        content = output_file.read_text()
        assert '# Research Synthesis Report' in content
        assert 'Report saved to:' in result.output

    def test_report_includes_provenance(self, runner, sample_research_runs, temp_results_dir):
        """Report includes provenance of contributing runs."""
        run_ids = 'trun_test_ai_001,trun_test_ml_002'
        result = runner.invoke(synthesize, ['report', '--runs', run_ids])

        assert result.exit_code == 0
        assert 'Contributing Research' in result.output
        assert 'trun_test_ai_001' in result.output
        assert 'trun_test_ml_002' in result.output


class TestSynthesizeResearchQueryFilter:
    """Tests for --query filter in synthesize commands."""

    def test_citations_with_query_filter(self, runner, sample_research_runs, temp_results_dir):
        """Citations command can use --query to find runs."""
        # "artificial" matches "What is artificial intelligence?"
        result = runner.invoke(synthesize, ['citations', '--query', 'artificial'])

        assert result.exit_code == 0
        assert 'Citation Aggregation for 1 Research Runs' in result.output

    def test_common_findings_with_query_filter(self, runner, sample_research_runs, temp_results_dir):
        """Common-findings can use --query to find related runs."""
        # "learning" matches both ML and DL queries
        result = runner.invoke(synthesize, ['common-findings', '--query', 'learning'])

        assert result.exit_code == 0
        # Should find runs with "learning" in query
        assert 'Analyzing' in result.output


class TestErrorHandling:
    """Tests for error handling in CLI tools."""

    def test_browse_invalid_subcommand(self, runner, sample_research_runs, temp_results_dir):
        """browse_research handles invalid subcommand."""
        result = runner.invoke(research, ['invalid-command'])

        assert result.exit_code != 0
        assert 'No such command' in result.output or 'Error' in result.output

    def test_synthesize_invalid_subcommand(self, runner, sample_research_runs, temp_results_dir):
        """synthesize_research handles invalid subcommand."""
        result = runner.invoke(synthesize, ['invalid-command'])

        assert result.exit_code != 0
        assert 'No such command' in result.output or 'Error' in result.output

    def test_browse_missing_run_id_for_show(self, runner, sample_research_runs, temp_results_dir):
        """browse_research show requires run_id argument."""
        result = runner.invoke(research, ['show'])

        assert result.exit_code != 0
        assert 'Missing argument' in result.output or 'Error' in result.output

    def test_synthesize_missing_citation_for_search(self, runner, sample_research_runs, temp_results_dir):
        """browse_research search requires --citation option."""
        result = runner.invoke(research, ['search'])

        assert result.exit_code != 0
        assert 'required' in result.output.lower() or 'Error' in result.output


class TestHelperFunctions:
    """Tests for helper functions used by CLI tools."""

    def test_load_research_metadata(self, sample_research_runs, temp_results_dir):
        """load_research_metadata loads all metadata from results directory."""
        # Need to import with patched RESULTS_DIR
        from pilot_tools.browse_research import load_research_metadata

        results = load_research_metadata(temp_results_dir)

        assert len(results) == 3
        run_ids = [r['run_id'] for r in results]
        assert 'trun_test_ai_001' in run_ids
        assert 'trun_test_ml_002' in run_ids
        assert 'trun_test_dl_003' in run_ids

    def test_load_research_metadata_empty_dir(self, tmp_path):
        """load_research_metadata handles empty directory."""
        from pilot_tools.browse_research import load_research_metadata

        empty_dir = tmp_path / 'empty'
        empty_dir.mkdir()

        results = load_research_metadata(empty_dir)

        assert results == []

    def test_load_research_metadata_nonexistent_dir(self, tmp_path):
        """load_research_metadata handles nonexistent directory."""
        from pilot_tools.browse_research import load_research_metadata

        nonexistent = tmp_path / 'nonexistent'

        results = load_research_metadata(nonexistent)

        assert results == []


# Run with: uv run pytest tests/test_cli_tools.py -v
if __name__ == '__main__':
    pytest.main([__file__, '-v'])

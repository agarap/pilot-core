"""Test detect_task_tool.py enforcement."""

import json
import tempfile
import pytest
from pathlib import Path
from tools.detect_task_tool import detect_task_tool, BANNED_SUBAGENT_TYPES


class TestTaskToolDetection:
    """Test Task tool detection enforcement."""

    def test_detects_task_tool_usage(self, tmp_path):
        """Should detect Task tool in agent logs."""
        agent_dir = tmp_path / "test-agent"
        agent_dir.mkdir()

        log_data = {
            "timestamp": "2024-01-01T00:00:00",
            "output": {
                "tool_uses": [
                    {
                        "tool": "Task",
                        "input": {
                            "subagent_type": "general-purpose",
                            "description": "test",
                            "prompt": "do something"
                        }
                    }
                ]
            }
        }

        log_file = agent_dir / "run_001.json"
        log_file.write_text(json.dumps(log_data))

        result = detect_task_tool(str(tmp_path))
        assert result['violation_count'] == 1
        assert result['violations'][0]['task_type'] == 'general-purpose'

    def test_detects_explore_subagent(self, tmp_path):
        """Should detect Explore subagent type."""
        agent_dir = tmp_path / "test-agent"
        agent_dir.mkdir()

        log_data = {
            "timestamp": "2024-01-01T00:00:00",
            "output": {
                "tool_uses": [
                    {
                        "tool": "Task",
                        "input": {
                            "subagent_type": "Explore",
                            "prompt": "find files"
                        }
                    }
                ]
            }
        }

        log_file = agent_dir / "run_001.json"
        log_file.write_text(json.dumps(log_data))

        result = detect_task_tool(str(tmp_path))
        assert result['violation_count'] == 1

    def test_clean_logs_pass(self, tmp_path):
        """Logs without Task tool should pass."""
        agent_dir = tmp_path / "test-agent"
        agent_dir.mkdir()

        log_data = {
            "timestamp": "2024-01-01T00:00:00",
            "output": {
                "tool_uses": [
                    {
                        "tool": "Read",
                        "input": {"file_path": "/some/file.py"}
                    }
                ]
            }
        }

        log_file = agent_dir / "run_001.json"
        log_file.write_text(json.dumps(log_data))

        result = detect_task_tool(str(tmp_path))
        assert result['violation_count'] == 0

    def test_empty_directory_passes(self, tmp_path):
        """Empty logs directory should pass."""
        result = detect_task_tool(str(tmp_path))
        assert result['violation_count'] == 0

    def test_all_banned_types_defined(self):
        """Ensure BANNED_SUBAGENT_TYPES is not empty."""
        assert len(BANNED_SUBAGENT_TYPES) > 0
        assert 'general-purpose' in BANNED_SUBAGENT_TYPES
        assert 'Explore' in BANNED_SUBAGENT_TYPES
        assert 'Plan' in BANNED_SUBAGENT_TYPES

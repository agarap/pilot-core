"""Tests for pre-commit hook logic (lib/precommit.py)."""

import json
import pytest
from datetime import datetime, timedelta
from pathlib import Path

from lib.precommit import (
    parse_marker,
    is_expired,
    get_diff_hash,
    verify_diff_hash,
    log_bypass,
    is_gitignore_only,
    validate_marker,
    MAX_APPROVAL_AGE_SECONDS,
)


class TestMarkerDetection:
    """Tests for marker parsing and detection."""

    def test_no_marker_blocks_commit(self):
        """Empty content should return empty dict."""
        result = parse_marker("")
        assert result == {}

        result = parse_marker(None)
        assert result == {}

    def test_valid_json_marker_allows_commit(self):
        """Valid JSON marker should parse correctly."""
        marker = {
            "approved_at": "2025-01-01T12:00:00",
            "diff_hash": "abc123def456",
            "verdict": "APPROVED",
            "files": ["file1.py", "file2.py"],
        }
        content = json.dumps(marker)
        result = parse_marker(content)

        assert result["approved_at"] == "2025-01-01T12:00:00"
        assert result["diff_hash"] == "abc123def456"
        assert result["verdict"] == "APPROVED"
        assert result["files"] == ["file1.py", "file2.py"]

    def test_valid_yaml_marker_fallback(self):
        """YAML-like format should parse as fallback."""
        content = """approved_at: 2025-01-01T12:00:00
diff_hash: abc123def456
verdict: APPROVED"""

        result = parse_marker(content)

        assert result["approved_at"] == "2025-01-01T12:00:00"
        assert result["diff_hash"] == "abc123def456"
        assert result["verdict"] == "APPROVED"

    def test_invalid_marker_blocks_commit(self):
        """Invalid content should return empty or partial dict."""
        # Random garbage
        result = parse_marker("this is not a valid marker")
        assert "diff_hash" not in result

        # Missing required fields
        result = parse_marker('{"verdict": "APPROVED"}')
        assert "diff_hash" not in result

    def test_marker_with_whitespace(self):
        """Marker with extra whitespace should parse."""
        content = """
        {
            "approved_at": "2025-01-01T12:00:00",
            "diff_hash": "abc123"
        }
        """
        result = parse_marker(content)
        assert result["diff_hash"] == "abc123"


class TestDiffHash:
    """Tests for diff hash computation and verification."""

    def test_matching_hash_passes(self):
        """Matching hash should verify successfully."""
        test_diff = b"diff content here\n"
        computed_hash = get_diff_hash(test_diff)

        assert verify_diff_hash(computed_hash, test_diff)

    def test_mismatched_hash_blocks_commit(self):
        """Mismatched hash should fail verification."""
        original_diff = b"original diff\n"
        modified_diff = b"modified diff\n"

        original_hash = get_diff_hash(original_diff)

        # Hash from original should not match modified diff
        assert not verify_diff_hash(original_hash, modified_diff)

    def test_empty_hash_fails(self):
        """Empty or None hash should fail verification."""
        assert not verify_diff_hash("", b"some diff")
        assert not verify_diff_hash(None, b"some diff")

    def test_hash_is_deterministic(self):
        """Same diff should always produce same hash."""
        diff = b"consistent content\n"
        hash1 = get_diff_hash(diff)
        hash2 = get_diff_hash(diff)
        assert hash1 == hash2

    def test_hash_format(self):
        """Hash should be valid SHA-256 hex string."""
        diff = b"test content"
        result = get_diff_hash(diff)

        # SHA-256 produces 64 hex characters
        assert len(result) == 64
        assert all(c in "0123456789abcdef" for c in result)


class TestExpiration:
    """Tests for approval expiration logic."""

    def test_recent_approval_passes(self):
        """Recent approval (< 1 hour) should not be expired."""
        recent = datetime.now().isoformat()
        assert not is_expired(recent)

    def test_expired_approval_blocks(self):
        """Old approval (> 1 hour) should be expired."""
        old = (datetime.now() - timedelta(hours=2)).isoformat()
        assert is_expired(old)

    def test_exactly_one_hour_boundary(self):
        """Test behavior at exactly 1 hour boundary."""
        # Just under 1 hour - should pass
        just_under = datetime.now() - timedelta(seconds=MAX_APPROVAL_AGE_SECONDS - 60)
        assert not is_expired(just_under.isoformat())

        # Just over 1 hour - should fail
        just_over = datetime.now() - timedelta(seconds=MAX_APPROVAL_AGE_SECONDS + 60)
        assert is_expired(just_over.isoformat())

    def test_invalid_timestamp_fails_safe(self):
        """Invalid timestamp should be treated as expired (fail-safe)."""
        assert is_expired("not-a-timestamp")
        assert is_expired("")
        assert is_expired(None)

    def test_iso_format_with_z_suffix(self):
        """ISO format with Z suffix should parse."""
        recent = datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ")
        assert not is_expired(recent)

    def test_iso_format_with_microseconds(self):
        """ISO format with microseconds should parse."""
        recent = datetime.now().isoformat()  # Includes microseconds
        assert not is_expired(recent)

    def test_custom_max_age(self):
        """Custom max age should be respected."""
        # 10 minutes ago with 5 minute max - should be expired
        ten_min_ago = (datetime.now() - timedelta(minutes=10)).isoformat()
        assert is_expired(ten_min_ago, max_age_seconds=300)

        # 2 minutes ago with 5 minute max - should not be expired
        two_min_ago = (datetime.now() - timedelta(minutes=2)).isoformat()
        assert not is_expired(two_min_ago, max_age_seconds=300)


class TestBypass:
    """Tests for bypass logging."""

    def test_bypass_with_env_var_logs(self, tmp_path):
        """Bypass should create log file."""
        log_dir = tmp_path / "bypasses"

        log_file = log_bypass(
            reason="PILOT_SKIP_REVIEW environment variable",
            files=["file1.py", "file2.py"],
            log_dir=log_dir,
            user="Test User <test@example.com>",
            branch="main",
        )

        assert log_file.exists()
        content = log_file.read_text()
        assert "PILOT_SKIP_REVIEW" in content
        assert "file1.py" in content

    def test_bypass_log_format(self, tmp_path):
        """Bypass log should have correct YAML-like format."""
        log_dir = tmp_path / "bypasses"

        log_bypass(
            reason="emergency fix",
            files=["urgent.py"],
            log_dir=log_dir,
            user="Dev <dev@test.com>",
            branch="hotfix",
        )

        log_file = list(log_dir.glob("*.log"))[0]
        content = log_file.read_text()

        # Check format
        assert content.startswith("---")
        assert "timestamp:" in content
        assert "reason: emergency fix" in content
        assert "user: Dev <dev@test.com>" in content
        assert "branch: hotfix" in content
        assert "files: urgent.py" in content

    def test_bypass_log_appends(self, tmp_path):
        """Multiple bypasses should append to same day's log."""
        log_dir = tmp_path / "bypasses"

        log_bypass(
            reason="first bypass",
            files=["a.py"],
            log_dir=log_dir,
            user="User1 <u1@test.com>",
            branch="main",
        )

        log_bypass(
            reason="second bypass",
            files=["b.py"],
            log_dir=log_dir,
            user="User2 <u2@test.com>",
            branch="feature",
        )

        log_files = list(log_dir.glob("*.log"))
        assert len(log_files) == 1  # Same day

        content = log_files[0].read_text()
        assert "first bypass" in content
        assert "second bypass" in content

    def test_bypass_creates_directory(self, tmp_path):
        """Bypass should create log directory if it doesn't exist."""
        log_dir = tmp_path / "deeply" / "nested" / "bypasses"
        assert not log_dir.exists()

        log_bypass(
            reason="test",
            files=["test.py"],
            log_dir=log_dir,
            user="Test <t@test.com>",
            branch="main",
        )

        assert log_dir.exists()


class TestGitignoreBypass:
    """Tests for .gitignore-only commit bypass."""

    def test_gitignore_only_commits_skip_review(self):
        """Only .gitignore should bypass review."""
        assert is_gitignore_only([".gitignore"])
        assert is_gitignore_only(["subdir/.gitignore"])
        assert is_gitignore_only([".gitignore", "another/.gitignore"])

    def test_mixed_files_require_review(self):
        """Mixed files should require review."""
        assert not is_gitignore_only([".gitignore", "code.py"])
        assert not is_gitignore_only(["README.md"])
        assert not is_gitignore_only(["src/main.py", ".gitignore"])

    def test_empty_list_requires_review(self):
        """Empty file list should not bypass."""
        assert not is_gitignore_only([])

    def test_similar_filenames_require_review(self):
        """Files that look like .gitignore but aren't should require review."""
        assert not is_gitignore_only([".gitignore.bak"])
        assert not is_gitignore_only(["my.gitignore"])
        assert not is_gitignore_only([".gitignore_global"])


class TestMarkerValidation:
    """Tests for marker validation logic."""

    def test_valid_marker_passes(self):
        """Valid marker with required fields should pass."""
        marker = {"diff_hash": "abc123", "approved_at": "2025-01-01T12:00:00"}
        is_valid, error = validate_marker(marker)
        assert is_valid
        assert error == ""

    def test_missing_diff_hash_fails(self):
        """Marker without diff_hash should fail."""
        marker = {"approved_at": "2025-01-01T12:00:00", "verdict": "APPROVED"}
        is_valid, error = validate_marker(marker)
        assert not is_valid
        assert "diff_hash" in error

    def test_empty_marker_fails(self):
        """Empty marker should fail."""
        is_valid, error = validate_marker({})
        assert not is_valid

        is_valid, error = validate_marker(None)
        assert not is_valid

    def test_empty_diff_hash_fails(self):
        """Marker with empty diff_hash should fail."""
        marker = {"diff_hash": "", "approved_at": "2025-01-01T12:00:00"}
        is_valid, error = validate_marker(marker)
        assert not is_valid

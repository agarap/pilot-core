"""Test scan_web_imports.py enforcement."""

import tempfile
import pytest
from pathlib import Path
from tools.scan_web_imports import scan_web_imports, scan_file, FORBIDDEN_LIBRARIES


class TestWebImportsScanner:
    """Test web import scanning enforcement."""

    def test_detects_import_requests(self, tmp_path):
        """Direct import of requests should be caught."""
        test_file = tmp_path / "bad.py"
        test_file.write_text('import requests\n')
        result = scan_web_imports(str(tmp_path))
        assert result['violation_count'] == 1
        assert result['violations'][0]['library'] == 'requests'

    def test_detects_from_import(self, tmp_path):
        """From import should be caught."""
        test_file = tmp_path / "bad.py"
        test_file.write_text('from requests import get\n')
        result = scan_web_imports(str(tmp_path))
        assert result['violation_count'] == 1

    def test_detects_httpx(self, tmp_path):
        """httpx should be caught."""
        test_file = tmp_path / "bad.py"
        test_file.write_text('import httpx\n')
        result = scan_web_imports(str(tmp_path))
        assert result['violation_count'] == 1
        assert result['violations'][0]['library'] == 'httpx'

    def test_detects_urllib(self, tmp_path):
        """urllib variants should be caught."""
        test_file = tmp_path / "bad.py"
        test_file.write_text('from urllib.request import urlopen\n')
        result = scan_web_imports(str(tmp_path))
        assert result['violation_count'] == 1

    def test_detects_beautifulsoup(self, tmp_path):
        """BeautifulSoup should be caught."""
        test_file = tmp_path / "bad.py"
        test_file.write_text('from bs4 import BeautifulSoup\n')
        result = scan_web_imports(str(tmp_path))
        assert result['violation_count'] == 1

    def test_clean_file_passes(self, tmp_path):
        """Clean file with no forbidden imports passes."""
        test_file = tmp_path / "clean.py"
        test_file.write_text('import json\nimport os\n')
        result = scan_web_imports(str(tmp_path))
        assert result['violation_count'] == 0

    def test_exempted_file_allowed(self, tmp_path):
        """Files in EXEMPTED_FILES should be allowed."""
        # Create exempted file structure
        tools_dir = tmp_path / "tools"
        tools_dir.mkdir()
        web_search = tools_dir / "web_search.py"
        web_search.write_text('import requests\n')  # Would be violation but exempted
        result = scan_web_imports(str(tmp_path))
        # Should pass because web_search.py is exempted
        assert result['violation_count'] == 0

    def test_all_forbidden_libraries_defined(self):
        """Ensure FORBIDDEN_LIBRARIES is not empty."""
        assert len(FORBIDDEN_LIBRARIES) > 0
        assert 'requests' in FORBIDDEN_LIBRARIES
        assert 'httpx' in FORBIDDEN_LIBRARIES

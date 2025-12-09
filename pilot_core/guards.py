"""
Runtime import blocker for forbidden web libraries.

Enforces the web access policy: ALL web access MUST go through Parallel API tools.
This module installs an import hook that blocks direct imports of HTTP clients
and web scraping libraries except from approved tool modules.

Auto-installs on import - just `import pilot_core.guards` to activate protection.
"""

import inspect
import sys
from typing import Optional

# Telemetry import - may fail during early Python startup
# Use a no-op stub if unavailable
try:
    from pilot_core.telemetry import record_event, EventType
    _telemetry_available = True
except ImportError:
    _telemetry_available = False

    def record_event(*args, **kwargs):
        """No-op stub when telemetry is unavailable."""
        pass

# HTTP clients and web scraping libraries that are forbidden
FORBIDDEN_WEB_LIBRARIES: frozenset[str] = frozenset({
    # HTTP clients
    "requests",
    "httpx",
    "urllib",
    "urllib3",
    "aiohttp",
    "httplib",
    "http.client",
    "http",
    # Web scraping
    "bs4",
    "BeautifulSoup",
    "beautifulsoup4",
    "scrapy",
    "selenium",
    "playwright",
    # Submodules
    "urllib.request",
    "urllib.parse",
    "urllib.error",
    "http.cookiejar",
})

# Tool modules that ARE allowed to use web libraries
ALLOWED_CALLERS: frozenset[str] = frozenset({
    "tools/web_search.py",
    "tools/web_fetch.py",
    "tools/parallel_task.py",
    "tools/parallel_findall.py",
    "tools/parallel_chat.py",
    "tools/deep_research.py",
    "tools/synthesize_research.py",
})


class WebImportBlocker:
    """Import hook that blocks forbidden web libraries except from allowed callers."""

    def _is_project_frame(self, frame_file: str) -> bool:
        """
        Check if a stack frame originates from our project code.

        Returns True if the frame is from pilot project code (should be subject to blocking).
        Returns False if frame is from stdlib, site-packages, or external code (should be allowed).
        """
        if not frame_file:
            return False

        # External/stdlib indicators - these are always allowed
        external_indicators = (
            "site-packages",
            ".venv",
            "/python3.",
            "/Python.framework/",
            "<frozen",
            "<string>",
        )
        for indicator in external_indicators:
            if indicator in frame_file:
                return False

        # Project indicators - check for pilot project paths
        # Matches /pilot/ or /pilot-something/ but not site-packages paths
        if "/pilot/" in frame_file or "/pilot-" in frame_file:
            return True

        return False

    def _is_importlib_internal(self, frame_file: str) -> bool:
        """
        Check if a frame is from importlib internals (should be skipped when finding caller).
        """
        if not frame_file:
            return True

        # Importlib and bootstrap internals
        importlib_indicators = (
            "importlib",
            "_bootstrap",
            "<frozen",
        )
        for indicator in importlib_indicators:
            if indicator in frame_file:
                return True

        return False

    def _find_actual_importer(self, stack: list) -> Optional[str]:
        """
        Find the actual file that contains the import statement.

        The import hook stack looks like:
        - Frame 0: guards.py (our find_module)
        - Frame 1-N: importlib internals
        - Frame N+1: The actual file with the import statement  <-- THIS ONE
        - Frame N+2+: Whatever called that file

        Returns the filename of the actual importer, or None if not found.
        """
        for frame_info in stack:
            frame_file = frame_info.filename

            # Skip our own module
            if "guards.py" in frame_file:
                continue

            # Skip importlib internals
            if self._is_importlib_internal(frame_file):
                continue

            # This is the first non-internal frame = the actual importer
            return frame_file

        return None

    def find_module(self, name: str, path: Optional[list] = None):
        """
        Check if this import should be blocked.

        Returns self to block (triggers load_module), None to allow.

        Logic:
        1. If module is not forbidden, allow
        2. Find the ACTUAL importer (the file with the import statement)
        3. If the importer is in ALLOWED_CALLERS, allow
        4. If the importer is from our project, block
        5. Otherwise allow (external/stdlib import)
        """
        # Get base module name (e.g., "urllib" from "urllib.request")
        base_name = name.split(".")[0]

        # 1. Not a forbidden library - allow
        if name not in FORBIDDEN_WEB_LIBRARIES and base_name not in FORBIDDEN_WEB_LIBRARIES:
            return None

        # 2. Find the actual importer (the file with the import statement)
        stack = inspect.stack()
        importer_file = self._find_actual_importer(stack)

        if not importer_file:
            # Couldn't determine importer, allow to be safe
            return None

        # 3. Check if importer is in allowed list - allow
        for allowed_caller in ALLOWED_CALLERS:
            if allowed_caller in importer_file:
                # Record telemetry for explicitly allowed import from approved caller
                if _telemetry_available:
                    record_event(
                        EventType.IMPORT_ALLOWED,
                        "guards.py",
                        {"module": name, "caller": importer_file},
                    )
                return None

        # 4. If the importer is from our project, block
        if self._is_project_frame(importer_file):
            return self

        # 5. Importer is external code (stdlib, site-packages, etc.) - allow
        return None

    def load_module(self, name: str):
        """
        Called when import is blocked - raise ImportError with policy explanation.
        """
        # Find the caller for telemetry before raising
        caller_file = None
        if _telemetry_available:
            stack = inspect.stack()
            caller_file = self._find_actual_importer(stack)
            record_event(
                EventType.IMPORT_BLOCKED,
                "guards.py",
                {"module": name, "caller": caller_file},
            )

        raise ImportError(
            f"\n{'='*60}\n"
            f"BLOCKED: Import of '{name}' is forbidden by web access policy.\n"
            f"{'='*60}\n\n"
            f"Direct HTTP requests and web scraping are not allowed.\n"
            f"ALL web access MUST go through Parallel API tools.\n\n"
            f"ALTERNATIVES:\n"
            f"  - Use tools/web_search.py for web searches\n"
            f"  - Use tools/web_fetch.py for fetching URLs\n"
            f"  - Use tools/parallel_task.py for complex research\n\n"
            f"If you need web access in a new tool, add it to ALLOWED_CALLERS\n"
            f"in lib/guards.py after review.\n"
            f"{'='*60}"
        )


def install_guards() -> bool:
    """
    Install the web import blocker into sys.meta_path.

    Returns True if newly installed, False if already present.
    """
    # Check if already installed
    for hook in sys.meta_path:
        if isinstance(hook, WebImportBlocker):
            return False

    # Insert at beginning to intercept before standard finders
    sys.meta_path.insert(0, WebImportBlocker())
    return True


# Auto-install on import
install_guards()

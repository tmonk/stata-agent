"""Pytest configuration and fixtures for stata-agent tests."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

# Always set mock mode for tests by default
os.environ.setdefault("MCP_STATA_MOCK", "1")


def _is_stata_available() -> bool:
    """Quick check if Stata is available on this system."""
    if os.environ.get("MCP_STATA_MOCK") == "1":
        return False
    # Check common Stata binary locations
    for path in [
        "/usr/local/bin/stata-se",
        "/usr/local/bin/stata",
        "/Applications/StataNow/StataSE.app/Contents/MacOS/StataSE",
    ]:
        if os.path.exists(path) and os.access(path, os.X_OK):
            return True
    return False


def pytest_collection_modifyitems(config, items):
    """Auto-skip requires_stata tests when Stata is unavailable."""
    if _is_stata_available():
        return  # Don't skip — real Stata is available

    skip_marker = pytest.mark.skip(
        reason="requires Stata license — set MCP_STATA_MOCK=0 and install Stata"
    )
    for item in items:
        if "requires_stata" in item.keywords:
            item.add_marker(skip_marker)


@pytest.fixture
def mock_log_dir():
    """Provide a temporary log directory for tests."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def mock_cache_dir():
    """Provide a temporary cache directory (simulates ~/.cache/stata-agent)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        cache = Path(tmpdir)
        (cache / "sessions").mkdir(parents=True, exist_ok=True)
        (cache / "logs").mkdir(parents=True, exist_ok=True)
        yield cache

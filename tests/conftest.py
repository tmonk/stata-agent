"""Pytest configuration and fixtures for stata-agent tests."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

# Note: STATA_AGENT_MOCK can be set externally to force mock mode.
# By default, we try to detect a live Stata installation first.


def _is_stata_available() -> bool:
    """Quick check if Stata is available on this system.

    Returns False if STATA_AGENT_MOCK=1 is explicitly set in the environment,
    allowing callers to force mock mode. Otherwise checks for a real Stata
    binary on common macOS paths.
    """
    if os.environ.get("STATA_AGENT_MOCK") == "1":
        return False
    # Check common Stata binary locations (macOS, both uppercase and lowercase variants)
    for path in [
        "/usr/local/bin/stata-se",
        "/usr/local/bin/stata-mp",
        "/usr/local/bin/stata-ic",
        "/usr/local/bin/stata",
        "/Applications/StataNow/stata-se",
        "/Applications/StataNow/stata-mp",
        "/Applications/StataNow/stata-ic",
        "/Applications/StataNow/stata",
        "/Applications/StataNow/StataSE.app/Contents/MacOS/StataSE",
        "/Applications/StataNow/StataSE.app/Contents/MacOS/stata-se",
        "/Applications/StataNow/StataMP.app/Contents/MacOS/StataMP",
        "/Applications/StataNow/StataMP.app/Contents/MacOS/stata-mp",
        "/Applications/StataNow/StataIC.app/Contents/MacOS/StataIC",
        "/Applications/StataNow/StataIC.app/Contents/MacOS/stata-ic",
        "/Applications/Stata/StataSE.app/Contents/MacOS/StataSE",
        "/Applications/Stata/StataSE.app/Contents/MacOS/stata-se",
        "/Applications/Stata/StataMP.app/Contents/MacOS/StataMP",
        "/Applications/Stata/StataMP.app/Contents/MacOS/stata-mp",
        "/Applications/Stata/StataIC.app/Contents/MacOS/StataIC",
        "/Applications/Stata/StataIC.app/Contents/MacOS/stata-ic",
    ]:
        if os.path.exists(path) and os.access(path, os.X_OK):
            return True
    return False


def pytest_collection_modifyitems(config, items):
    """Auto-skip tests based on platform and Stata availability."""
    # Skip requires_stata tests when Stata is unavailable
    if _is_stata_available():
        return  # Don't skip — real Stata is available

    skip_marker = pytest.mark.skip(
        reason="requires Stata license — run with Stata installed and without STATA_AGENT_MOCK=1"
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

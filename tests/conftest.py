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
    """Auto-skip tests based on platform and Stata availability.

    Also applies ``fast``, ``slow``, and ``benchmark`` markers based on
    the item's file path so that developers can run sensible subsets.
    """
    tests_root = Path(__file__).resolve().parent

    for item in items:
        fspath = Path(item.fspath).resolve()

        # -- Marker: benchmark (tests/benchmarks/) ------------------------
        if _in_dir(fspath, tests_root / "benchmarks"):
            item.add_marker(pytest.mark.benchmark)

        # -- Marker: slow (e2e, install) --------------------------------
        if _in_dir(fspath, tests_root / "e2e") or _in_dir(fspath, tests_root / "install"):
            item.add_marker(pytest.mark.slow)

        # -- Marker: fast (tests/unit/) ----------------------------------
        if _in_dir(fspath, tests_root / "unit"):
            item.add_marker(pytest.mark.fast)

        # -- Auto-skip: requires_stata -----------------------------------
        if "requires_stata" not in item.keywords:
            continue
        if _is_stata_available():
            continue
        item.add_marker(pytest.mark.skip(
            reason="requires Stata license — run with Stata installed and without STATA_AGENT_MOCK=1"
        ))


def _in_dir(path: Path, dirpath: Path) -> bool:
    """Return True if *path* is inside (or equal to) *dirpath*."""
    try:
        path.resolve().relative_to(dirpath.resolve())
        return True
    except ValueError:
        return False


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

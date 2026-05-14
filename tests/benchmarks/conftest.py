"""Shared fixtures for the benchmark suite.

Provides a real StataClient fixture (requires licensed Stata) and
realistic test data files. Benchmarks that need Stata are marked
``requires_stata`` and auto-skipped when Stata is unavailable.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from datetime import datetime
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Hook: save benchmark results to benchmarks/history/
# ---------------------------------------------------------------------------


def pytest_benchmark_update_json(config, benchmarks, output_json):
    """Save benchmark results to benchmarks/history/ as timestamped JSON."""
    hist_dir = Path(config.rootpath) / "benchmarks" / "history"
    hist_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    commit_info = "unknown"
    try:
        import subprocess
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=5, cwd=config.rootpath,
        )
        if result.returncode == 0:
            commit_info = result.stdout.strip()
    except Exception:
        pass

    filename = f"benchmark_{timestamp}_{commit_info}.json"
    dest = hist_dir / filename

    output_json.setdefault("meta", {})
    output_json["meta"].update({
        "timestamp": timestamp,
        "git_commit": commit_info,
        "project_root": str(config.rootpath),
    })

    with open(dest, "w") as f:
        json.dump(output_json, f, indent=2, default=str)

    print(f"\n[benchmark] Results saved to {dest}")


# ---------------------------------------------------------------------------
# Fixture: real Stata client (requires Stata license)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def stata_client():
    """Create a real StataClient connected to a licensed Stata instance.

    Initialises pystata via ``stata_setup`` (auto-discovery). Requires a
    licensed Stata installation (macOS / Linux / Windows). Skipped in CI
    or when ``STATA_AGENT_MOCK=1``.
    """
    import stata_setup
    from stata_agent.discovery import find_stata_path

    path, edition = find_stata_path()
    edition_lower = edition.lower()
    # Walk up from binary path to find the root that contains utilities/
    bin_dir = os.path.dirname(os.path.abspath(path))
    root = bin_dir
    for _ in range(5):
        if os.path.isdir(os.path.join(root, "utilities")):
            break
        parent = os.path.dirname(root)
        if parent == root:
            root = None
            break
        root = parent
    if root is None:
        pytest.skip(f"Cannot find Stata root (utilities/) from binary: {path}")

    stata_setup.config(root, edition_lower, splash=False)

    from stata_agent.stata_client import StataClient

    client = StataClient(session_name="benchmark")
    client.init()
    yield client
    client.close()


@pytest.fixture(scope="session")
def stata_client_with_auto(stata_client):
    """StataClient with the auto dataset loaded (for data-inspection benchmarks)."""
    stata_client.run("sysuse auto, clear", echo=False)
    return stata_client


# ---------------------------------------------------------------------------
# Fixture: large log content (for ErrorExtractor benchmarks)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def large_log_path() -> str:
    """Create a ~5MB Stata log file for benchmarking log operations."""
    tmp = tempfile.NamedTemporaryFile(suffix=".log", delete=False)
    path = tmp.name
    tmp.close()

    lines = []
    for i in range(150_000):
        if i % 1000 == 0:
            lines.append(f". sysuse auto, clear\n")
            lines.append(f"(1978 Automobile Data)\n")
        elif i % 500 == 0:
            lines.append(f". regress price mpg weight\n")
            lines.append(f"      Source |       SS       df       MS              Number of obs =      74\n")
            lines.append(f"-------------+------------------------------           F(  2,    71) =   14.74\n")
            lines.append(f"       Model |   186321280     2  93160639.9           Prob > F      =  0.0000\n")
            lines.append(f"    Residual |   448744116    71  6320339.67           R-squared     =  0.2934\n")
            lines.append(f"-------------+------------------------------           Adj R-squared =  0.2735\n")
            lines.append(f"       Total |   635065396    73  8699525.97           Root MSE      =  2514.0\n")
            lines.append(f"\n")
            lines.append(f"      price |      Coef.   Std. Err.      t    P>|t|     [95% Conf. Interval]\n")
            lines.append(f"-------------+----------------------------------------------------------------\n")
            lines.append(f"      weight |   1.746559   .6413538     2.72   0.008     .4681902    3.024928\n")
            lines.append(f"         mpg |  -49.51222   86.15604    -0.57   0.567    -221.3025    122.2781\n")
            lines.append(f"       _cons |   1946.069   3597.054     0.54   0.590    -5226.245    9118.382\n")
        elif i % 250 == 0:
            lines.append(f". summarize price mpg weight length\n")
            lines.append(f"    Variable |        Obs        Mean    Std. Dev.       Min        Max\n")
            lines.append(f"-------------+---------------------------------------------------------\n")
            lines.append(f"       price |         74    6165.257    2949.496       3291      15906\n")
            lines.append(f"         mpg |         74     21.2973    5.785503         12         41\n")
            lines.append(f"      weight |         74    3019.459    777.1936       1760       4840\n")
        else:
            lines.append(f"  {i:6d}.  some regular output line for padding\n")

    text = "".join(lines)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)

    size = os.path.getsize(path)
    print(f"[benchmark] Large log created: {size:,} bytes ({len(lines):,} lines)")

    return path


@pytest.fixture(scope="session")
def large_log_with_error_path() -> str:
    """Create a ~2MB log file with an error at the end."""
    tmp = tempfile.NamedTemporaryFile(suffix=".log", delete=False)
    path = tmp.name
    tmp.close()

    lines = []
    for i in range(50_000):
        if i % 500 == 0:
            lines.append(f". sysuse auto, clear\n")
            lines.append(f"(1978 Automobile Data)\n")
        elif i == 49_999:
            lines.append(f". regress y z\n")
            lines.append(f"variable y not found\n")
            lines.append(f"r(111);\n")
        else:
            lines.append(f"  {i:6d}.  output line for padding\n")

    text = "".join(lines)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)

    return path


# ---------------------------------------------------------------------------
# Fixture: large do-file for linter benchmarks
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def large_dofile_path() -> str:
    """Create a ~2000-line do-file for linter benchmarks."""
    tmp = tempfile.NamedTemporaryFile(suffix=".do", delete=False)
    path = tmp.name
    tmp.close()

    lines = []
    lines.append("* Large benchmark do-file\n")
    lines.append("version 18\n")
    lines.append("clear all\n")
    lines.append("set more off\n\n")

    for i in range(100):
        lines.append(f"\n* ---- Block {i} ----\n")
        lines.append(f'sysuse auto, clear\n')
        lines.append(f'gen mpg_sq = mpg^2 for\n')
        lines.append(f'regress price mpg weight length foreign\n')
        lines.append(f'summarize price mpg weight\n')
        lines.append(f'tabulate rep78\n')

        lines.append(f'forvalues j = 1/5 {{\n')
        lines.append(f'    display "Iteration `j\'"\n')
        lines.append(f'    foreach var in price mpg weight {{\n')
        lines.append(f'        summarize `var\'\n')
        lines.append(f'    }}\n')
        lines.append(f'}}\n')

    text = "".join(lines)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)

    return path


# ---------------------------------------------------------------------------
# Fixture: cleanup
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def cleanup_benchmark_history(request):
    """Ensure benchmarks/history/ dir exists before each test."""
    hist_dir = Path.cwd() / "benchmarks" / "history"
    hist_dir.mkdir(parents=True, exist_ok=True)
    yield

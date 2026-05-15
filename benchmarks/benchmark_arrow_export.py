#!/usr/bin/env python3
"""
Benchmark the pyarrow data export path (StataClient.inspect_get format='arrow').

Measures at three levels:
  - Direct call: StataClient.inspect_get(format='arrow') via SFI Data API
  - Daemon RPC:  RpcClient.call("inspect_get", {format:"arrow", ...})
  - CLI:         `stata-agent inspect get --format arrow ...`

Covers ALL parameter combinations:
  - Default (all vars, all rows)
  - varlist subset (partial columns)
  - varlist single (one column)
  - obs_range subset (partial rows)
  - obs_range varlist combination

Two datasets:
  - Small:  sysuse auto (74 obs, 12 vars)
  - Large:  1,000,000 obs, 19 vars (mixed numeric types)

Usage:
    .venv/bin/python benchmarks/benchmark_arrow_export.py

Output:
    benchmarks/history/benchmark_arrow_{timestamp}_{commit}.json
"""

from __future__ import annotations

import json
import math
import os
import signal
import subprocess
import sys
import tempfile
import time
import uuid
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

MIN_TIME_PER_BENCHMARK = 0.5  # seconds of measurement per benchmark
WARMUP_ITERATIONS = 2
DAEMON_START_TIMEOUT = 45
LARGE_DTA_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "testdata", "large_benchmark.dta")
)

# Parameter combinations to test across both datasets
# Each entry: (suffix, varlist, obs_range, description)
PARAM_COMBOS = [
    ("all",       None,   None,      "all vars, all rows (default)"),
    ("varlist5",  None,   None,      "5 vars, all rows"),      # filled per dataset
    ("varlist1",  None,   None,      "1 var, all rows"),
    ("obs10pct",  None,   None,      "all vars, 10% rows"),
    ("obs1pct",   None,   None,      "all vars, 1% rows"),
    ("varlist5.obs10pct", None, None, "5 vars, 10% rows"),
    ("varlist1.obs1pct",  None, None, "1 var, 1% rows"),
]

# Resolve varlist/obs_range per dataset at runtime
def resolve_params(dataset_label: str):
    """Return list of (suffix, varlist, obs_range, desc) for the given dataset."""
    if dataset_label == "small":
        v5 = "price mpg rep78 foreign weight"     # 5 of 12 vars
        v1 = "price"                               # 1 var
        return [
            ("all",         None,              None,              "all 12 vars, all 74 rows"),
            ("varlist5",    v5,                None,              "5 vars, all 74 rows"),
            ("varlist1",    v1,                None,              "1 var, all 74 rows"),
            ("obs10pct",    None,              "1:7",             "all 12 vars, 7 rows (~10%)"),
            ("obs1pct",     None,              "1:1",             "all 12 vars, 1 row (~1%)"),
            ("varlist5.obs10pct", v5,          "1:7",             "5 vars, 7 rows"),
            ("varlist1.obs1pct",  v1,          "1:1",             "1 var, 1 row"),
        ]
    else:
        v5 = "var1 var3 var5 var7 var9"         # 5 of 19 vars
        v1 = "var1"                              # 1 var
        return [
            ("all",         None,              None,              "all 19 vars, all 1M rows"),
            ("varlist5",    v5,                None,              "5 vars, all 1M rows"),
            ("varlist1",    v1,                None,              "1 var, all 1M rows"),
            ("obs10pct",    None,              "1:100000",        "all 19 vars, 100K rows"),
            ("obs1pct",     None,              "1:10000",         "all 19 vars, 10K rows"),
            ("varlist5.obs10pct", v5,          "1:100000",        "5 vars, 100K rows"),
            ("varlist1.obs1pct",  v1,          "1:10000",         "1 var, 10K rows"),
        ]


# ---------------------------------------------------------------------------
# Adaptive measurement
# ---------------------------------------------------------------------------


def measure(func, min_time: float = MIN_TIME_PER_BENCHMARK,
            warmup: int = WARMUP_ITERATIONS) -> dict:
    """Measure *func()* over at least *min_time* seconds.

    Returns a dict with min / max / mean / median / stddev / rounds / total
    (all times in seconds) plus *ops* (operations per second).
    """
    import gc

    # Warmup
    for _ in range(warmup):
        func()

    # Force GC before timed runs
    gc.collect()

    times: list[float] = []
    t_start = time.perf_counter()
    while time.perf_counter() - t_start < min_time:
        t1 = time.perf_counter()
        func()
        times.append(time.perf_counter() - t1)

    n = len(times)
    if n == 0:
        return {"error": "no samples", "rounds": 0}

    times.sort()
    mean = sum(times) / n

    if n >= 2:
        variance = sum((t - mean) ** 2 for t in times) / (n - 1)
        stddev = math.sqrt(variance)
    else:
        stddev = 0.0

    median = times[n // 2] if n % 2 else (times[n // 2 - 1] + times[n // 2]) / 2
    q1 = times[int(n * 0.25)]
    q3 = times[int(n * 0.75)]
    iqr = q3 - q1
    total = sum(times)

    return {
        "min": times[0],
        "max": times[-1],
        "mean": mean,
        "stddev": stddev,
        "median": median,
        "iqr": iqr,
        "q1": q1,
        "q3": q3,
        "rounds": n,
        "total": total,
        "ops": n / total if total > 0 else 0.0,
    }


def entry(group: str, name: str, stats: dict, params: dict | None = None) -> dict:
    """pytest-benchmark-compatible entry."""
    return {
        "group": group,
        "name": name,
        "fullname": f"arrow_bench::{group}::{name}",
        "params": params or {},
        "stats": {
            "min": stats.get("min", 0),
            "max": stats.get("max", 0),
            "mean": stats.get("mean", 0),
            "stddev": stats.get("stddev", 0.0),
            "rounds": stats.get("rounds", 0),
            "median": stats.get("median", 0),
            "iqr": stats.get("iqr", 0.0),
            "q1": stats.get("q1", 0),
            "q3": stats.get("q3", 0),
            "iqr_outliers": 0,
            "stddev_outliers": 0,
            "outliers": "0;0",
            "ld15iqr": stats.get("q1", 0),
            "hd15iqr": stats.get("q3", 0),
            "ops": stats.get("ops", 0),
            "total": stats.get("total", 0),
            "iterations": 1,
            "durations": [],
        },
        "options": {
            "disable_gc": True,
            "timer": "perf_counter",
            "min_time": MIN_TIME_PER_BENCHMARK,
            "warmup": WARMUP_ITERATIONS,
        },
    }


# ---------------------------------------------------------------------------
# Stata initialisation
# ---------------------------------------------------------------------------


def get_client(session: str = "bench_arrow"):
    """Initialise Stata and return a ready-to-use StataClient."""
    from pystata_x.stata_setup import config as px_setup_config
    from stata_agent.discovery import find_stata_path

    path, edition = find_stata_path()
    edition_lower = edition.lower()

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

    px_setup_config(root, edition_lower, splash=False)

    from stata_agent.stata_client import StataClient

    client = StataClient(session_name=session)
    client.init()
    return client


# ---------------------------------------------------------------------------
# Dataset loading helpers
# ---------------------------------------------------------------------------


def load_small_dataset(client):
    """Load sysuse auto."""
    client.run("sysuse auto, clear", echo=False)


def load_large_dataset(client):
    """Load the synthetic large dataset."""
    client.run(f'use "{LARGE_DTA_PATH}", clear', echo=False)


# ---------------------------------------------------------------------------
# Benchmark runner (shared by all levels)
# ---------------------------------------------------------------------------


def run_one_export(client_func, suffix: str, varlist, obs_range,
                   dataset_label: str) -> dict:
    """Perform one export via *client_func(out_path)* and time it."""
    export_dir = tempfile.mkdtemp(prefix=f"arrow_{suffix}_")

    def _run():
        out_path = os.path.join(export_dir, f"out_{uuid.uuid4().hex}.arrow")
        return client_func(out_path, varlist=varlist, obs_range=obs_range)

    stats = measure(_run)

    # Compute rows exported for this combo
    if dataset_label == "small":
        total_rows = 74
    else:
        total_rows = 1_000_000

    if obs_range:
        parts = obs_range.split(":")
        r1, r2 = int(parts[0]), int(parts[1])
        exported_rows = r2 - r1 + 1
    else:
        exported_rows = total_rows

    if varlist:
        exported_vars = len(varlist.split())
    elif dataset_label == "small":
        exported_vars = 12
    else:
        exported_vars = 19

    stats["exported_rows"] = exported_rows
    stats["exported_vars"] = exported_vars
    stats["rows_per_sec"] = exported_rows / stats["mean"] if stats["mean"] > 0 else 0
    stats["cells_per_sec"] = (exported_rows * exported_vars) / stats["mean"] if stats["mean"] > 0 else 0
    stats["ops_per_sec"] = stats["ops"]

    import shutil
    shutil.rmtree(export_dir, ignore_errors=True)

    return stats


# ---------------------------------------------------------------------------
# Benchmark: Direct call level
# ---------------------------------------------------------------------------


def bench_direct_call(client, entries: list, dataset_label: str):
    """Benchmark inspect_get(format='arrow') via direct Python call."""
    params = resolve_params(dataset_label)

    for suffix, varlist, obs_range, desc in params:
        g = f"DirectCall_{dataset_label}_{suffix}"

        def _run_arrow(out_path, varlist=varlist, obs_range=obs_range):
            return client.inspect_get(
                format="arrow", out_path=out_path,
                varlist=varlist, obs_range=obs_range,
            )

        stats = run_one_export(_run_arrow, suffix, varlist, obs_range, dataset_label)
        entries.append(entry(g, "inspect_get_arrow", stats, {
            "dataset": dataset_label, "level": "direct",
            "varlist": varlist, "obs_range": obs_range,
            "desc": desc,
        }))


# ---------------------------------------------------------------------------
# Benchmark: Daemon RPC level
# ---------------------------------------------------------------------------


def start_daemon(session: str) -> subprocess.Popen:
    """Start a real daemon subprocess and return the process handle."""
    cache_dir = Path.home() / ".cache" / "stata-agent" / "sessions"
    cache_dir.mkdir(parents=True, exist_ok=True)
    sock_path = cache_dir / f"{session}.sock"

    proc = subprocess.Popen(
        [sys.executable, "-m", "stata_agent.daemon", "--session", session],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )

    deadline = time.monotonic() + DAEMON_START_TIMEOUT
    while time.monotonic() < deadline:
        if sock_path.exists():
            break
        time.sleep(0.2)
    else:
        proc.terminate()
        proc.wait(timeout=5)
        raise RuntimeError(f"Daemon did not start within {DAEMON_START_TIMEOUT}s")

    time.sleep(1.5)  # settle for worker init

    return proc


def stop_daemon(proc: subprocess.Popen, session: str):
    """Stop the daemon process and clean up."""
    cache_dir = Path.home() / ".cache" / "stata-agent" / "sessions"
    sock_path = cache_dir / f"{session}.sock"

    try:
        from stata_agent.rpc_client import RpcClient
        client = RpcClient(session=session)
        client.call("stop", {"session": session})
    except Exception:
        pass

    proc.terminate()
    try:
        proc.wait(timeout=5)
    except Exception:
        proc.kill()

    sock_path.unlink(missing_ok=True)
    (cache_dir / f"{session}.json").unlink(missing_ok=True)


def bench_daemon_rpc(entries: list, dataset_label: str):
    """Benchmark inspect_get(format='arrow') via daemon RPC."""
    params = resolve_params(dataset_label)

    session = f"bench-arrow-daemon-{uuid.uuid4().hex[:8]}"
    print(f"  Starting daemon (session={session}) ...", end=" ", flush=True)
    proc = start_daemon(session)
    print("ready")

    from stata_agent.rpc_client import RpcClient
    rpc = RpcClient(session=session)

    try:
        # Load the dataset via RPC
        if dataset_label == "small":
            rpc.call("run", {"code": "sysuse auto, clear", "echo": False})
        else:
            rpc.call("run", {"code": f'use "{LARGE_DTA_PATH}", clear', "echo": False})

        for suffix, varlist, obs_range, desc in params:
            g = f"DaemonRPC_{dataset_label}_{suffix}"

            def _run_arrow_rpc(out_path, varlist=varlist, obs_range=obs_range):
                return rpc.call("inspect_get", {
                    "format": "arrow",
                    "out_path": out_path,
                    "varlist": varlist,
                    "obs_range": obs_range,
                })

            stats = run_one_export(_run_arrow_rpc, suffix, varlist, obs_range, dataset_label)
            entries.append(entry(g, "inspect_get_arrow", stats, {
                "dataset": dataset_label, "level": "rpc",
                "varlist": varlist, "obs_range": obs_range,
                "desc": desc,
            }))
    finally:
        stop_daemon(proc, session)


# ---------------------------------------------------------------------------
# Benchmark: CLI level
# ---------------------------------------------------------------------------


def bench_cli(entries: list, dataset_label: str):
    """Benchmark inspect_get(format='arrow') via CLI."""
    params = resolve_params(dataset_label)

    session = f"bench-arrow-cli-{uuid.uuid4().hex[:8]}"
    print(f"  Starting daemon (session={session}) ...", end=" ", flush=True)
    proc = start_daemon(session)
    print("ready")

    load_cmd = "sysuse auto, clear" if dataset_label == "small" \
        else f'use "{LARGE_DTA_PATH}", clear'

    from stata_agent.rpc_client import RpcClient
    rpc = RpcClient(session=session)
    rpc.call("run", {"code": load_cmd, "echo": False})

    for suffix, varlist, obs_range, desc in params:
        g = f"CLI_{dataset_label}_{suffix}"

        export_dir = tempfile.mkdtemp(prefix=f"arrow_cli_{suffix}_")

        def _run_cli(export_dir=export_dir, varlist=varlist, obs_range=obs_range):
            out_path = os.path.join(export_dir, f"out_{uuid.uuid4().hex}.arrow")
            cmd = [
                sys.executable, "-m", "stata_agent", "inspect", "get",
                "--format", "arrow", "--session", session,
                "--out", out_path,
            ]
            if varlist:
                cmd.extend(["--varlist"] + varlist.split())
            if obs_range:
                cmd.extend(["--obs-range", obs_range])
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=30,
            )
            if result.returncode != 0:
                raise RuntimeError(
                    f"CLI failed (rc={result.returncode}): {result.stderr[:500]}"
                )
            return result

        stats = run_one_export(_run_cli, suffix, varlist, obs_range, dataset_label)
        entries.append(entry(g, "inspect_get_arrow", stats, {
            "dataset": dataset_label, "level": "cli",
            "varlist": varlist, "obs_range": obs_range,
            "desc": desc,
        }))

        import shutil
        shutil.rmtree(export_dir, ignore_errors=True)

    stop_daemon(proc, session)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    print("=" * 60)
    print("  PyArrow Export Benchmark Suite — Full Feature Coverage")
    print("=" * 60)
    print()

    start = time.monotonic()
    entries: list[dict] = []

    # ---- Warm StataClient ----
    print("  Initialising Stata ...", end=" ", flush=True)
    client = get_client("bench_arrow_main")
    print("ready")

    # ---- Direct Call: All parameter combos, Small dataset ----
    print("\n  --- Direct Call: Small (sysuse auto, 74x12) ---")
    load_small_dataset(client)
    bench_direct_call(client, entries, "small")

    # ---- Direct Call: All parameter combos, Large dataset ----
    print("\n  --- Direct Call: Large (1M x 19) ---")
    load_large_dataset(client)
    bench_direct_call(client, entries, "large")

    client.close()
    print("  StataClient closed.")

    # ---- Daemon RPC: Small ----
    print("\n  --- Daemon RPC: Small ---")
    bench_daemon_rpc(entries, "small")

    # ---- Daemon RPC: Large ----
    print("\n  --- Daemon RPC: Large ---")
    bench_daemon_rpc(entries, "large")

    # ---- CLI: Small ----
    print("\n  --- CLI: Small ---")
    bench_cli(entries, "small")

    # ---- CLI: Large ----
    print("\n  --- CLI: Large ---")
    bench_cli(entries, "large")

    # ---- Summary ----
    elapsed = time.monotonic() - start
    total_measured = sum(
        b["stats"].get("total", 0) for b in entries
        if isinstance(b.get("stats"), dict)
    )
    print(f"\n  --- Summary ---")
    print(f"  Measured wall time: {total_measured:.3f}s across {len(entries)} benchmarks")
    print(f"  Total script time: {elapsed:.1f}s")
    print()

    # Sort by mean descending (slowest first)
    sorted_entries = sorted(entries, key=lambda e: e["stats"].get("mean", 0), reverse=True)
    print(f"  {'GROUP':40s} {'MEAN':>10s}  {'ROWS':>8s}  {'CELLS':>10s}  {'DESC'}")
    print(f"  {'-'*40} {'-'*10}  {'-'*8}  {'-'*10}  {'-'*30}")
    for e in sorted_entries:
        s = e["stats"]
        mean_us = s["mean"] * 1e6
        print(f"  {e['group']:40s} {mean_us:>10.1f}µs  "
              f"{s.get('exported_rows', '?'):>8}  "
              f"{s.get('exported_vars', '?'):>10}  "
              f"{e['params'].get('desc', ''):.50s}")

    # Highlight the slowest
    slowest = sorted_entries[0]
    print(f"\n  ⏱️  Slowest benchmark: {slowest['group']} at {slowest['stats']['mean']:.3f}s")
    print(f"       {slowest['params'].get('desc', '')}")

    save_results(entries, sorted_entries)


def save_results(entries: list, sorted_entries: list | None = None):
    """Write benchmark results to benchmarks/history/ as JSON."""
    root = Path.cwd()
    hist_dir = root / "benchmarks" / "history"
    hist_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    commit_info = "unknown"
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=5, cwd=root,
        )
        if result.returncode == 0:
            commit_info = result.stdout.strip()
    except Exception:
        pass

    filename = f"benchmark_arrow_{timestamp}_{commit_info}.json"
    dest = hist_dir / filename

    # Determine phase from existing history
    hist_files = sorted(hist_dir.glob("benchmark_arrow_*.json"))
    phase_count = sum(1 for f in hist_files if "all_features" not in f.name)
    phase = "all_features_v1" if phase_count >= 2 else "baseline"

    payload = {
        "benchmark_suite": "arrow_export",
        "phase": phase,
        "description": "Full parameter coverage: default, varlist, obs_range, and combinations",
        "machine_info": {
            "platform": sys.platform,
            "cpu": os.uname().machine,
            "node": os.uname().nodename,
        },
        "commit_info": {"commit": commit_info},
        "benchmarks": entries,
        "slowest": sorted_entries[0]["group"] if sorted_entries else None,
        "slowest_time": sorted_entries[0]["stats"]["mean"] if sorted_entries else None,
        "meta": {
            "timestamp": timestamp,
            "git_commit": commit_info,
            "project_root": str(root),
            "runner": "benchmarks/benchmark_arrow_export.py",
            "large_dataset": LARGE_DTA_PATH,
            "parameter_combos": [
                {"suffix": s, "desc": d}
                for s, _, _, d in resolve_params("large")  # use large dataset schema
            ],
        },
    }

    with open(dest, "w") as f:
        json.dump(payload, f, indent=2, default=str)

    print(f"\n  Results saved: {dest}")


if __name__ == "__main__":
    main()

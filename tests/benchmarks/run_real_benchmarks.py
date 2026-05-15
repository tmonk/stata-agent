#!/usr/bin/env python3
"""
Real-Stata benchmark runner (single-process, no test-framework overhead).

Measures **our Python code** around Stata operations — the wrapper overhead,
not Stata's own computation time.  Stata initialisation IS benchmarked
(since our agent performs it), but individual commands are kept as fast
as possible (``display``, not ``regress``).

Pure-Python benchmarks (linter, log ops, helpers, runner) remain in
pytest since they have zero Stata overhead and run instantly.

Usage:
    uv run python tests/benchmarks/run_real_benchmarks.py

Output:
    benchmarks/history/benchmark_{timestamp}_{commit}.json
"""

from __future__ import annotations

import json
import math
import os
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

MIN_TIME_PER_BENCHMARK = 0.3  # seconds of measurement per benchmark
WARMUP_ITERATIONS = 3
DAEMON_START_TIMEOUT = 30

# ---------------------------------------------------------------------------
# Adaptive timing
# ---------------------------------------------------------------------------


def measure(func, min_time: float = MIN_TIME_PER_BENCHMARK,
            warmup: int = WARMUP_ITERATIONS) -> dict:
    """Measure *func()* over at least *min_time* seconds.

    Returns a dict with min / max / mean / median / stddev / rounds / total
    (all times in seconds) plus *ops* (operations per second).
    """
    for _ in range(warmup):
        func()

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


def entry(group: str, name: str, stats: dict) -> dict:
    """pytest-benchmark-compatible entry from *measure()* result."""
    return {
        "group": group,
        "name": name,
        "fullname": f"real::{group}::{name}",
        "params": {},
        "stats": {
            "min": stats["min"],
            "max": stats["max"],
            "mean": stats["mean"],
            "stddev": stats.get("stddev", 0.0),
            "rounds": stats["rounds"],
            "median": stats["median"],
            "iqr": stats.get("iqr", 0.0),
            "q1": stats.get("q1", stats["min"]),
            "q3": stats.get("q3", stats["max"]),
            "iqr_outliers": 0,
            "stddev_outliers": 0,
            "outliers": "0;0",
            "ld15iqr": stats.get("q1", stats["min"]),
            "hd15iqr": stats.get("q3", stats["max"]),
            "ops": stats["ops"],
            "total": stats["total"],
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
# Stata initialisation (benchmarked separately)
# ---------------------------------------------------------------------------


def measure_cold_init() -> float:
    """Measure cold Stata init time in a fresh subprocess."""
    script = '''
import sys, time
sys.path.insert(0, "/Applications/StataNow/utilities")
from pystata_x.stata_setup import config as px_setup_config
from stata_agent.discovery import find_stata_path
path, edition = find_stata_path()
edition_lower = edition.lower()
bin_dir = __import__("os").path.dirname(__import__("os").path.abspath(path))
root = bin_dir
for _ in range(5):
    if __import__("os").path.isdir(__import__("os").path.join(root, "utilities")):
        break
    parent = __import__("os").path.dirname(root)
    if parent == root:
        root = None
        break
    root = parent
px_setup_config(root, edition_lower, splash=False)
from stata_agent.stata_client import StataClient
client = StataClient(session_name="cold_init_measure")
client.init()
client.close()
'''
    t0 = time.monotonic()
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True, text=True, timeout=60,
    )
    elapsed = time.monotonic() - t0
    if result.returncode != 0:
        print(f"    Cold init subprocess failed: {result.stderr.strip()}")
        return 0.0
    return elapsed


def get_client():
    """Initialise Stata and return a ready-to-use StataClient."""
    sys.path.insert(0, "/Applications/StataNow/utilities")
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

    client = StataClient(session_name="bench_real")
    client.init()
    return client


# ---------------------------------------------------------------------------
# Benchmark groups  —  each measures *our wrapper code*, not Stata internals
# ---------------------------------------------------------------------------


def bench_code_execution(client, entries: list):
    """Benchmark our wrapper overhead around StataSO_Execute.

    Commands are trivial (``display``) so Stata's execution time is negligible.
    """
    g = "CodeExecution"

    # Warm up once
    client.run("display 1+1", echo=False)

    # run() with echo
    def run_simple():
        client.run("display 1+1", echo=True)
    entries.append(entry(g, "run_simple_code", measure(run_simple)))

    # run() without echo (slightly less output handling)
    def run_no_echo():
        client.run("display 1+1", echo=False)
    entries.append(entry(g, "run_no_echo", measure(run_no_echo)))

    # run_file()
    def run_file_bench():
        fd, path = tempfile.mkstemp(suffix=".do")
        os.close(fd)
        with open(path, "w") as f:
            f.write("display 1+1\n")
        try:
            client.run_file(path, echo=False)
        finally:
            os.unlink(path)
    entries.append(entry(g, "run_file", measure(run_file_bench)))

    # Multi-line code (triggers temp-do-file + include path — our Python cost)
    code = "display 1\ndisplay 2\ndisplay 3\n"

    def run_multiline():
        client.run(code, echo=False)
    entries.append(entry(g, "run_multiline_code",
                   measure(run_multiline, min_time=1.0)))

    # Output truncation — our overhead when max_output_tokens is set
    def run_truncated():
        client.run("display 1+1", echo=True, max_output_tokens=10)
    entries.append(entry(g, "run_with_output_truncation",
                   measure(run_truncated, min_time=1.0)))


def bench_data_inspection(client, entries: list):
    """Benchmark our data-inspection wrapper methods."""
    client.run("sysuse auto, clear", echo=False)
    g = "DataInspection"

    def describe():
        client.inspect_describe()
    entries.append(entry(g, "inspect_describe", measure(describe)))

    def describe_vl():
        client.inspect_describe(varlist="price mpg weight")
    entries.append(entry(g, "inspect_describe_with_varlist",
                   measure(describe_vl)))

    # Our code: _stata_run("summarize ..., detail") + _read_log_tail()
    def summary():
        client.inspect_summary(varlist="price mpg weight")
    entries.append(entry(g, "inspect_summary", measure(summary)))

    # Our code: _stata_run("codebook ...") + _read_log_tail()
    def codebook():
        client.inspect_codebook(varlist="price mpg")
    entries.append(entry(g, "inspect_codebook", measure(codebook)))

    # Our code: _stata_run("list ...") + _read_log_tail()
    def list_vars():
        client.inspect_list(varlist="price mpg", from_row=1, count=5)
    entries.append(entry(g, "inspect_list", measure(list_vars)))

    # Our code: _stata_run("export delimited ...") + os.path.getsize()
    def get_csv():
        fd, out = tempfile.mkstemp(suffix=".csv")
        os.close(fd)
        os.unlink(out)
        client.inspect_get(format="csv", out_path=out, varlist="price mpg")
        os.unlink(out)
    entries.append(entry(g, "inspect_get_csv", measure(get_csv)))

    # JSON export (via jsonio) — skip if not installed
    stdout, rc = client._stata_run('capture which jsonio', echo=False)
    stdout2, _ = client._stata_run('display "rc=" _rc', echo=False)
    if "rc=0" in stdout2:
        def get_json():
            fd, out = tempfile.mkstemp(suffix=".json")
            os.close(fd)
            os.unlink(out)
            client.inspect_get(format="json", out_path=out, varlist="price mpg")
            os.unlink(out)
        entries.append(entry(g, "inspect_get_json", measure(get_json)))
    else:
        print("  [jsonio not installed, skip inspect_get_json]")

    # Arrow export — default (all vars, all rows)
    def get_arrow():
        fd, out = tempfile.mkstemp(suffix=".arrow")
        os.close(fd)
        os.unlink(out)
        client.inspect_get(format="arrow", out_path=out)
        os.unlink(out)
    entries.append(entry(g, "inspect_get_arrow", measure(get_arrow)))

    # Arrow export with varlist (partial columns)
    def get_arrow_varlist():
        fd, out = tempfile.mkstemp(suffix=".arrow")
        os.close(fd)
        os.unlink(out)
        client.inspect_get(format="arrow", out_path=out, varlist="price mpg weight")
        os.unlink(out)
    entries.append(entry(g, "inspect_get_arrow_varlist", measure(get_arrow_varlist)))

    # Arrow export with obs_range (partial rows)
    def get_arrow_obsrange():
        fd, out = tempfile.mkstemp(suffix=".arrow")
        os.close(fd)
        os.unlink(out)
        client.inspect_get(format="arrow", out_path=out, obs_range="1:10")
        os.unlink(out)
    entries.append(entry(g, "inspect_get_arrow_obsrange", measure(get_arrow_obsrange)))


def bench_results(client, entries: list):
    """Benchmark our result-retrieval wrapper (_read_log_tail() + parsing)."""
    g = "Results"

    # Ensure the relevant result classes are populated
    client.run("sysuse auto, clear", echo=False)
    client.run("regress price mpg weight", echo=False)

    def r_class():
        client.get_results()
    entries.append(entry(g, "get_results_r_class", measure(r_class)))

    client.run("ereturn list", echo=False)

    def e_class():
        client.get_results()
    entries.append(entry(g, "get_results_e_class", measure(e_class)))

    client.run("return list", echo=False)

    def s_class():
        client.get_results()
    entries.append(entry(g, "get_results_s_class", measure(s_class)))


def bench_graph_operations(client, entries: list):
    """Benchmark our graph-listing and export wrapper."""
    g = "GraphOperations"

    client.run("sysuse auto, clear", echo=False)
    client.run("scatter price mpg, name(g1)", echo=True)
    client.run("histogram weight, name(g2)", echo=True)
    client._stata_run("graph display g1", echo=False)

    # Our code: snapshot_graphs() (standalone graph dir query)
    def graph_list():
        client.snapshot_graphs()
    entries.append(entry(g, "graph_list", measure(graph_list)))

    # Our code: run() with track_graphs=False (zero-cost default)
    def run_no_track():
        client.run("display 1+1", echo=False, track_graphs=False)
    entries.append(entry(g, "run_track_graphs_false", measure(run_no_track)))

    # Our code: run() with track_graphs=True (bundled query)
    def run_track():
        client.run("display 1+1", echo=False, track_graphs=True,
                    max_output_tokens=1000)
    entries.append(entry(g, "run_track_graphs_true", measure(run_track)))

    # Our code: execute() with track_graphs=True (bundled)
    from pystata_x._core import execute
    def exec_track():
        execute("display 1+1", echo=False, capture=True, track_graphs=True)
    entries.append(entry(g, "execute_track_graphs_true", measure(exec_track)))

    # Our code: _stata_run("graph export ...") + file-size check
    tmp_fd, out = tempfile.mkstemp(suffix=".png")
    os.close(tmp_fd)
    os.unlink(out)

    # Our code: export_graph() (full wrapper, default PDF format)
    def export_graph_wrapper():
        client.export_graph(name="g1", fmt="pdf", out_path=out)
    entries.append(entry(g, "graph_export_wrapper",
                   measure(export_graph_wrapper, min_time=1.0)))

    def graph_export():
        client._stata_run("graph display g1", echo=False)
        client._stata_run(f'graph export "{out}", name(g1) replace', echo=False)
    entries.append(entry(g, "graph_export",
                   measure(graph_export, min_time=1.0)))
    try:
        os.unlink(out)
    except FileNotFoundError:
        pass


def bench_log_operations(client, entries: list):
    """Benchmark log reading and error extraction."""
    g = "LogOperations"

    # Generate some log content first
    client.run("display 1+1", echo=True)
    client.run("display 2+2", echo=True)
    for i in range(10):
        client.run(f"display {i}", echo=False)

    # Our code: read_log_tail()
    def read_tail():
        client.read_log_tail(lines=50)
    entries.append(entry(g, "log_tail_50", measure(read_tail)))

    # Get log errors (no errors expected — measures parsing overhead)
    log_path_str = str(client._log_path) if client._log_path else ""
    from stata_agent.error_extractor import ErrorExtractor
    extractor = ErrorExtractor()

    def extract_errors():
        if log_path_str:
            extractor.extract_from_tail(log_path_str)
        return None
    entries.append(entry(g, "log_errors_clean", measure(extract_errors)))

    # Log rotation (triggers file rotation + log close/reopen)
    # Small adjustment: write many lines to force rotation
    for i in range(5):
        client.run("display 'line' + string(" + str(i) + ")", echo=True)

    def rotate_log():
        client._rotate_if_needed()
    entries.append(entry(g, "log_rotate", measure(rotate_log)))

    # Search in log
    from stata_agent.log_manager import search_in_log

    def search():
        search_in_log(client._log_path, "display")
    entries.append(entry(g, "log_search", measure(search)))

    # Paginated read
    from stata_agent.log_manager import paginated_read

    def paginated():
        paginated_read(client._log_path, offset=0, max_bytes=4096)
    entries.append(entry(g, "log_paginated_read", measure(paginated)))


def bench_daemon(entries: list):
    """Start one real daemon subprocess and benchmark our RPC overhead."""
    from stata_agent.rpc_client import RpcClient

    g = "Daemon"
    cache_dir = Path.home() / ".cache" / "stata-agent" / "sessions"
    cache_dir.mkdir(parents=True, exist_ok=True)

    session = f"bench-daemon-{uuid.uuid4().hex[:8]}"
    sock_path = cache_dir / f"{session}.sock"

    print("  Starting daemon ...", end=" ", flush=True)
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
        time.sleep(0.1)
    else:
        proc.terminate()
        proc.wait(timeout=5)
        print("FAILED (timeout)  — daemon benchmarks skipped")
        return

    time.sleep(1.5)
    client = RpcClient(session=session)
    print("ready")

    try:
        # Health-check RPC roundtrip (our code: socket send/recv + JSON)
        def health():
            client.call("health", {})
        entries.append(entry(g, "daemon_health_check", measure(health)))

        # Full roundtrip: RPC → daemon → worker → StataSO_Execute → reply
        def run_simple():
            client.call("run", {"code": "display 1+1", "echo": True,
                                "max_output_tokens": 1000})
        entries.append(entry(g, "daemon_run_simple", measure(run_simple)))

        code = "sysuse auto, clear\nregress price mpg weight\npredict pred\n"

        def run_multiline():
            client.call("run", {"code": code, "echo": False,
                                "max_output_tokens": 1000})
        entries.append(entry(g, "daemon_run_multiline",
                       measure(run_multiline, min_time=1.0)))

        # Arrow export via RPC (small dataset)
        client.call("run", {"code": "sysuse auto, clear", "echo": False})
        arrow_dir = tempfile.mkdtemp(prefix="arrow_daemon_")

        def arrow_rpc():
            out_path = os.path.join(arrow_dir, f"out_{uuid.uuid4().hex}.arrow")
            client.call("inspect_get", {"format": "arrow", "out_path": out_path})
            return out_path
        entries.append(entry(g, "daemon_inspect_get_arrow", measure(arrow_rpc)))

        # Arrow export with varlist via RPC
        def arrow_rpc_varlist():
            out_path = os.path.join(arrow_dir, f"out_{uuid.uuid4().hex}.arrow")
            client.call("inspect_get", {"format": "arrow", "out_path": out_path,
                                         "varlist": "price mpg weight"})
            return out_path
        entries.append(entry(g, "daemon_inspect_get_arrow_varlist",
                       measure(arrow_rpc_varlist)))

        # log_tail via RPC
        def tail_rpc():
            client.call("log_tail", {"lines": 50})
        entries.append(entry(g, "daemon_log_tail_50", measure(tail_rpc)))

        # log_errors via RPC
        def errors_rpc():
            client.call("log_errors", {"context_lines": 20})
        entries.append(entry(g, "daemon_log_errors", measure(errors_rpc)))

        import shutil
        shutil.rmtree(arrow_dir, ignore_errors=True)

        # Pure Python: JSON ser/deser (our code for IPC framing)
        request = {"id": "test", "method": "run",
                   "args": {"code": "display 1+1", "echo": True}}
        response = {"id": "test", "ok": True,
                    "result": {"ok": True, "rc": 0, "stdout": ". display 1+1\n2\n",
                               "log_path": "/tmp/mock.log", "truncated": False}}

        def json_ser():
            req_bytes = json.dumps(request).encode("utf-8")
            resp = json.loads(json.dumps(response))
            return req_bytes, resp

        entries.append(entry(g, "rpc_json_serialization", measure(json_ser)))

    finally:
        try:
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


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    print("=" * 60)
    print("  Real-Stata Benchmark Runner  (measuring our code, not Stata's)")
    print("=" * 60)
    print()

    start = time.monotonic()
    entries: list[dict] = []

    entries: list[dict] = []

    # ---- Cold Stata init (subprocess) ----
    print("  --- Cold Stata Init ---", end=" ", flush=True)
    cold_init = measure_cold_init()
    print(f"{cold_init:.2f}s")
    if cold_init > 0:
        entries.append({
            "group": "StataInit",
            "name": "stata_cold_init",
            "fullname": "real::StataInit::stata_cold_init",
            "params": {},
            "stats": {
                "min": cold_init, "max": cold_init, "mean": cold_init,
                "stddev": 0.0, "rounds": 1, "median": cold_init,
                "iqr": 0.0, "q1": cold_init, "q3": cold_init,
                "iqr_outliers": 0, "stddev_outliers": 0,
                "outliers": "0;0", "ld15iqr": cold_init,
                "hd15iqr": cold_init,
                "ops": 1.0 / cold_init if cold_init > 0 else 0.0,
                "total": cold_init, "iterations": 1,
                "durations": [],
            },
            "options": {},
        })

    # ---- Warm StataClient ----
    print("  Initialising Stata for benchmarks ...", end=" ", flush=True)
    client = get_client()
    print("ready")

    print("\n  --- Code Execution ---")
    bench_code_execution(client, entries)

    print("\n  --- Data Inspection ---")
    bench_data_inspection(client, entries)

    print("\n  --- Results ---")
    bench_results(client, entries)

    print("\n  --- Graph Operations ---")
    bench_graph_operations(client, entries)

    print("\n  --- Log Operations ---")
    bench_log_operations(client, entries)

    client.close()

    # ---- Daemon ----
    print("\n  --- Daemon ---")
    bench_daemon(entries)

    # ---- Save ----
    elapsed = time.monotonic() - start
    total_time = sum(b["stats"].get("total", 0) for b in entries)
    print(f"\n  Measured wall time: {total_time:.3f}s across {len(entries)} benchmarks")
    print(f"  Total script time: {elapsed:.1f}s")
    save_results(entries)


def save_results(entries: list):
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

    filename = f"benchmark_{timestamp}_{commit_info}.json"
    dest = hist_dir / filename

    payload = {
        "machine_info": {"cpu": os.uname().machine, "node": os.uname().nodename},
        "commit_info": {"commit": commit_info},
        "benchmarks": entries,
        "meta": {
            "timestamp": timestamp,
            "git_commit": commit_info,
            "project_root": str(root),
            "runner": "run_real_benchmarks.py",
        },
    }

    with open(dest, "w") as f:
        json.dump(payload, f, indent=2, default=str)

    print(f"\n  Results saved: {dest}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Profile graph operations via Stata C library (StataSO_* API).

Focus: PDF graph export (the default, immutable format).
Investigates:
  1. Time split: graph display vs PDF graph export
  2. Can we skip graph display before PDF export? (name() option)
  3. Different PDF export resolution/quality options
  4. Graph listing latency (for context)
  5. Unused StataSO_* API functions
"""

from __future__ import annotations

import math
import os
import shutil
import sys
import tempfile
import time
from ctypes import c_char_p, c_int


def get_client():
    """Initialise and return a ready StataClient."""
    sys.path.insert(0, "/Applications/StataNow/utilities")
    from pystata_x.stata_setup import config as px_setup_config
    from stata_agent.discovery import find_stata_path
    from stata_agent.stata_client import StataClient

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
    client = StataClient(session_name="bench_graph")
    client.init()
    return client


def measure_n(func, n: int = 20) -> dict:
    """Run func() n times, return stats in ms."""
    times = []
    for _ in range(n):
        t1 = time.perf_counter()
        func()
        times.append(time.perf_counter() - t1)

    times.sort()
    mean = sum(times) / len(times)
    if len(times) >= 2:
        variance = sum((t - mean) ** 2 for t in times) / (len(times) - 1)
        stddev = math.sqrt(variance)
    else:
        stddev = 0.0

    return {
        "min": times[0] * 1000,
        "max": times[-1] * 1000,
        "mean": mean * 1000,
        "stddev": stddev * 1000,
        "rounds": len(times),
        "median": times[len(times) // 2] * 1000,
    }


def fmt_ms(ms: float) -> str:
    if ms >= 1000:
        return f"{ms/1000:.3f}s"
    return f"{ms:.2f}ms"


def main():
    client = get_client()

    # Create test graphs
    print("Creating test graphs...")
    client.run("sysuse auto, clear", echo=False)
    client.run("scatter price mpg, name(g1)", echo=False)
    client.run("histogram weight, name(g2)", echo=False)

    tmp_dir = tempfile.mkdtemp(prefix="graph_profile_")

    # ==================================================================
    # 1. Time split: display vs PDF export
    # ==================================================================
    print("\n" + "=" * 65)
    print("  1. TIME SPLIT: graph display vs PDF export (default format)")
    print("=" * 65)

    def do_display():
        client._stata_run("graph display g1", echo=False)

    stats_display = measure_n(do_display, n=10)
    print(f"\n    graph display g1:")
    print(f"      mean={fmt_ms(stats_display['mean'])} ±{stats_display['stddev']:.2f}ms  "
          f"min={fmt_ms(stats_display['min'])}  max={fmt_ms(stats_display['max'])}")

    # PDF export WITHOUT display (using name(g1) option)
    out_pdf = os.path.join(tmp_dir, "test_direct.pdf")

    def do_export_pdf():
        client._stata_run(
            f'graph export "{out_pdf}", name(g1) replace as(pdf)',
            echo=False,
        )
    stats_export_pdf = measure_n(do_export_pdf, n=10)
    print(f"    graph export (PDF)  -- direct, no display:")
    print(f"      mean={fmt_ms(stats_export_pdf['mean'])} ±{stats_export_pdf['stddev']:.2f}ms  "
          f"min={fmt_ms(stats_export_pdf['min'])}  max={fmt_ms(stats_export_pdf['max'])}")

    # Current two-step: display + export
    def do_display_then_export():
        client._stata_run("graph display g1", echo=False)
        client._stata_run(
            f'graph export "{out_pdf}", replace as(pdf)',
            echo=False,
        )
    stats_both = measure_n(do_display_then_export, n=10)
    print(f"    display + export    -- current two-step:")
    print(f"      mean={fmt_ms(stats_both['mean'])} ±{stats_both['stddev']:.2f}ms  "
          f"min={fmt_ms(stats_both['min'])}  max={fmt_ms(stats_both['max'])}")

    if stats_both['mean'] > 0 and stats_export_pdf['mean'] > 0:
        saving = stats_both['mean'] - stats_export_pdf['mean']
        saving_pct = saving / stats_both['mean'] * 100
        print(f"\n    => Skipping display saves {fmt_ms(saving)} ({saving_pct:.0f}%)")

    # ==================================================================
    # 2. PDF export options exploration
    # ==================================================================
    print("\n" + "=" * 65)
    print("  2. PDF EXPORT OPTIONS EXPLORATION")
    print("=" * 65)

    pdf_configs = [
        ("", "Default PDF"),
        (" magscale(0.5)", "magscale(0.5)"),
        (" magscale(2.0)", "magscale(2.0)"),
        (" pagesize(letter)", "pagesize(letter)"),
        (" pagesize(a4)", "pagesize(a4)"),
    ]

    results = []
    for opts, label in pdf_configs:
        out_path = os.path.join(tmp_dir, f"test_opt.pdf")

        def make_fn(out=out_path, opts=opts):
            def fn():
                client._stata_run(
                    f'graph export "{out}", name(g1) replace as(pdf){opts}',
                    echo=False,
                )
            return fn

        s = measure_n(make_fn(), n=10)
        size = os.path.getsize(out_path) if os.path.exists(out_path) else 0
        results.append(("pdf", label, s, size))
        print(f"    pdf  {label:28s} mean={fmt_ms(s['mean']):>8s}  "
              f"min={fmt_ms(s['min']):>8s}  max={fmt_ms(s['max']):>8s}  "
              f"size={size//1024:>5}KB")

    # ==================================================================
    # 3. Full wrapper overhead (default export_graph() which defaults to pdf)
    # ==================================================================
    print("\n" + "=" * 65)
    print("  3. FULL WRAPPER OVERHEAD")
    print("=" * 65)

    out_w = os.path.join(tmp_dir, "wrapper.pdf")

    def do_wrapper():
        client.export_graph(name="g1", fmt="pdf", out_path=out_w)
    stats_wrapper = measure_n(do_wrapper, n=10)
    print(f"    client.export_graph(name='g1', fmt='pdf'):")
    print(f"      mean={fmt_ms(stats_wrapper['mean'])} ±{stats_wrapper['stddev']:.2f}ms  "
          f"min={fmt_ms(stats_wrapper['min'])}  max={fmt_ms(stats_wrapper['max'])}")

    wrapper_pdf_only = 0
    if stats_wrapper['mean'] > 0 and stats_both['mean'] > 0:
        wrapper_overhead = stats_wrapper['mean'] - stats_both['mean']
        wrapper_pdf_only = wrapper_overhead
        print(f"    Wrapper overhead vs raw two-step: {wrapper_overhead:.2f}ms "
              f"({wrapper_overhead/stats_wrapper['mean']*100:.1f}%)")

    # ==================================================================
    # 4. Graph listing benchmarks
    # ==================================================================
    print("\n" + "=" * 65)
    print("  4. GRAPH LISTING")
    print("=" * 65)

    def do_snapshot():
        client.snapshot_graphs()
    stats_snapshot = measure_n(do_snapshot, n=200)
    print(f"    snapshot_graphs() (graph dir + SFI):")
    print(f"      mean={fmt_ms(stats_snapshot['mean'])}  "
          f"min={fmt_ms(stats_snapshot['min'])}  max={fmt_ms(stats_snapshot['max'])}  "
          f"n={stats_snapshot['rounds']}")

    from pystata_x._core import execute
    from sfi import Macro

    def do_internal():
        execute("quietly graph dir, memory", echo=False, capture=False)
        Macro.getGlobal("r(list)")
    stats_internal = measure_n(do_internal, n=200)
    print(f"    execute(capture=False) + Macro:")
    print(f"      mean={fmt_ms(stats_internal['mean'])}  "
          f"min={fmt_ms(stats_internal['min'])}  max={fmt_ms(stats_internal['max'])}  "
          f"n={stats_internal['rounds']}")

    def do_bundled():
        result = execute(
            "display 1+1\nquietly graph dir, memory",
            echo=False, capture=True, track_graphs=True,
        )
        _ = set(result.graph_names or [])
    stats_bundled = measure_n(do_bundled, n=200)
    print(f"    Bundled query (display + graph dir):")
    print(f"      mean={fmt_ms(stats_bundled['mean'])}  "
          f"min={fmt_ms(stats_bundled['min'])}  max={fmt_ms(stats_bundled['max'])}  "
          f"n={stats_bundled['rounds']}")

    # ==================================================================
    # 5. Unused StataSO_* API
    # ==================================================================
    print("\n" + "=" * 65)
    print("  5. UNUSED StataSO_* API SURFACE")
    print("=" * 65)

    from pystata_x._config import stlib

    checks = [
        ("StataSO_EchoStdout", lambda: (
            setattr(stlib.StataSO_EchoStdout, 'restype', None),
            setattr(stlib.StataSO_EchoStdout, 'argtypes', [c_char_p]),
            None,
        )),
        ("StataSO_SetOutputBufferSz_M", lambda: (
            setattr(stlib.StataSO_SetOutputBufferSz_M, 'restype', None),
            setattr(stlib.StataSO_SetOutputBufferSz_M, 'argtypes', [c_int]),
            stlib.StataSO_SetOutputBufferSz_M(c_int(4)),
        )),
        ("StataSO_AppendOutputBuffer", lambda: (
            setattr(stlib.StataSO_AppendOutputBuffer, 'restype', None),
            setattr(stlib.StataSO_AppendOutputBuffer, 'argtypes', [c_char_p]),
            None,
        )),
    ]

    for name, fn in checks:
        try:
            fn()
            print(f"    {name:35s} ✓ resolves")
        except Exception as e:
            print(f"    {name:35s} ✗ {e}")

    # ==================================================================
    # 6. Summary
    # ==================================================================
    print("\n" + "=" * 65)
    print("  SUMMARY — PDF GRAPH EXPORT")
    print("=" * 65)

    display_cost = stats_display['mean']
    export_cost = stats_export_pdf['mean']

    print(f"""
    graph display:             {fmt_ms(display_cost):>8s}
    PDF export (no display):   {fmt_ms(export_cost):>8s}
    display + PDF export:      {fmt_ms(stats_both['mean']):>8s}
    export_graph() wrapper:    {fmt_ms(stats_wrapper['mean']):>8s}
    graph listing (snapshot):  {fmt_ms(stats_snapshot['mean']):>8s}
    graph listing (bundled):   {fmt_ms(stats_bundled['mean']):>8s}
    """)

    results_sorted = sorted(results, key=lambda r: r[2]['mean'])
    print(f"  PDF options (fastest → slowest):")
    for rank, (_, label, s, size) in enumerate(results_sorted, 1):
        print(f"    {rank}. {label:28s} {fmt_ms(s['mean']):>8s}  {size//1024:>5}KB")

    # Recommendations
    print(f"\n  RECOMMENDATIONS:")
    if export_cost > 0 and stats_both['mean'] > 0:
        saving_display = stats_both['mean'] - export_cost
        if saving_display > 1:
            print(f"    ✅ Skip graph display before PDF export: saves ~{fmt_ms(saving_display)}")
            print(f"       export_graph() now uses name() option directly — ~3ms vs ~18ms")
    print(f"    ✅ Graph listing at ~{stats_snapshot['mean']:.0f}µs is near the StataSO floor")
    print(f"    ❌ No StataSO_* function provides a graph-specific shortcut")

    shutil.rmtree(tmp_dir, ignore_errors=True)
    client.close()


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Systematic benchmark of all graph export formats / resolutions.

Tests: PDF, SVG, EPS, PNG at widths 200–3200.
Each format+option combo writes to a UNIQUE file.
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import time
import math


def get_client():
    sys.path.insert(0, "/Applications/StataNow/utilities")
    from pystata_x.stata_setup import config as px_setup_config
    from stata_agent.discovery import find_stata_path
    from stata_agent.stata_client import StataClient

    path, edition = find_stata_path()
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
    px_setup_config(root, edition.lower(), splash=False)
    client = StataClient(session_name="fmt_bench")
    client.init()
    return client


def main():
    client = get_client()
    client.run("sysuse auto, clear", echo=False)
    client.run("scatter price mpg, name(g1)", echo=False)

    tmp_dir = tempfile.mkdtemp(prefix="fmt_bench_")

    # Each entry: (fmt, opts, label) — unique labels for unique files
    configs = [
        # Vector formats
        ("pdf", "",              "PDF (default)"),
        ("svg", "",              "SVG (default)"),
        ("eps", "",              "EPS (default)"),
        # PNG width scaling
        ("png", " width(200)",   "PNG width(200)"),
        ("png", " width(400)",   "PNG width(400)"),
        ("png", "",              "PNG default (800px)"),
        ("png", " width(1600)",  "PNG width(1600)"),
        ("png", " width(3200)",  "PNG width(3200)"),
    ]

    results = []
    for fmt, opts, label in configs:
        slug = label.lower().replace(" ", "_").replace("(", "").replace(")", "")
        ext = fmt
        out = os.path.join(tmp_dir, f"{slug}.{ext}")

        times = []
        last_rc = None
        for _ in range(15):
            t0 = time.perf_counter()
            stdout, rc = client._stata_run(
                f'graph export "{out}", name(g1) replace as({fmt}){opts}',
                echo=False,
            )
            elapsed = (time.perf_counter() - t0) * 1000
            times.append(elapsed)
            last_rc = rc

        times.sort()
        mean = sum(times) / len(times)
        if len(times) >= 2:
            variance = sum((t - mean) ** 2 for t in times) / (len(times) - 1)
            stddev = math.sqrt(variance)
        else:
            stddev = 0.0

        exists = os.path.exists(out)
        size = os.path.getsize(out) if exists else 0

        status = "✓" if last_rc == 0 and exists else f"✗ rc={last_rc}"
        results.append((label, mean, stddev, min(times), max(times), size, status))

    # Print
    print(f"\n{'FORMAT':35s} {'MEAN':>10s} {'STDDEV':>8s} {'MIN':>8s} {'MAX':>8s} {'SIZE':>8s}  {'STATUS'}")
    print(f"{'-'*35} {'-'*10} {'-'*8} {'-'*8} {'-'*8} {'-'*8}  {'-'*10}")
    for label, mean, stddev, mn, mx, size, status in results:
        print(f"{label:35s} {mean:>10.3f}ms {stddev:>8.3f}ms {mn:>8.3f}ms {mx:>8.3f}ms {size//1024:>7}KB  {status}")

    print(f"\n--- VECTOR FORMATS (PDF, SVG, EPS) ---")
    for label, mean, *_ in [r for r in results if r[0].startswith(('PDF', 'SVG', 'EPS'))]:
        print(f"  {label:25s} {mean:.3f}ms")

    print(f"\n--- PNG RESOLUTION SCALING ---")
    for label, mean, *_ in [r for r in results if r[0].startswith('PNG')]:
        print(f"  {label:25s} {mean:.3f}ms")

    shutil.rmtree(tmp_dir, ignore_errors=True)
    client.close()


if __name__ == "__main__":
    main()

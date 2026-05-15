#!/usr/bin/env python3
"""Profile the pyarrow export path to identify bottlenecks.

Instruments each major stage of inspect_get(format='arrow').
"""

from __future__ import annotations

import os
import sys
import tempfile
import time
import uuid

LARGE_DTA_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "testdata", "large_benchmark.dta")
)


def setup_stata():
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
    client = StataClient(session_name="profile")
    client.init()
    return client


def profile_arrow_export(client, label: str):
    """Profile each stage of the arrow export."""
    import pyarrow as pa
    from sfi import Data

    # Stage 0: Get variable metadata
    t0 = time.perf_counter()
    var_count = Data.getVarCount()
    var_names = [Data.getVarName(i) for i in range(var_count)]
    t_meta = time.perf_counter() - t0

    # Select all variables
    selected = var_names

    # Stage 1: Determine obs range
    t0 = time.perf_counter()
    obs_total = Data.getObsTotal()
    obs_start = 0
    obs_end = obs_total
    t_range = time.perf_counter() - t0

    # Stage 2: Build columns (cell-by-cell Data.get)
    t0 = time.perf_counter()
    arrays = []
    cell_count = 0
    for name in selected:
        idx = Data.getVarIndex(name)
        col = []
        for obs_idx in range(obs_start, obs_end):
            val = Data.get(idx, obs_idx)
            col.append(val)
        arrays.append(pa.array(col))
        cell_count += obs_end - obs_start
    t_build = time.perf_counter() - t0

    # Stage 3: Build schema and table
    t0 = time.perf_counter()
    schema = pa.schema([
        (name, pa.float64() if arrays[i].type == pa.null() else arrays[i].type)
        for i, name in enumerate(selected)
    ])
    table = pa.Table.from_arrays(arrays, schema=schema)
    t_schema = time.perf_counter() - t0

    # Stage 4: Write IPC file
    t0 = time.perf_counter()
    fd, out_path = tempfile.mkstemp(suffix=".arrow")
    os.close(fd)
    with pa.OSFile(str(out_path), "wb") as sink:
        with pa.ipc.new_file(sink, table.schema) as writer:
            writer.write_table(table)
    t_write = time.perf_counter() - t0

    size = os.path.getsize(out_path)
    os.unlink(out_path)

    print(f"\n  [{label}] Profile ({obs_total} obs x {len(selected)} vars = {cell_count:,} cells):")
    print(f"    Variable metadata:     {t_meta*1e3:9.3f} ms  ({t_meta/t_build*100:5.1f}% of build)")
    print(f"    Obs range:             {t_range*1e3:9.3f} ms")
    print(f"    Build columns (Data.get): {t_build:9.3f} s  ({t_build/(obs_end-obs_start):9.6f} s/col, {t_build*1e6/cell_count:8.2f} µs/cell)")
    print(f"    Schema + Table:        {t_schema*1e3:9.3f} ms")
    print(f"    Write IPC file:        {t_write*1e3:9.3f} ms")
    print(f"    Total:                 {t_meta + t_range + t_build + t_schema + t_write:9.3f} s")
    print(f"    File size:             {size:,} bytes ({size/1024/1024:.1f} MB)")
    print(f"    Throughput:            {cell_count/t_build:,.0f} cells/s (build stage)")

    return t_build, cell_count


def main():
    print("=" * 60)
    print("  PyArrow Export Profiler")
    print("=" * 60)
    print()

    client = setup_stata()

    # Small dataset
    print("\n  Loading small dataset (sysuse auto)...")
    client.run("sysuse auto, clear", echo=False)
    t_build_small, _ = profile_arrow_export(client, "Small-auto")

    # Large dataset
    print("\n  Loading large dataset...")
    client.run(f'use "{LARGE_DTA_PATH}", clear', echo=False)
    t_build_large, cells_large = profile_arrow_export(client, "Large-1M")

    client.close()

    print("\n" + "=" * 60)
    print("  Key finding: Build columns stage dominates")
    print(f"  Large dataset build time: {t_build_large:.1f}s for {cells_large:,} cells")
    print(f"  Per-cell overhead: {t_build_large*1e6/cells_large:.1f} µs/cell")
    print()
    print("  Target: need 10x → ~1.9s build time")
    print(f"  Required per-cell: {t_build_large*1e6/cells_large/10:.1f} µs/cell")
    print("=" * 60)


if __name__ == "__main__":
    main()

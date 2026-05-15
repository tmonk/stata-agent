#!/usr/bin/env python3
"""Verify correctness of the optimized arrow export path.

Checks:
1. Column names preserved
2. Data values match (spot-check)
3. Missing values handled correctly
4. Round-trip: export → read back via pyarrow → compare values
"""

import os
import sys
import tempfile

LARGE_DTA_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "testdata", "large_benchmark.dta")
)


def setup():
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
    client = StataClient(session_name="correctness")
    client.init()
    return client


def test_roundtrip_small():
    """Test on the small auto dataset."""
    import pyarrow as pa
    import numpy as np

    client = setup()
    from sfi import Data
    client.run("sysuse auto, clear", echo=False)

    # --- Export to arrow using toNPArray ---
    var_count = Data.getVarCount()
    var_names = [Data.getVarName(i) for i in range(var_count)]
    obs_total = Data.getObsTotal()

    arrays = {}
    for name in var_names:
        idx = Data.getVarIndex(name)
        arr = Data.toNPArray(idx)
        arrays[name] = pa.array(arr)

    table = pa.table(arrays)

    # Write to temp file
    out = tempfile.NamedTemporaryFile(suffix=".arrow", delete=False).name
    with pa.OSFile(out, "wb") as sink:
        with pa.ipc.new_file(sink, table.schema) as writer:
            writer.write_table(table)

    # --- Read back ---
    with pa.ipc.open_file(out) as reader:
        restored = reader.read_all()

    os.unlink(out)

    # --- Compare ---
    errors = []

    # Check column names match
    orig_names = set(var_names)
    restored_names = set(restored.column_names)
    if orig_names != restored_names:
        errors.append(f"Column names differ: extra={restored_names - orig_names}, missing={orig_names - restored_names}")

    # Check row count
    if restored.num_rows != obs_total:
        errors.append(f"Row count: expected {obs_total}, got {restored.num_rows}")

    # Spot-check first 10 rows for each column
    import random
    random.seed(42)
    check_rows = list(range(obs_total))
    random.shuffle(check_rows)
    check_rows = sorted(check_rows[:10])

    for name in var_names:
        idx = Data.getVarIndex(name)
        restored_col = restored.column(name)
        for row in check_rows:
            orig_val = Data.get(idx, row)
            restored_val = restored_col[row].as_py()
            # Normalize: Data.get() returns nested single-element lists [[[value]]]
            while isinstance(orig_val, list) and len(orig_val) == 1:
                orig_val = orig_val[0]

            # Helper: is a value a Stata missing sentinel?
            STATA_MISSING = 8.98846567431158e+307
            def _is_missing(v):
                if v is None:
                    return True
                if isinstance(v, float) and (np.isnan(v) or abs(v - STATA_MISSING) < abs(v * 1e-12)):
                    return True
                return False

            if _is_missing(orig_val) and _is_missing(restored_val):
                continue
            if _is_missing(orig_val) != _is_missing(restored_val):
                errors.append(f"Mismatch at {name}[{row}]: orig_missing={_is_missing(orig_val)}, restored_missing={_is_missing(restored_val)}, orig={orig_val!r}, restored={restored_val!r}")
                continue

            # Compare strings directly
            if isinstance(orig_val, str) or isinstance(restored_val, str):
                if str(orig_val).strip() != str(restored_val).strip():
                    errors.append(f"Mismatch at {name}[{row}]: orig={orig_val!r}, restored={restored_val!r}")
                continue

            # Compare numeric with tolerance
            if isinstance(orig_val, (int, float)) and isinstance(restored_val, (int, float)):
                if abs(float(orig_val) - float(restored_val)) > 0.001:
                    errors.append(f"Mismatch at {name}[{row}]: orig={orig_val}, restored={restored_val}")
                continue

            # Fallback: string comparison
            if str(orig_val) != str(restored_val):
                errors.append(f"Mismatch at {name}[{row}]: orig={orig_val!r}, restored={restored_val!r}")

    if errors:
        print(f"  FAILED - {len(errors)} errors:")
        for e in errors[:10]:
            print(f"    {e}")
        return False
    else:
        print(f"  PASSED - {obs_total} rows x {var_count} cols, spot-checked {len(check_rows)} rows")
        return True


def test_missing_values():
    """Test missing value handling specifically."""
    import pyarrow as pa
    import numpy as np

    client = setup()
    from sfi import Data

    # Create a small dataset with known missing values
    client.run("""
        clear
        set obs 10
        gen double x = _n
        replace x = . if _n == 3
        replace x = .a if _n == 7
        gen byte y = _n * 10
        replace y = . if _n == 5
    """, echo=False)

    var_names = ["x", "y"]
    obs_total = Data.getObsTotal()

    arrays = {}
    for name in var_names:
        idx = Data.getVarIndex(name)
        arr = Data.toNPArray(idx)
        arrays[name] = pa.array(arr)

    table = pa.table(arrays)

    out = tempfile.NamedTemporaryFile(suffix=".arrow", delete=False).name
    with pa.OSFile(out, "wb") as sink:
        with pa.ipc.new_file(sink, table.schema) as writer:
            writer.write_table(table)

    with pa.ipc.open_file(out) as reader:
        restored = reader.read_all()
    os.unlink(out)

    STATA_MISSING = 8.98846567431158e+307
    def _is_missing(v):
        if v is None:
            return True
        if isinstance(v, float) and (np.isnan(v) or abs(v - STATA_MISSING) < abs(v * 1e-12)):
            return True
        return False

    errors = []
    for row in range(obs_total):
        for name in var_names:
            idx = Data.getVarIndex(name)
            orig_val = Data.get(idx, row)
            while isinstance(orig_val, list) and len(orig_val) == 1:
                orig_val = orig_val[0]
            restored_val = restored.column(name)[row].as_py()

            if _is_missing(orig_val) and _is_missing(restored_val):
                continue
            if _is_missing(orig_val) != _is_missing(restored_val):
                errors.append(f"Mismatch at {name}[{row}]: orig_missing={_is_missing(orig_val)}, restored_missing={_is_missing(restored_val)}, orig={orig_val!r}, restored={restored_val!r}")
                continue

            if isinstance(orig_val, str) or isinstance(restored_val, str):
                if str(orig_val).strip() != str(restored_val).strip():
                    errors.append(f"Mismatch at {name}[{row}]: orig={orig_val!r}, restored={restored_val!r}")
                continue

            if isinstance(orig_val, (int, float)) and isinstance(restored_val, (int, float)):
                if abs(float(orig_val) - float(restored_val)) > 0.001:
                    errors.append(f"Mismatch at {name}[{row}]: orig={orig_val}, restored={restored_val}")
                continue

            if str(orig_val) != str(restored_val):
                errors.append(f"Mismatch at {name}[{row}]: orig={orig_val!r}, restored={restored_val!r}")

    if errors:
        print(f"  FAILED (missing values) - {len(errors)} errors:")
        for e in errors[:10]:
            print(f"    {e}")
        return False
    else:
        print(f"  PASSED - missing values handled correctly")
        return True


def test_large_roundtrip():
    """Quick spot-check on the large dataset."""
    import pyarrow as pa
    import numpy as np

    client = setup()
    from sfi import Data
    client.run(f'use "{LARGE_DTA_PATH}", clear', echo=False)

    var_count = Data.getVarCount()
    var_names = [Data.getVarName(i) for i in range(var_count)]
    obs_total = Data.getObsTotal()

    arrays = {}
    for name in var_names:
        idx = Data.getVarIndex(name)
        arr = Data.toNPArray(idx)
        arrays[name] = pa.array(arr)

    table = pa.table(arrays)

    out = tempfile.NamedTemporaryFile(suffix=".arrow", delete=False).name
    with pa.OSFile(out, "wb") as sink:
        with pa.ipc.new_file(sink, table.schema) as writer:
            writer.write_table(table)

    with pa.ipc.open_file(out) as reader:
        restored = reader.read_all()
    os.unlink(out)

    errors = []
    if restored.num_rows != obs_total:
        errors.append(f"Row count: expected {obs_total}, got {restored.num_rows}")

    restored_names = set(restored.column_names)
    orig_names = set(var_names)
    if orig_names != restored_names:
        errors.append(f"Column diff: extra={restored_names - orig_names}, missing={orig_names - restored_names}")

    # Spot-check: first, middle, last row for a few columns
    check_cols = var_names[:3]  # Check first 3 columns only
    check_rows = [0, obs_total // 2, obs_total - 1] if obs_total > 2 else [0]

    STATA_MISSING = 8.98846567431158e+307
    def _is_missing(v):
        if v is None:
            return True
        if isinstance(v, float) and (np.isnan(v) or abs(v - STATA_MISSING) < abs(v * 1e-12)):
            return True
        return False

    for name in check_cols:
        idx = Data.getVarIndex(name)
        restored_col = restored.column(name)
        for row in check_rows:
            orig_val = Data.get(idx, row)
            while isinstance(orig_val, list) and len(orig_val) == 1:
                orig_val = orig_val[0]
            restored_val = restored_col[row].as_py()

            if _is_missing(orig_val) and _is_missing(restored_val):
                continue
            if _is_missing(orig_val) != _is_missing(restored_val):
                errors.append(f"Mismatch at {name}[{row}]: orig_missing={_is_missing(orig_val)}, restored_missing={_is_missing(restored_val)}, orig={orig_val!r}, restored={restored_val!r}")
                continue

            if isinstance(orig_val, (int, float)) and isinstance(restored_val, (int, float)):
                if abs(float(orig_val) - float(restored_val)) > 0.001:
                    errors.append(f"Mismatch at {name}[{row}]: orig={orig_val}, restored={restored_val}")

    if errors:
        print(f"  FAILED - {len(errors)} errors:")
        for e in errors[:10]:
            print(f"    {e}")
        return False
    else:
        print(f"  PASSED - {obs_total} rows x {var_count} cols, spot-checked {len(check_cols)} cols x {len(check_rows)} rows")
        return True


if __name__ == "__main__":
    print("=== Correctness Tests for toNPArray Arrow Export ===\n")
    ok = True

    print("--- Small dataset round-trip ---")
    ok &= test_roundtrip_small()

    print("\n--- Missing values ---")
    ok &= test_missing_values()

    print("\n--- Large dataset spot-check ---")
    ok &= test_large_roundtrip()

    print(f"\n{'='*50}")
    print(f"{'ALL PASSED' if ok else 'SOME FAILED'}")

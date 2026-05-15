#!/usr/bin/env python3
"""Generate a large synthetic Stata dataset for benchmarking.

Creates a dataset with ~1,000,000 observations and ~20 columns
(mixed numeric types) and saves it to disk as a .dta file.

Usage:
    uv run python benchmarks/create_large_dataset.py
    # or
    python benchmarks/create_large_dataset.py
"""

from __future__ import annotations

import os
import sys
import time

# Number of observations
N = 1_000_000
OUTPUT = os.path.abspath(os.path.join(
    os.path.dirname(__file__), "..", "testdata", "large_benchmark.dta"
))

STATA_CODE = f"""
clear all
set obs {N}
set seed 42

* --- Integer variables ---
gen double  id        = _n
gen int     mpg       = round(uniform() * 30 + 10)
gen int     cylinders = round(uniform() * 4 + 4)
gen int     rep78     = round(uniform() * 4 + 1)
gen long    population = round(uniform() * 1000000 + 10000)
gen byte    gear      = round(uniform() * 3 + 3)

* --- Float variables ---
gen double  price     = uniform() * 50000 + 3000
gen double  weight    = uniform() * 3000 + 1500
gen double  length    = uniform() * 100 + 150
gen double  displacement = uniform() * 300 + 50
gen double  mpg_city  = uniform() * 20 + 10
gen double  highway   = uniform() * 15 + 20
gen double  tax       = uniform() * 2000 + 100
gen double  profit    = runiform() * 10000 - 2000
gen double  debt      = uniform() * 50000

* --- Float with missing ---
gen double  bonus     = uniform() * 10000
replace bonus = . if mod(_n, 20) == 0

* --- Int with missing ---
gen int     score     = round(uniform() * 100)
replace score = . if mod(_n, 15) == 0

* --- Categorical (numeric encoding) ---
gen byte    category  = round(uniform() * 4 + 1)
gen byte    region    = round(uniform() * 3 + 1)

label variable id           "Unique identifier"
label variable mpg          "Miles per gallon"
label variable cylinders    "Number of cylinders"
label variable rep78        "Repair record 1978"
label variable population   "Population (thousands)"
label variable gear         "Number of gears"
label variable price        "Price (USD)"
label variable weight       "Weight (lbs)"
label variable length       "Length (inches)"
label variable displacement "Engine displacement (cu in)"
label variable mpg_city     "City MPG"
label variable highway      "Highway MPG"
label variable tax          "Tax (USD)"
label variable profit       "Profit margin (USD)"
label variable debt         "Debt (USD)"
label variable bonus        "Bonus (USD)"
label variable score        "Score (0-100)"
label variable category     "Category (1-5)"
label variable region       "Region (1-4)"

* Compress to save space
compress

* Save
save "{OUTPUT}", replace

* Summary
describe
summarize
display "Rows: " _N
display "Cols: " c(k)
"""


def main():
    print(f"Generating {N:,} observations x 20 columns...")
    print(f"Output: {OUTPUT}")
    print()

    # Ensure testdata dir exists
    os.makedirs(os.path.dirname(OUTPUT), exist_ok=True)

    # Set up Stata from Python, run the code
    sys.path.insert(0, "/Applications/StataNow/utilities")
    from pystata_x.stata_setup import config as px_setup_config
    from stata_agent.discovery import find_stata_path

    path, edition = find_stata_path()
    edition = edition.lower()
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

    px_setup_config(root, edition, splash=False)

    from stata_agent.stata_client import StataClient
    client = StataClient(session_name="create_large_dataset")
    client.init()

    t0 = time.time()
    result = client.run(STATA_CODE, echo=False)
    elapsed = time.time() - t0

    if result.ok:
        file_size = os.path.getsize(OUTPUT)
        print(f"Done! {elapsed:.2f}s")
        print(f"File: {OUTPUT} ({file_size:,} bytes, {file_size/1024/1024:.1f} MB)")
    else:
        print(f"FAILED (rc={result.rc})")
        print(result.stdout[:2000] if result.stdout else "No output")

    client.close()


if __name__ == "__main__":
    main()

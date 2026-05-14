# Graph Detection Flow Optimization

> Completed 2026-05-14

## Problem

The graph detection flow in `StataClient.run()`/`run_file()` adds ~95µs overhead
per invocation — over 100% overhead on simple commands like `display 1+1` (which
takes ~10µs without graph tracking).

The flow:
1. Execute user code via `pystata_x._core.execute()` (1 StataSO_Execute call)
2. Call `snapshot_graphs()` which runs `quietly graph dir, memory` (2nd StataSO_Execute call)
3. Read `r(list)` via SFI `Macro.getGlobal()`
4. Compute set difference against cached "before" state

## Baseline Cost Breakdown

Measured via `time.perf_counter()`, 2000 samples each, with 2 graphs in memory:

| Component | Cost (µs) | % of total |
|-----------|-----------|------------|
| `execute("display 1+1")` (user code) | 4.9 | 5% |
| `_stata_run_internal("graph dir, memory")` | 88.2 | 93% |
| SFI `Macro.getGlobal("r(list)")` | 0.3 | <1% |
| Python set creation + split | 0.2 | <1% |
| `compute_graph_delta()` | 0.4 | <1% |
| **Total graph overhead** | **~95** | 100% |

Scenarios:
- **No graphs**: `snapshot_graphs()` = 60.3µs (cheaper because no r(list) returned)
- **1-2 graphs**: `snapshot_graphs()` = ~88-90µs
- **Unnamed graphs**: Same cost — graph dir still enumerates "Graph"
- **Cached state (repeated call)**: Same cost — graph dir always runs

**Conclusion: 98% of graph detection cost is the `graph dir, memory` Stata command
itself. Everything else (set diff, SFI macro read, split) totals < 1µs.**

## Approaches Explored

### A. Bundled execute() — ✓ Implemented

Modify `pystata_x._core.execute()` to accept `track_graphs=True`. After executing
the user's main code, use the already-resolved runtime (`stlib`, `encode`) to
directly call `StataSO_Execute(b"quietly graph dir, memory", 0)` and read
`r(list)` via SFI — all in one function, avoiding a separate Python dispatch.

**Result**: 84µs overhead (down from 95µs). Saves ~11µs of Python dispatch
overhead. The Stata command itself still runs.

Files changed:
- `pystata_x/_core.py`: Added `track_graphs` param, `_query_graph_names()` helper,
  `ExecuteResult` result type
- `pystata_x/__init__.py`: Export `ExecuteResult`
- `stata_agent/stata_client.py`: `run()`/`run_file()` use bundled execute

### B. Combined StataSO_Execute — ✗ Rejected

Append `\nquietly graph dir, memory` to the user's code and run both in a
single `StataSO_Execute` call.

**Result**: 170µs — MUCH slower. The combined command triggers the multi-line
(temp do-file) code path, adding file I/O overhead.

### C. Direct ctypes to internal libstata symbols — ✗ Not viable

Try calling `_ti__gr_list_cmd` (the internal graph list command handler) via
dlsym. This symbol is local (not exported), so `dlsym` can't find it by name.
The Stata C API only exports `StataSO_*` functions, none of which provide
graph enumeration without running a Stata command.

### D. Zero-cost default (track_graphs=False) — ✓ Implemented

Changed the default value of `track_graphs` from `True` to `False` in both
`StataClient.run()` and `StataClient.run_file()`. The CLI explicitly passes
`track_graphs=True` to preserve user-facing graph display.

**Result**: For programmatic callers (AI agents), graph detection costs exactly
0µs. This is the biggest win.

## Selected Solution

**Combination of A + D**: Bundled execute() + zero-cost default.

- Default `track_graphs=False`: 0µs overhead for most callers
- Opt-in `track_graphs=True`: 84µs overhead (down from 95µs) via bundled execute()

## Benchmark Results

```
                                         Before       After      Change
run() track_graphs=False                  10.7us      11.4us      +0.7us
run() track_graphs=True                  105.6us      95.5us      -9.7us
Graph detection overhead                  94.9us      84.2us     -11.3us (11% improvement)
```

Full benchmark run: `./tests/benchmarks/run_benchmarks.sh`

## Files Changed

### pystata-x (`/Users/tom/projects/pystata-x/`)

- `src/pystata_x/_core.py`:
  - Added `ExecuteResult` tuple subclass (output, rc, graph_names)
  - Added `_query_graph_names()` helper
  - Modified `execute()` to accept `track_graphs` param
  - Modified `run()` to use `ExecuteResult`
- `src/pystata_x/__init__.py`: Export `ExecuteResult`

### stata-agent (`/Users/tom/projects/stata-agent/`)

- `src/stata_agent/stata_client.py`:
  - Changed `run()` default: `track_graphs=True` → `False`
  - Changed `run_file()` default: stays `False`
  - Both use `execute(code, track_graphs=t)` instead of separate calls
  - `snapshot_graphs()` simplified to use direct StataSO calls
  - Removed `_stata_run_internal()` (no longer needed)
- `src/stata_agent/worker.py`: Change `track_graphs` default from `True` to `False`
- `src/stata_agent/cli.py`: Explicitly pass `track_graphs=True` in RPC call
- `tests/unit/test_cli_handlers.py`: Updated expected RPC call args
- `tests/benchmarks/test_benchmark_graph_operations.py`: Added track_graphs benchmarks
- `tests/benchmarks/run_real_benchmarks.py`: Added track_graphs benchmarks

## Why Diffing Is Optimal

The cost of the diffing itself (set operations + sorting) is < 1µs. The ~84µs
cost is the Stata `graph dir, memory` command — this is the unavoidable minimum
to enumerate graphs from Stata's internal state. There is no public C API to
access Stata's graph table directly.

For the diffing approach:
- **Before**: Cached set from previous `run()` (free, already in memory)
- **After**: `graph dir, memory` query (84µs, unavoidable)
- **Delta**: Set difference + sort (< 1µs, essentially free)

Caching the "after" state as the next "before" saves one `graph dir` call per
invocation (from 2 to 1), halving the naive approach.

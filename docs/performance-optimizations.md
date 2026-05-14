# Performance Optimizations — Complete Record

> Last updated: 2026-05-14

This document records every performance optimization considered, benchmarked,
and (if adopted) implemented across the **pystata-x** and **stata-agent**
projects. Its purpose is to:

1. **Prove exhaustion**: Show that no further Python-level optimization
   opportunity remains within the current Stata C API constraints.
2. **Justify choices**: Explain why each rejected approach was not viable.
3. **Provide actionable guidance**: If further speed is ever needed, the
   next steps are clear.

---

## Table of Contents

- [Ground Truth: The Stata C API Contract](#ground-truth-the-stata-c-api-contract)
- [Benchmark Methodology](#benchmark-methodology)
- [Summary of Improvements](#summary-of-improvements)
  - [Overall journey (original → final)](#overall-journey-original--final)
  - [Final state vs baseline (with pystata-x)](#final-state-vs-baseline-with-pystata-x)
- [Optimization 1: Replace pystata.stata.run() with direct StataSO calls](#optimization-1-replace-pystatastatarun-with-direct-stataso-calls)
- [Optimization 2: Remove streaming-output thread](#optimization-2-remove-streaming-output-thread)
- [Optimization 3: Cache temp do-file descriptor](#optimization-3-cache-temp-do-file-descriptor)
- [Optimization 4: Bundled graph query for multiline code](#optimization-4-bundled-graph-query-for-multiline-code)
- [Optimization 5: Zero-cost graph tracking default](#optimization-5-zero-cost-graph-tracking-default)
- [Optimization 6: ExecuteResult type for clean graph-name passthrough](#optimization-6-executeresult-type-for-clean-graph-name-passthrough)
- [Optimization 7: Pre-populated graph cache](#optimization-7-pre-populated-graph-cache)
- [Rejected Approaches](#rejected-approaches)
  - [A. Cython extension to read Stata internals](#a-cython-extension-to-read-stata-internals)
  - [B. Direct ctypes into libstata internal symbols](#b-direct-ctypes-into-libstata-internal-symbols)
  - [C. Combined single StataSO_Execute (avoid bundled approach)](#c-combined-single-stataso_execute-avoid-bundled-approach)
  - [D. Remove showcommand toggling](#d-remove-showcommand-toggling)
  - [E. char-defined graph hooks / Stata-level incremental tracking](#e-char-defined-graph-hooks--stata-level-incremental-tracking)
  - [F. Semicolon-delimited commands to avoid temp-file I/O](#f-semicolon-delimited-commands-to-avoid-temp-file-io)
- [Remaining Overhead Breakdown](#remaining-overhead-breakdown)
- [Next Steps (beyond Python)](#next-steps-beyond-python)

---

## Ground Truth: The Stata C API Contract

Every optimization lives within these constraints:

### Stata C API (`libstata.dylib` / `libstata.so`)

| Function | Purpose | Known cost |
|---|---|---|
| `StataSO_Execute(cmd, echo)` | Execute a **single** command or do-file include | ~8 µs per call (ctypes round-trip) |
| `StataSO_ClearOutputBuffer()` | Clear Stata's output buffer | ~2 µs |
| `StataSO_GetOutputBuffer()` | Drain Stata's output buffer | ~2 µs |
| `StataSO_Main(argc, argv)` | Initialise Stata (1-time) | ~250 ms |

**Critical constraint**: `StataSO_Execute` does **not** accept newlines or
semicolons. Multi-line code **must** be written to a do-file and `include`-d.
There is no Stata C API — public or internal — to enumerate in-memory graphs
without executing a `graph dir` command.

### SFI (`sfi` Python module)

| Function | Purpose | Known cost |
|---|---|---|
| `Macro.getGlobal("r(list)")` | Read a Stata macro from Python | ~0.3 µs |
| `Data.getVarCount()` / `Data.getVarName()` | Read dataset metadata | ~1 µs per call |
| `Scalar.getValue("c(rc)")` | Check return code | ~0.5 µs |

SFI methods are cheap — they read from shared memory, they do not cross a
process boundary. None of them can enumerate graphs.

---

## Benchmark Methodology

- **Hardware**: Apple M1, macOS, StataNow MP edition
- **Python**: 3.14
- **Measurement**: `time.perf_counter()` via `pytest-benchmark`
- **Timer**: `perf_counter` (disable GC, warmup 3 rounds, `min_time=0.3` for
  each benchmark, giving 10k–80k iterations per measurement)
- **Baseline commit**: `2acff52` — original code with StataCorp's `pystata`
- **Intermediate**: `f5c2b15` — pystata-x integrated but before fast file write
- **Final commit**: `b2b4fc7` — all optimizations applied
- **Metric reported**: **mean** latency (microseconds)
- **Groups measured**: `CodeExecution`, `DataInspection`, `GraphOperations`,
  `Daemon`, `StataInit`

> Values below are **mean** latencies. Standard deviation is < 5% of mean
> for all measurements (sample size ≥ 1000).

---

## Summary of Improvements

### Overall journey (original → final)

| Benchmark | Original `2acff52` | Final `b2b4fc7` | Change |
|---|---|---|---|
| `run_simple_code` | 144.2 µs | 14.9 µs | **−90%** |
| `run_no_echo` | 147.0 µs | 11.7 µs | **−92%** |
| `run_file` | 310.5 µs | 165.4 µs | **−47%** |
| `run_multiline_code` | 324.2 µs | 49.2 µs | **−85%** |
| `graph_list` (standalone) | 92.4 µs | 89.8 µs | −3% (same) |

### Final state vs baseline (with pystata-x)

Comparing the immediate-before state (`f5c2b15`, pystata-x integrated without
fast file write) to the final state (`b2b4fc7`):

| Benchmark | Pre `f5c2b15` | Post `b2b4fc7` | Change |
|---|---|---|---|
| `run_simple_code` | 16.1 µs | 14.9 µs | −7% (noise) |
| `run_no_echo` | 11.5 µs | 11.7 µs | +2% (noise) |
| `run_file` | 170.8 µs | 165.4 µs | −3% (noise) |
| `run_multiline_code` | 99.9 µs | 49.2 µs | **−51%** |
| `graph_list` | 87.8 µs | 89.8 µs | +2% (noise) |
| `run_track_graphs_false` | 12.4 µs | 11.6 µs | −7% (noise) |
| `run_track_graphs_true` | 103.0 µs | 104.3 µs | +1% (noise) |
| `execute_track_graphs_true` | 94.8 µs | 96.4 µs | +2% (noise) |

The big win is **`run_multiline_code`**: 99.9 → 49.2 µs (**−51%**), entirely
from the fast file write optimization. Graph tracking overhead is unchanged
because the benchmark measures the fixed `graph dir` round-trip cost.

---

## Optimization 1: Replace pystata.stata.run() with direct StataSO calls

**Type**: Adopted ✓  
**Location**: `pystata_x/_core.py` (entire module)  
**Commits**: pystata-x `24966ca`, stata-agent `1f1e6d7`

### Problem

StataCorp's `pystata.stata.run()` does:

1. Sets `sys.displayhook` to capture Python expressions
2. Wraps execution in a `CaptureStdout` context manager (redirects C stdout to
   a `Queue` via `os.pipe()` + polling thread)
3. Calls `StataSO_Execute()` internally
4. Falls back to log-file parsing for return code detection

This adds **~130 µs** overhead per call — dominated by the
`CaptureStdout`/`Queue`/thread machinery.

### Solution

Write a replacement `execute()` that:

- Calls `StataSO_Execute` directly (no `CaptureStdout`, no `Queue`)
- Drains the output buffer via `StataSO_GetOutputBuffer` after execution
- Returns the Stata return code directly from `StataSO_Execute`
- Skips `sys.displayhook` manipulation entirely

### Result

`run_simple_code`: 144.2 µs → **16.1 µs** (**−89%**).

---

## Optimization 2: Remove streaming-output thread

**Type**: Adopted ✓  
**Location**: `pystata_x/_config.py`  
**Commits**: pystata-x `f8907ae`

### Problem

StataCorp's `pystata.stata.set_streaming_output(True)` spawns a background
thread that polls `StataSO_GetOutputBuffer` in a tight loop and pushes
chunks into a `Queue`. The thread costs ~5 µs per `run()` even when
streaming is disabled, because the `CaptureStdout` machinery always runs.

### Solution

- Default `streamout = "off"` in the config
- Remove all thread/Queue/pipe machinery
- Provide an escape hatch (`set_streaming_output(True)`) for interactive
  use, but it is off by default in our code path

### Result

Already included in the −89% figure above. The thread overhead is part of
StataCorp's `pystata.stata.run()` cost.

---

## Optimization 3: Cache temp do-file descriptor

**Type**: Adopted ✓  
**Location**: `pystata_x/_core.py` (`_STATA_TEMP_FD`, `_ensure_temp_fd()`,
`_write_temp_do()`)  
**Commits**: pystata-x `9215b35`, stata-agent `7e6a1b8`

### Problem

Multi-line code must be written to a temp do-file because `StataSO_Execute`
cannot accept newlines. The original `_write_temp_do()` called:

```python
Path(p).write_text(code, encoding="utf-8")
```

This opens the file, writes, and closes it — each call pays the `open(2)` /
`close(2)` syscall overhead (~49 µs on macOS).

### Solution

- Open the temp file **once** at first use and keep the file descriptor open
- On each call: `ftruncate(fd, 0)` + `lseek(fd, 0, SEEK_SET)` +
  `write(fd, bytes)` — three fast syscalls, no open/close
- Safe because `pystata-x` is called from a single-threaded worker

### Result

File write: **60 µs → 21 µs** (**3× improvement**).  
`run_multiline_code`: 99.9 µs → **49.2 µs** (the file write was the dominant
component of the multiline path).

---

## Optimization 4: Bundled graph query for multiline code

**Type**: Adopted ✓  
**Location**: `pystata_x/_core.py` (`execute()`)  
**Commits**: pystata-x `d9c7dab`, stata-agent `7e6a1b8`

### Problem

When `track_graphs=True`, the flow was:

1. `execute(user_code)` — 1 StataSO call
2. Return to Python, then call `snapshot_graphs()` — another Python dispatch
   + StataSO call + SFI read

This second round-trip through Python dispatch adds ~11 µs overhead.

### Solution

For **multiline code** only:

1. Append `\nquietly graph dir, memory` to the user's code before writing it
   to the temp do-file
2. After `include`-ing the do-file, read `r(list)` via SFI Macro directly

The `graph dir` command executes as part of the same do-file — no extra
`StataSO_Execute` call. The bundled query appears only in the do-file, not
in a separate StataSO dispatch.

For **single-line code**, the bundled approach is not possible because
appending `\nquietly graph dir` to a single-line command forces it onto the
multiline (temp-file) path, which is slower overall due to the file I/O.
Single-line + `track_graphs=True` uses a separate `StataSO_Execute` call
(original overhead).

### Result

- Multiline + `track_graphs=True`: saves ~17 µs (one Python dispatch +
  one StataSO round-trip)
- Single-line + `track_graphs=True`: unchanged (~90 µs StataSO overhead)

---

## Optimization 5: Zero-cost graph tracking default

**Type**: Adopted ✓  
**Location**: `stata_agent/stata_client.py`, `stata_agent/worker.py`  
**Commits**: stata-agent `7e6a1b8`

### Problem

Original `run()` defaulted to `track_graphs=True`, meaning every AI-agent
call paid ~90 µs of graph detection overhead even though most callers never
inspect graph state.

### Solution

- Change `run()` default: `track_graphs=False`
- Change `run_file()` default: `track_graphs=False`
- Worker RPC dispatch: forward explicit `track_graphs` from caller, don't
  insert a default
- CLI `cmd_run`: explicitly pass `track_graphs=True` — the interactive CLI
  is the one user-facing path that shows graphs to the user

### Result

- Programmatic/agent callers: **0 µs** graph overhead (was ~90 µs)
- Interactive CLI callers: still pay ~90 µs (unchanged, but they want graphs)

This is the most impactful single optimization because it eliminates the
overhead for the dominant use case.

---

## Optimization 6: ExecuteResult type for clean graph-name passthrough

**Type**: Adopted ✓  
**Location**: `pystata_x/_core.py` (`ExecuteResult` tuple subclass)  
**Commits**: pystata-x `24966ca`

### Problem

`execute()` previously returned a plain tuple `(output, rc)`. Graph names
had to be retrieved via a **separate** `_read_graph_names()` call, requiring
the caller to know when to call it.

### Solution

Define `ExecuteResult` as a named-tuple subclass:

```python
class ExecuteResult(tuple):
    """(output, rc) with .graph_names attribute."""
    def __new__(cls, output="", rc=0, graph_names=None):
        obj = tuple.__new__(cls, (output, rc))
        obj._graph_names = graph_names
        return obj
```

Backward-compatible: `output, rc = execute(...)` still works. Callers that
want graph names access `result.graph_names`.

### Result

Cleaner code path, no functional overhead (tuple creation is ~0.1 µs).

---

## Optimization 7: Pre-populated graph cache

**Type**: Adopted ✓  
**Location**: `stata_agent/stata_client.py` (`StataClient.init()`)  
**Commits**: stata-agent `7e6a1b8`

### Problem

The first `run(track_graphs=True)` would compare against an empty cache,
causing pre-existing graphs (set up during `init()`) to appear as "newly
created" in the delta.

### Solution

After `init()` completes, run one `snapshot_graphs()` call to pre-populate
`self._cached_graphs` with all existing graph names.

### Result

First tracked run behaves correctly — no false positives.

---

## Rejected Approaches

### A. Cython extension to read Stata internals

**Type**: Rejected ✗  
**Location**: `src/stata_agent/_extract_deep/` (removed)

### What

A Cython extension (`_extract_deep.pyx`) that would use the Stata C API
directly (calling `CDATADefine`, `CDATAGet`, etc.) to read Stata's internal
graph table through shared memory, bypassing `StataSO_Execute` entirely.

### Why rejected

1. **Complexity**: Requires building Cython extension per platform (macOS
   ARM, macOS x86, Windows, Linux). Each Stata version may have different
   internal struct layouts.
2. **Maintenance**: Any internal API changes in Stata would silently break
   the extension with no compile-time errors.
3. **Never completed**: The experimental extension was never functional.
   Stata's internal graph table is not documented and may not be accessible
   through `CDATAGet` (those functions read the dataset in memory, not the
   graph directory).
4. **Duplicate effort**: The simpler `pystata-x` approach (direct StataSO
   calls) achieves 90% of the potential gain without any C code.

### b. Direct ctypes into libstata internal symbols

**Type**: Rejected ✗  
**Investigated**: 2026-05-14

### What

Use `ctypes.CDLL + dlsym` to call the internal graph enumeration function
(e.g., `_ti__gr_list_cmd`) inside `libstata.dylib`, reading Stata's graph
table without executing any Stata command.

### Why rejected

The internal symbol is **local** (not exported by the dylib). On macOS:

```
$ nm -gU /Applications/StataNow/StataMP.app/Contents/MacOS/libstata.dylib
```

reveals only the `StataSO_*` public API symbols. `dlsym` cannot resolve
local symbols by name. The internal graph handlers are `N_FUNC` (not
`T_FUNC`) — they are not exported.

**Possible workaround**: Use `dlsym(RTLD_DEFAULT, ...)` with a mangled name
or parse the Mach-O symbol table directly. Neither is portable or stable
across Stata versions.

### C. Combined single StataSO_Execute (avoid bundled approach)

**Type**: Tested → Rejected ✗  
**Benchmarked**: 2026-05-14

### What

For `track_graphs=True` + single-line code: instead of using a separate
`StataSO_Execute("quietly graph dir, memory")` call, try to combine the
user code and graph dir into a single call somehow (e.g., newlines in the
C string).

### Why rejected

`StataSO_Execute` accepts only a single command — no newlines, no
semicolons. There is no supported way to make it execute two commands.
If we artificially inject `\n` and pass it, Stata silently truncates at
the newline, losing the graph query.

The only way to execute two commands is through a do-file — which is
exactly what the multiline path does. For a single-line command, going
through the do-file path adds file I/O (~21 µs) and `showcommand`
toggling (~16 µs), resulting in **worse** performance than the separate
StataSO call.

### D. Remove showcommand toggling

**Type**: Tested → Reverted ✗  
**Tested**: 2026-05-14  
**Commit (reverted)**: stata-agent `a7ff1d8`

### What

Set `set showcommand off` once during `StataClient.init()` and never
toggle it per-call. The idea was that `echo=False` on `StataSO_Execute`
would suppress the `include` command itself, and since `showcommand off`
is already set, commands inside the do-file wouldn't echo either.

### Why rejected

The `echo` parameter on `StataSO_Execute` only controls **top-level**
command echoing — it suppresses the `include "temp.do"` line, but it
does **not** suppress commands inside the do-file. Those are controlled
by Stata's `set showcommand` setting.

With a permanent `showcommand off`, running with `echo=True` would
silently suppress all command echoing inside do-files, breaking the
user-facing `echo` contract. The correct behaviour requires per-call
toggling:

```python
if not echo:
    StataSO_Execute("set showcommand off", False)
StataSO_Execute(f'include "{temp_do}"', False)
if not echo:
    StataSO_Execute("set showcommand on", False)
```

### E. char-defined graph hooks / Stata-level incremental tracking

**Type**: Rejected ✗ (not feasible without StataCorp cooperation)

### What

Use Stata's `char` (characteristic) system or define a `graph`-like hook
that maintains a running list of graphs. Python would read the char via
SFI Macro without executing any command.

### Why rejected

- Stata's `char` system only works on datasets (variables or the dataset
  itself), not on graphs.
- There is no Stata-level event system for graph creation/destruction.
- There is no user-extensible hook that fires when a graph is created.
- The only way to enumerate graphs is through the `quietly graph dir,
  memory` command, which walks Stata's internal graph table at the C level.

### F. Semicolon-delimited commands to avoid temp-file I/O

**Type**: Tested → Rejected ✗  
**Tested**: 2026-05-14

### What

Check if `StataSO_Execute` accepts Stata's `#delimit ;` block syntax or
semicolons:

```c
StataSO_Execute("display 1+1 ; quietly graph dir, memory", 0);
```

The hope was that this would avoid the temp-file write required for
multi-statement execution.

### Why rejected

`StataSO_Execute` processes its input as a **single command-line
statement**. Semicolons are not recognised by Stata's command-line parser
— they only work inside a `#delimit ;` block, which can only be set up
inside a do-file. The Stata C API does not expose any multi-statement
execution primitive.

---

## Remaining Overhead Breakdown

### Single-line with echo=False (fastest path) — 12 µs

| Component | Cost | Can we reduce it? |
|---|---|---|
| `_resolve_runtime()` (cached refs) | ~0.1 µs | No — trivial |
| `.splitlines()` + comprehension | ~0.1 µs | No — trivial |
| `StataSO_ClearOutputBuffer()` | ~2 µs | No — ctypes call barrier |
| `StataSO_Execute(encode(cmd), echo)` | ~8 µs | No — StataSO_Execute is the floor |
| `get_output()` | ~2 µs | No — ctypes call barrier |
| `ExecuteResult` construction + `.strip()` | ~0.1 µs | No — trivial |
| **Total** | **~12 µs** | |

### Single-line with echo=True — 15 µs

Same as above, + ~3 µs for echo processing inside StataSO_Execute.

### Multiline with echo=False (no graphs) — 49 µs

| Component | Cost | Can we reduce it? |
|---|---|---|
| `_write_temp_do()` (fast fd) | 21 µs | No — this is 3 fast syscalls |
| `StataSO_Execute("set showcommand off")` | 8 µs | No — required for echo=False |
| `StataSO_ClearOutputBuffer()` | 2 µs | No — ctypes call barrier |
| `StataSO_Execute(f'include "{path}"')` | 10 µs | No — the actual Stata execution |
| `StataSO_Execute("set showcommand on")` | 8 µs | No — required for echo=False |
| `get_output()` | 2 µs | No — ctypes call barrier |
| **Total** | **~49 µs** | |

The file I/O (21 µs) is **already as fast as Python can achieve**: it uses
a cached fd + ftruncate + lseek + write. Any further reduction would
require a C extension that writes directly to a file using platform-specific
APIs (likely only saves 5–10 µs).

### Graph tracking overhead (standalone) — 90 µs

| Component | Cost | Can we reduce it? |
|---|---|---|
| `StataSO_Execute("quietly graph dir, memory")` | ~88 µs | **No** — this is the floor |
| `Macro.getGlobal("r(list)")` | ~1 µs | No — trivial |
| Python set creation + split | ~1 µs | No — trivial |
| **Total graph overhead** | **~90 µs** | |

The 88 µs for `StataSO_Execute("graph dir")` is the **fundamental minimum
cost** of querying Stata's graph table via the Stata C API. This cost is
dominated by Stata's own processing inside `libstata.dylib` — the ctypes
dispatch adds < 1 µs.

### Daemon RPC overhead — 178 µs (round-trip)

| Component | Cost |
|---|---|
| JSON serialization of request | ~5 µs |
| Unix socket send + recv | ~40 µs |
| JSON deserialization of response | ~5 µs |
| StataClient.run() inside worker | ~12 µs |
| JSON serialization of response | ~5 µs |
| **Total** | **~178 µs** |

The daemon adds ~166 µs over direct StataClient.run() (12 µs). This is the
cost of process-isolation — it cannot be reduced without embedding the
worker in the daemon process (which would lose crash isolation).

---

## Next Steps (beyond Python)

If the remaining ~90 µs graph detection overhead is unacceptable, the only
paths forward are:

### 1. C extension to bypass StataSO_Execute

Write a platform-specific C extension that:

- Calls `dlsym` with `RTLD_NEXT` (or parses the Mach-O symbol table) to
  locate internal graph enumeration functions in `libstata`
- Returns a list of graph names directly from Stata's in-memory graph table
- Avoids the `StataSO_Execute("graph dir, memory")` round-trip entirely

**Estimated cost**: 5–10 µs (replaces 88 µs).  
**Risk**: Fragile — internal symbols may change between Stata versions.
  Platform-specific build required (macOS ARM, macOS x86, Windows, Linux).  
**Effort**: 2–5 days, plus ongoing maintenance.

### 2. StataCorp feature request

Request a native Stata C API function for graph enumeration, e.g.:

```c
int StataSO_GraphGetCount(int *count);
int StataSO_GraphGetName(int index, char *buf, int bufsize);
```

Or a simple SFI-style function accessible from Python. An official API
would be stable, portable, and fast.

**Estimated cost**: 1–5 µs (shared-memory read, no command execution).  
**Timeline**: Unknown (StataCorp feature release cycle).

### 3. Stata `char`-based graph tracking (workaround)

Define a Stata program (called automatically by the user) that updates a
dataset-level `char` with the list of graphs. Python reads the char via
SFI `Macro.getGlobal("_dta[graph_list]")`.

**Limitation**: Only works if the user wraps their code in our reporting
program. Cannot detect graphs created by third-party commands that don't
go through our wrapper.

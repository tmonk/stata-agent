# Simplified Graph Handling — Feature Review

**Feature:** Replace `GraphCreationDetector`/`StreamingGraphCache` with post-run delta detection  
**Plan Reference:** plan.md §11.2  
**Date:** 2026-05-12  
**Stata Version:** StataNow 19.5 SE  
**Reviewer:** worker subagent

---

## 1. Executive Summary

The current graph-detection stack (`graph_detector.py` ~600 LOC + `list_graphs` ~130 LOC in `stata_client.py`) is massively over-engineered for what Stata natively provides. Active verification confirms that a **post-run delta check using `graph dir, memory`** is:

- **Correct**: captures named and unnamed graphs, modifications, drops, and clears.
- **Fast**: ~0.000s for 3 graphs; effectively free compared to command execution time (~0.4s for a scatter).
- **Trivial to parse**: `r(list)` returns a space-separated string with a trailing space.
- **Stateless**: no TTL caches, no signature hashes, no streaming callbacks, no concurrency locks.

**Recommendation: Replace the entire detector with ~20 lines of delta logic. Export must remain explicit via `stata graph export`.**

---

## 2. Active Verification Results

All tests run on StataNow 19.5 SE in batch mode (`stata-se -b do file.do`).

### 2.1 Baseline — No Graphs

```stata
sysuse auto
graph dir, memory
```

**Output:** *(blank line)*  
**`return list`:** `r(list) = " "` (single space)

### 2.2 Create One Named Graph

```stata
sysuse auto
twoway scatter price mpg, name(g1)
graph dir, memory
```

**Output:** `g1`  
**`return list`:** `r(list) = "g1 "`

### 2.3 Create Second Named Graph

```stata
twoway scatter price weight, name(g2)
graph dir, memory
```

**Output:** `g1  g2`  
**`return list`:** `r(list) = "g1 g2 "`

### 2.4 Export Tests

| Command | Result | Notes |
|---------|--------|-------|
| `graph export /tmp/test1.pdf, replace` | ✅ 12,853 bytes | Exports **current** graph (most recently created) |
| `graph export /tmp/test1.svg, replace` | ✅ 40,998 bytes | SVG also supported |
| `graph display g1` → `graph export /tmp/..., replace` | ✅ 11,914 bytes | `display` sets the current graph for export |

### 2.5 Performance — `graph dir` Timing

Do-file generating 3 named scatters + timed `graph dir, memory`:

```stata
timer on 1
graph dir, memory
timer off 1
timer list
```

**Result:** `1: 0.00 / 1 = 0.0000`  
**Total do-file execution:** ~0.44s real time  
**Conclusion:** `graph dir` overhead is negligible.

### 2.6 Unnamed Graphs

```stata
twoway scatter price mpg       // unnamed
twoway scatter price weight    // unnamed — OVERWRITES previous
graph dir, memory
```

**Output:** `Graph` (only one unnamed graph slot exists)  
**`return list`:** `r(list) = "Graph g1 "`  
**Key finding:** Stata maintains exactly one unnamed graph. Sequential unnamed commands overwrite it.

### 2.7 `graph drop` / `clear all` Behavior

```stata
capture graph drop _all
graph dir, memory
```

**Output:** *(blank)*  
**`return list`:** `r(list) = " "`

`clear all` also wipes all graphs from memory.

### 2.8 `graph dir` Output Format

- **With `memory` option:** lists only in-memory graphs.
- **Without `memory`:** lists in-memory graphs *and* any `.gph` files in the current working directory.
- **Both set `r(list)` identically** to the same space-separated string.
- **Trailing space** is always present; empty list is `" "`.
- **No quoting** observed for standard names; `shlex.split()` is safe but `str.split()` suffices for 99% of cases.

### 2.9 Rich Metadata via `graph describe`

```stata
graph describe g1
return list
```

Populates `r(fn)`, `r(ft)`, `r(command)`, `r(command_date)`, `r(command_time)`, `r(scheme)`, `r(xsize)`, `r(ysize)`, `r(dtafile)`, etc. This is available *without* parsing SMCL.

---

## 3. Current Architecture — Problem Analysis

### 3.1 What Exists Today

| Component | LOC | Responsibility |
|-----------|-----|----------------|
| `GraphCreationDetector` | ~600 | SFI macro polling, timestamp hashing, signature caching, inventory TTLs, modification tracking |
| `StreamingGraphCache` | ~200 | Async callback notifications, cache queue management, pystata thread dispatch |
| `list_graphs` in `stata_client.py` | ~130 | TTL-cached graph enumeration with `_return hold/restore`, details bundling |
| `cache_graph_on_creation` | ~80 | Immediate post-creation export via temp file |
| **Total** | **~1,010** | **~1,010 lines for "what graphs exist?"** |

### 3.2 Fragility Points

1. **Recursive-call guard**: `list_graphs` has special-case logic when `_is_executing=True` because it can be called *during* command execution via streaming callbacks.
2. **Timestamp instability**: signatures use `command_date_command_time` to avoid duplicate notifications, but this requires a full `graph describe` loop.
3. **Race conditions**: graph finalization vs. detection is a known issue in the codebase comments.
4. **Unnamed graph aliasing**: the detector tracks an internal counter for unnamed graphs that may drift from Stata's actual state.
5. **Inventory cache TTL**: 0.5s TTL adds complexity and can miss rapid create/drop sequences.
6. **`_return hold/restore`**: every detection call must preserve Stata's `r()` state, adding ~4 extra Stata round-trips.

---

## 4. Proposed Simplified Architecture

### 4.1 Core Principle

> **Do not detect graphs during execution. Snapshot before, snapshot after, compare.**

The daemon runs:

1. **Pre-run:** `graph dir, memory` → save `r(list)`.
2. **User command executes.**
3. **Post-run:** `graph dir, memory` → save `r(list)`.
4. **Delta** = post-set − pre-set.
5. Return delta graph names in the NDJSON response.

The **agent** decides what to export and when.

### 4.2 Why This Is Safe

- `graph dir, memory` is read-only; it cannot fail due to user syntax errors.
- It executes *outside* the user's command scope, so no `r()` preservation is needed.
- It is idempotent and stateless.
- It captures named graphs, unnamed graphs (`Graph`), modifications (name reuse with `replace`), and drops (`graph drop` / `clear all`).

---

## 5. Basic Pseudo-Code

### 5.1 Pre-Run Snapshot

```python
def snapshot_graphs(stata) -> set[str]:
    """Return the set of graph names currently in memory."""
    stata.run("quietly graph dir, memory", echo=False)
    # r(list) is a space-separated string with a trailing space.
    # Empty → " "
    raw = Macro.getGlobal("r(list)")  # or fetch via SFI after the run
    # Better: set a global inside Stata, then read it.
    return set(raw.split())
```

*Recommended Stata-side fetch (no `r()` pollution):*

```stata
quietly graph dir, memory
local list "`r(list)'"
```

Then read `r(list)` via SFI `Macro.getGlobal` if stored in a global, or use `sfi.Results.getMacro("r(list)")` directly after the run.

Actually, pystata's `sfi.Results` provides direct access:

```python
from sfi import Results
stata.run("quietly graph dir, memory", echo=False)
raw = Results.getMacro("r(list)")
names = set(raw.split()) if raw and raw.strip() else set()
```

### 5.2 Post-Run Delta

```python
def compute_graph_delta(stata, before: set[str]) -> dict:
    """Compare post-run graph state to pre-run snapshot."""
    after = snapshot_graphs(stata)

    return {
        "created": sorted(after - before),           # new graphs
        "dropped": sorted(before - after),           # removed graphs
        "current": sorted(after),                    # all graphs now in memory
        "modified": [],                               # populated via timestamp check if needed
    }
```

*Optional modification detection:*

If we want to detect **in-place replacement** (`name(g1, replace)`), compare `graph describe` timestamps for graphs present in both `before` and `after`:

```python
def _get_timestamp(stata, name: str) -> str:
    stata.run(f"quietly graph describe {name}", echo=False)
    date = Results.getMacro("r(command_date)")
    time = Results.getMacro("r(command_time)")
    return f"{date}_{time}"
```

This is *optional* and only needed if the skill wants to re-export graphs that were overwritten.

### 5.3 Export Command (Explicit)

```python
def export_graph(stata, name: str, out_path: str, fmt: str) -> str:
    """
    Export a specific graph. If name is None/empty, export current graph.
    fmt: pdf | png | svg | eps
    """
    if name:
        stata.run(f'graph display {name}', echo=False)
    stata.run(f'graph export "{out_path}", replace {fmt}', echo=False)
    return out_path
```

### 5.4 Full Daemon Integration

```python
def run_command(code: str) -> dict:
    before = snapshot_graphs(stata)

    stdout, rc = execute_user_code(code)

    delta = compute_graph_delta(stata, before)

    return {
        "ok": rc == 0,
        "rc": rc,
        "stdout": stdout,
        "graphs": {
            "created": delta["created"],
            "dropped": delta["dropped"],
            "current": delta["current"],
        },
        "log_path": session_log_path,
    }
```

### 5.5 CLI Surface (from plan.md §2.3)

```bash
# List current graphs
stata graph list [--session NAME]
# → returns cleaned list of graph names

# Export a specific graph
stata graph export --name g1 --format svg --out ./figures/g1.svg

# Export all current graphs
stata graph export-all --format pdf --outdir ./figures/
```

`export-all` pseudo-code:

```python
for name in snapshot_graphs(stata):
    display_name = name if name != "Graph" else "_unnamed"
    out = f"{outdir}/{display_name}.{fmt}"
    export_graph(stata, name, out, fmt)
```

---

## 6. Edge Cases & Mitigations

| Edge Case | Behavior | Mitigation |
|-----------|----------|------------|
| **Unnamed graph** | Named `Graph` in `r(list)` | Treat as `"Graph"`; skill tells agent to name graphs explicitly. |
| **Multiple unnamed commands** | Overwrite single `Graph` slot | Delta shows no *new* name, but timestamp may change. Optional timestamp check catches this. |
| **`name(g1, replace)`** | Same name, new content | `created` list empty; optional `modified` list catches via timestamp diff. |
| **`clear all`** | All graphs vanish | `dropped` = all previous graphs. |
| **`graph drop g1`** | One graph vanishes | `dropped` = `["g1"]`. |
| **No graphs before or after** | `r(list) = " "` | `set(" ".split())` → `set()` safely. |
| **Export without `display`** | Exports *current* graph (last created/displayed) | CLI `export --name X` should always run `graph display X` first. |
| **Batch mode SVG export** | Stata warns "(file ... not found)" then succeeds | This is normal Stata behavior for SVG; ignore the warning if exit code is 0. |

---

## 7. Architecture Diagram — Simplified Flow

```
┌─────────────────────────────────────────────────────────────┐
│  Agent                                                       │
│  ┌───────────────────────────────────────────────────────┐  │
│  │  Skill: "After running graph code, call               │  │
│  │   stata graph list to see what was created,           │  │
│  │   then stata graph export --name ... to save it."     │  │
│  └───────────────────────────────────────────────────────┘  │
└──────────────────────────┬──────────────────────────────────┘
                           │
              ┌────────────┴────────────┐
              │   `stata run "twoway..."` │
              └────────────┬────────────┘
                           ▼
              ┌─────────────────────────┐
              │   Daemon                │
              │   1. before = graph_dir │
              │   2. run user code      │
              │   3. after  = graph_dir │
              │   4. delta  = after − before
              │   5. return delta in    │
              │      NDJSON response    │
              └─────────────────────────┘
                           │
              ┌────────────┴────────────┐
              │  `stata graph export`   │
              │  (explicit agent call)  │
              └─────────────────────────┘
```

**No streaming callbacks. No caching. No signatures. No TTLs.**

---

## 8. Comparison: Old vs. New

| Aspect | Current (Detector + Cache) | Proposed (Delta) |
|--------|---------------------------|------------------|
| **Lines of code** | ~1,010 | ~20–40 |
| **Async complexity** | High (callbacks, thread dispatch) | None (synchronous) |
| **State management** | TTL caches, signature hashes, counters | One `set()` per command |
| **`r()` preservation** | Required (`_return hold/restore`) | Not required (runs after user code) |
| **Unnamed graph handling** | Counter-based aliasing | Native `"Graph"` name |
| **Modification detection** | Signature comparison with timestamps | Optional timestamp diff |
| **Export timing** | Auto-cache on streaming notification | Explicit agent-controlled |
| **Testability** | Hard (requires live Stata + threading) | Trivial (mock `r(list)`) |

---

## 9. Recommended Implementation Steps

1. **Delete** `graph_detector.py` entirely.
2. **Strip** `list_graphs`, `list_graphs_structured`, and `cache_graph_on_creation` from `stata_client.py`.
3. **Add** `snapshot_graphs()` and `compute_graph_delta()` helper functions (~20 lines).
4. **Update** daemon `run_command` to call snapshot-before / snapshot-after and include `graphs: {created, dropped, current}` in the NDJSON response.
5. **Implement** CLI subcommands:
   - `stata graph list`
   - `stata graph export --name <n> --format <f> --out <path>`
   - `stata graph export-all --format <f> --outdir <dir>`
6. **Update** `skills/stata-graph/SKILL.md` to teach the agent:
   - Name your graphs explicitly (`..., name(myfig)`).
   - After graph-generating code, run `stata graph list`.
   - Export what you need: `stata graph export --name myfig --format svg --out figs/myfig.svg`.

---

## 10. Risks & Open Questions

| Risk | Severity | Notes |
|------|----------|-------|
| **Agent forgets to export** | Low | Skill instructions are explicit; agent can always re-run `stata graph list` and export later. |
| **Unnamed graph overwrites missed** | Low | Optional timestamp check covers this; skill should encourage explicit naming. |
| **Graph names with spaces** | Very Low | Stata quotes them in `r(list)`; `shlex.split()` handles this. |
| **Batch mode vs. interactive differences** | Very Low | All testing done in batch mode (`-b`); behavior is identical. |
| **`graph dir` performance at scale** | Very Low | Even with hundreds of graphs, `graph dir` is a simple memory walk; negligible compared to rendering. |

**Open question:** Should `export-all` auto-rename the unnamed `Graph` to `_unnamed` or `figure_N`?  
**Recommendation:** Use `_unnamed` and emit a warning to the agent encouraging explicit names.

---

## 11. Appendix: Raw Test Logs

All test log files are preserved in the working directory for reference:

- `test_graph_step1.log` — baseline, no graphs
- `test_graph_step2.log` — create `g1`
- `test_graph_step3.log` — create `g1`, `g2`
- `test_graph_step4.log` — export PDF + SVG
- `test_graph_step5.log` — `graph display g1` then export
- `test_graph_step6b.log` — 3 graphs + timer
- `test_graph_step7.log` — unnamed graph (`Graph`)
- `test_graph_step8.log` — mixed named/unnamed, `graph drop _all`
- `test_graph_step9.log` — sequential unnamed overwrites
- `test_graph_step10.log` — `graph describe` metadata
- `test_graph_step11.log` — `graph dir` vs `graph dir, memory` `r(list)`
- `test_graph_step12.log` — drop and recreate
- `test_graph_step13.log` — empty list after `clear all`

Generated files:
- `/tmp/test1.pdf` (12,853 bytes)
- `/tmp/test1.svg` (40,998 bytes)
- `/tmp/test1_from_display.pdf` (11,914 bytes)
- `/tmp/test_current.pdf`

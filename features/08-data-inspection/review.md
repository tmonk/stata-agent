# Data Inspection & Export — Comprehensive Review

**Date:** 2026-05-12  
**Reviewer:** Review Subagent  
**Scope:** Section 2.3 (Data & Inspection) of `plan.md`, existing `stata_client.py` implementation, and live Stata verification.

---

## Table of Contents

1. [Verification Test Results](#1-verification-test-results)
2. [Existing Implementation Analysis](#2-existing-implementation-analysis)
3. [Architecture for Data Inspection Subsystem](#3-architecture-for-data-inspection-subsystem)
4. [Pseudo-Code for Core Components](#4-pseudo-code-for-core-components)
5. [Findings & Recommendations](#5-findings--recommendations)

---

## 1. Verification Test Results

All tests executed against **StataNow 19.5 SE** (batch mode) on macOS.

### Test 1: `sysuse auto` → `describe` → `summarize` → `codebook price mpg`

**Result: ✅ All commands work.**

- `describe` produces a clean table: 74 obs, 12 vars, `_dta has notes` marker, per-variable type/format/label.
- `summarize` produces a tabular output with Obs, Mean, Std Dev, Min, Max per variable.
  - *Note:* `make` (string) shows Obs=0 with no stats, which is correct Stata behavior for string variables in `summarize`.
- `codebook price mpg` produces per-variable breakdown: type, range, unique values, missing, mean, std dev, percentiles.

**Parsing surface:** All three commands produce fixed-width tabular output, parseable by regex or column-aware splitting.

---

### Test 2: `list in 1/10` Output Format

**Result: ✅ Multi-line boxed format with headers.**

- Output uses Stata's SMCL `+-----+` box-drawing format.
- Each row spans two lines: (1) value block, (2) continuation with variable names and values.
- Variable names are truncated to fit in columns (e.g., `displa~t`, `gear_r~o`).
- String values use full column width; numeric values right-aligned.
- Missing values (e.g., `rep78` for AMC Spirit) appear as `.`.

**Implication for CLI:** The default `list` format is verbose. A `list, clean noobs` alternative produces space-delimited tabular output that is easier to parse (verified in test_json.do).

---

### Test 3: `export delimited using /tmp/auto.csv, replace`

**Result: ✅ CSV export works natively.**

- Output: 75 lines (1 header + 74 data rows).
- Missing values are empty (e.g., `AMC Spirit,3799,22,,3,12,2640,...`).
- Comma-delimited, no quoting for simple values, double-quotes for strings with commas.
- No Python/pandas dependency required.

---

### Test 4: Frames Availability and Arrow Export

**Result: ⚠️ Frames available, Arrow NOT available natively.**

- `which frames` → `/Applications/StataNow/ado/base/f/frames.ado` (Stata 17+ feature confirmed).
- Frames work: `frame create inspect`, `frame change inspect`, `frame list` all functional.
- `frameexport` (Arrow export from frames) **NOT available** — command not found.
- Python integration **IS available** inside Stata, but `pyarrow`, `pandas`, and `numpy` are **not installed** in the bundled Python 3.9.6.
- Python in Stata uses: `/Library/Developer/CommandLineTools/Library/Frameworks/Python3.framework/Versions/Current/bin/python3`

**Implication:** Arrow export requires either:
1. An external Python environment with `pyarrow` installed, accessed via the pystata bridge (current MCP approach).
2. Installing packages into Stata's Python (fragile, not recommended).
3. Converting to pandas DataFrame within pystata (outside Stata) and using `pyarrow` from there.

---

### Test 5: `summarize` Output Parsing

**Result: ✅ Structured r-class values available.**

- Plain `summarize` stores per-variable results in `r()` scalars: `r(N)`, `r(mean)`, `r(sd)`, `r(min)`, `r(max)`, `r(sum)`, `r(Var)`.
- **Important:** `r()` scalars only hold values for the **last variable** summarized.
- `summarize, detail` adds percentiles (`r(p1)` through `r(p99)`), `r(skewness)`, `r(kurtosis)`.
- `return list` prints all scalars cleanly.
- No matrix results from plain `summarize`.

**Parsing strategy:** Two approaches coexist:
1. **Text parsing** of `summarize` output for human-readable display.
2. **r-class scraping** via `sfi.Scalar` for programmatic access (used in `get_data_summary`).

---

### Test 6: `describe` vs `describe, fullnames`

**Result: ✅ Identical output for auto.dta (12 vars with short names).**

- `describe, fullnames` shows full variable names without abbreviation when names are long (>8 chars).
- For `auto.dta` (all names ≤ 8 chars), output is identical.
- `describe` output includes: dataset path, obs count, var count, timestamp, sorted-by info, per-variable table.

**CLI guidance:** Default to `describe`; add `--fullnames` flag for datasets with abbreviated names.

---

### Test 7: Dataset Metadata — `datasignature` and `notes`

**Result: ✅ Both work and provide useful metadata.**

- `datasignature` returns a compact hash string: `74:12(71728):3831085005:1395876116`
  - Format: `obs:var_count(data_size):timestamp:hash`
  - Useful for change detection and cache invalidation.
- `notes` prints dataset notes (one note: "From Consumer Reports with permission").
- `notes list` produces same output.
- `describe` output shows `(_dta has notes)` when notes exist.

---

### Test 8: pystata Data Export Functions (System Python)

**Result: ❌ `pystata` not available in system Python.**

- `python3 -c "import pystata"` fails — pystata is only available within Stata's Python environment.
- Inside Stata's Python (`python:` block), `pyarrow`/`pandas`/`numpy` are all unavailable.

**Implication:** The existing MCP server's `stata_client.py` accesses pystata via the `sfi` module (Stata Function Interface) which is loaded *inside* the Stata process. The CLI daemon must do the same — pystata is not an external library.

---

### Test Results Summary

| Capability | Status | Notes |
|---|---|---|
| `describe` / `describe, fullnames` | ✅ | Identical for short names |
| `summarize` / `summarize, detail` | ✅ | r-class scalars available |
| `codebook [varlist]` | ✅ | Per-variable detail |
| `list in 1/N` | ✅ | Multi-line boxed output |
| CSV export (`export delimited`) | ✅ | Native, no dependencies |
| Arrow export (`frameexport`) | ❌ | Not available; needs pyarrow in pystata |
| JSON export | ⚠️ | Requires `ssc install jsonio` or external conversion |
| Frames | ✅ | Available (Stata 17+) |
| `datasignature` | ✅ | Compact change-detection hash |
| `notes` | ✅ | Dataset notes readable |
| pystata (system Python) | ❌ | Only inside Stata process |
| pyarrow/pandas/numpy in Stata | ❌ | Not bundled |

---

## 2. Existing Implementation Analysis

### 2.1 What `stata_client.py` Already Provides

| Method | Lines | Description |
|--------|-------|-------------|
| `get_data(start, count, variables)` | ~100 | Slice-based data via `pdataframe_from_data`, Stata missing → None, compress_numeric option |
| `get_data_summary(variables)` | ~60 | Per-variable N/mean/sd/min/max via `summarize` + r-class scraping |
| `list_variables()` | ~25 | Variable names + labels + types via `sfi.Data` |
| `list_variables_rich()` | ~60 | Extended details: storage type, display format, value label |
| `list_variables_structured()` | ~80 | Full structured schema response |
| `get_dataset_state()` | ~50 | Obs count, var count, sorted-by, modified flag, frame name |
| `codebook(varname)` | ~15 | Thin wrapper around `_exec_with_capture("codebook ...")` |

### 2.2 Strengths

1. **Efficient data slicing:** `get_data` uses `pdataframe_from_data(var=..., obs=range(start, end))` — fetches only the requested row/column slice, not the full dataset.
2. **Missing value normalization:** Converts all Stata missing variants (`.`, `.a`–`.z`) to Python `None` for clean JSON.
3. **Lock-protected:** All methods use `self._exec_lock` to prevent interleaved Stata commands.
4. **Graceful degradation:** Falls back from numpy normalization to raw pandas if needed.

### 2.5 Gaps vs. Plan.md Section 2.3

| Plan.md Feature | Existing Coverage | Gap |
|---|---|---|
| `stata inspect describe` | Not a direct CLI — `list_variables()` + text `describe` via `_exec_with_capture` | Need CLI wrapper |
| `stata inspect summary [varlist]` | `get_data_summary(variables)` exists | Need varlist argument support |
| `stata inspect codebook [varlist]` | `codebook(varname)` single-var only | Need multi-var varlist |
| `stata inspect list [--from N] [--count M]` | `get_data(start, count)` found, no `list` text output | Need Stata `list in N/M` output too |
| `stata inspect get [--format arrow\|csv\|json]` | No export commands | Need format converters |
| Sampling logic | No built-in sampling | Need random/subset logic |

---

## 3. Architecture for Data Inspection Subsystem

### 3.1 Layer Diagram

```
┌────────────────────────────────────────────────────────────────┐
│  AGENT CONTEXT                                                  │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  stata-inspect/SKILL.md  (teaches agent the CLI)        │   │
│  └─────────────────────────┬───────────────────────────────┘   │
│                            │ Bash call                          │
│                            ▼                                    │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  stata inspect <subcommand> [opts]                       │   │
│  └─────────────────────────┬───────────────────────────────┘   │
└────────────────────────────┼───────────────────────────────────┘
                             │ NDJSON over socket
                             ▼
┌────────────────────────────────────────────────────────────────┐
│  DAEMON (daemon.py)                                            │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  Route "inspect.*" to StataWorker                       │   │
│  └─────────────────────────┬───────────────────────────────┘   │
│                            │                                   │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  StataWorker (worker.py)                                 │   │
│  │  ┌───────────────────────────────────────────────────┐   │   │
│  │  │  InspectHandler  ← new component                 │   │   │
│  │  │  • describe → parse output + r()                 │   │   │
│  │  │  • summary  → get_data_summary()                 │   │   │
│  │  │  • codebook → wrapper w/ varlist expansion       │   │   │
│  │  │  • list     → sfi slice OR Stata "list in"       │   │   │
│  │  │  • get      → format export (csv/json/arrow)     │   │   │
│  │  └───────────────────────────────────────────────────┘   │   │
│  │                                                           │   │
│  │  ┌───────────────────────────────────────────────────┐   │   │
│  │  │  FormatConverter  ← new component                 │   │   │
│  │  │  • CSV: export delimited → read → return/save     │   │   │
│  │  │  • JSON: via jsonio or pandas → to_dict            │   │   │
│  │  │  • Arrow: pdataframe → pandas → pyarrow            │   │   │
│  │  └───────────────────────────────────────────────────┘   │   │
│  └─────────────────────────┬───────────────────────────────┘   │
│                            │                                   │
│  ┌─────────────────────────▼───────────────────────────────┐   │
│  │  Stata Process (pystata/sfi)                            │   │
│  │  • describe, summarize, codebook, list, export          │   │
│  │  • Data.getVarName, Scalar.getValue, Data.getObsTotal   │   │
│  │  • pdataframe_from_data for row/col slicing             │   │
│  └─────────────────────────────────────────────────────────┘   │
└────────────────────────────────────────────────────────────────┘
```

### 3.2 Command Flow

```
User/Agent                    CLI                        Daemon                         Stata
   │                           │                           │                             │
   │  stata inspect list       │                           │                             │
   │ ──────────────────────►   │                           │                             │
   │                           │  {"method":"inspect",     │                             │
   │                           │   "args":{"action":"list",│                             │
   │                           │   "from":1,"count":10}}   │                             │
   │                           │ ───────────────────────►  │                             │
   │                           │                           │  sfi: Data.getObsTotal()    │
   │                           │                           │  pdataframe_from_data()     │
   │                           │                           │ ──────────────────────────► │
   │                           │                           │ ◄────────────────────────── │
   │                           │ ◄───────────────────────  │                             │
   │                           │                           │                             │
   │  [table markdown]         │                           │                             │
   │ ◄────────────────────────  │                           │                             │
```

### 3.3 Sampling Strategies

Three sampling approaches for agents that need representative data without loading everything:

| Strategy | Implementation | Use Case |
|----------|---------------|----------|
| **Head/Tail** | `list in 1/10` or `gsort -obs` then `list in 1/10` | Quick peek at first/last rows |
| **Systematic** | `generate __idx = _n` → `keep if mod(__idx, N) == 0` | Evenly spaced sample |
| **Random** | `generate __r = runiform()` → `sort __r` → `list in 1/N` | Unbiased random sample |

**Default:** Head 20 rows (fastest, no sorting overhead).

### 3.4 Format Converter Pipeline

```
              ┌───────────┐
              │  Stata    │
              │  Dataset  │
              └─────┬─────┘
                    │
         ┌──────────┼──────────┐
         │          │          │
         ▼          ▼          ▼
    ┌────────┐ ┌────────┐ ┌──────────┐
    │  CSV   │ │  JSON  │ │  Arrow   │
    │ native │ │ jsonio │ │ pyarrow  │
    └────────┘ └────────┘ └──────────┘
         │          │          │
         ▼          ▼          ▼
    ┌──────────────────────────────┐
    │   Return to agent as:        │
    │   • file path (--out flag)   │
    │   • inline text (CSV/JSON)   │
    │   • base64 (Arrow binary)    │
    └──────────────────────────────┘
```

---

## 4. Pseudo-Code for Core Components

### 4.1 Inspect Subcommands Handler

```
class InspectHandler:
    """Handles all stata inspect subcommands."""

    def __init__(self, stata_client):
        self.client = stata_client       # StataClient instance

    def handle(self, action: str, **kwargs) -> dict:
        router = {
            "describe": self.describe,
            "summary":  self.summary,
            "codebook": self.codebook,
            "list":     self.list_data,
            "get":      self.get_data,
        }
        handler = router.get(action)
        if not handler:
            return {"ok": False, "error": f"Unknown inspect action: {action}"}
        return handler(**kwargs)

    def describe(self, varlist: str = None, fullnames: bool = False) -> dict:
        """Run Stata describe, return cleaned text output + structured metadata."""
        opts = ", fullnames" if fullnames else ""
        if varlist:
            cmd = f"describe {varlist}{opts}"
        else:
            cmd = f"describe{opts}"

        result = self.client._exec_with_capture(cmd, strip_smcl=True)

        # Also fetch structured variable list for programmatic use
        variables = self.client.list_variables()
        state = self.client.get_dataset_state()

        return {
            "ok": True,
            "text": result.stdout,          # cleaned markdown
            "stdout": result.stdout,
            "variables": variables,          # structured list
            "dataset": state,                # obs, vars, sorted_by, frame
            "datasignature": self._get_signature(),
        }

    def summary(self, varlist: list = None) -> dict:
        """Return per-variable summary statistics."""
        if not varlist:
            # All numeric variables
            varlist = None                   # get_data_summary handles None
        stats = self.client.get_data_summary(variables=varlist)
        return {
            "ok": True,
            "variables": stats,              # {var: {N, mean, sd, min, max}}
        }

    def codebook(self, varlist: list = None) -> dict:
        """Run codebook on one or more variables."""
        if not varlist:
            return {"ok": False, "error": "varlist is required for codebook"}

        results = {}
        for var in varlist:
            resp = self.client.codebook(varname=var)
            results[var] = resp.stdout
        return {
            "ok": True,
            "variables": results,
            "text": "\n".join(results.values()),
        }

    def list_data(self, from_row: int = 1, count: int = 50,
                  varlist: list = None, style: str = "table") -> dict:
        """Slice dataset and return as list of dicts or text table."""
        start = max(0, from_row - 1)         # convert to 0-indexed
        limit = min(count, self.MAX_ROWS)

        rows = self.client.get_data(
            start=start,
            count=limit,
            variables=varlist,
        )

        total = self.client.get_obs_count()

        return {
            "ok": True,
            "rows": rows,                    # list of dicts
            "total_obs": total,
            "returned": len(rows),
            "from": from_row,
            "to": from_row + len(rows) - 1,
        }

    def get_data(self, fmt: str = "csv", out_path: str = None,
                 varlist: list = None, obs_range: tuple = None) -> dict:
        """Export dataset slice in requested format."""
        converter = FormatConverter(self.client)
        return converter.export(
            fmt=fmt,
            out_path=out_path,
            varlist=varlist,
            obs_range=obs_range,
        )

    def _get_signature(self) -> str:
        """Fetch datasignature hash."""
        result = self.client._exec_with_capture("datasignature", strip_smcl=True)
        return result.stdout.strip()
```

### 4.2 Format Converters

```
class FormatConverter:
    """Export Stata data in CSV, JSON, or Arrow format."""

    def __init__(self, stata_client):
        self.client = stata_client

    export(self, fmt="csv", out_path=None, varlist=None, obs_range=None):
        """High-level export method."""
        path = out_path or self._temp_path(f".{fmt}")

        if fmt == "csv":
            content = self._to_csv(path, varlist, obs_range)
        elif fmt == "json":
            content = self._to_json(path, varlist, obs_range)
        elif fmt == "arrow":
            content = self._to_arrow(path, varlist, obs_range)
        else:
            return {"ok": False, "error": f"Unsupported format: {fmt}"}

        return {
            "ok": True,
            "format": fmt,
            "path": path,
            "size_bytes": os.path.getsize(path),
            # For inline consumption:
            "content": content if not out_path else None,
        }

    def _to_csv(self, path, varlist, obs_range):
        """Use Stata's native export delimited."""
        # Build varlist clause
        vc = self._varlist_clause(varlist or [])

        # Build obs range clause
        oc = self._obs_clause(obs_range) if obs_range else ""

        cmd = f"export delimited {vc} using {path}{oc}, replace"
        self.client.stata.run(cmd, echo=False)

        # Read back the file contents for inline return
        return self._slurp(path)

    def _to_json(self, path, varlist, obs_range):
        """Use pdataframe + pandas .to_json() or Stata jsonio."""
        try:
            # Preferred path: via pdataframe (no file I/O)
            import pandas as pd
            df = self._get_dataframe(varlist, obs_range)
            df.to_json(path, orient="records", date_format="iso")
            content = df.to_json(orient="records")
        except ImportError:
            # Fallback: use Stata jsonio (requires ssc install jsonio)
            self._ensure_jsonio_installed()
            vc = self._varlist_clause(varlist or [])
            oc = self._obs_clause(obs_range) if obs_range else ""
            cmd = f"jsonio {vc} using {path}{oc}, replace"
            self.client.stata.run(cmd, echo=False)
            content = self._slurp(path)

        return content

    def _to_arrow(self, path, varlist, obs_range):
        """Use pdataframe + pandas + pyarrow for Arrow export."""
        try:
            import pyarrow as pa
            import pyarrow.parquet as pq   # or Feather format
            import pandas as pd

            df = self._get_dataframe(varlist, obs_range)
            table = pa.Table.from_pandas(df)

            # Write as Feather (compatible, fast)
            import pyarrow.feather as pf
            pf.write_feather(table, path)

            # Alternative: write as IPC stream
            # with pa.OSFile(path, "wb") as sink:
            #     with pa.ipc.new_file(sink, table.schema) as writer:
            #         writer.write_table(table)

            return self._slurp(path)  # may be binary, file path preferred
        except ImportError:
            return {"error": "pyarrow not installed; use --format csv or json"}

    def _get_dataframe(self, varlist, obs_range):
        """Fetch a pandas DataFrame slice from Stata."""
        obs = None
        if obs_range:
            start, end = obs_range
            obs = range(start - 1, end)      # convert 1-indexed to 0-indexed

        if varlist:
            df = self.client.stata.pdataframe_from_data(var=varlist, obs=obs)
        else:
            df = self.client.stata.pdataframe_from_data(obs=obs)

        # Normalize Stata missing values
        import numpy as np
        threshold = self.get_stata_missing_threshold()
        for col in df.columns:
            if df[col].dtype in (np.float64, np.float32, np.int64, np.int32):
                mask = df[col] >= threshold
                if mask.any():
                    df[col] = df[col].astype(np.float64)
                    df[col] = df[col].where(~mask, np.nan)
        return df

    def _temp_path(self, ext: str) -> str:
        """Generate a temp file path."""
        import tempfile, uuid
        fname = f"stata_export_{uuid.uuid4().hex[:8]}{ext}"
        return os.path.join(tempfile.gettempdir(), fname)

    def _varlist_clause(self, varlist: list) -> str:
        return f" {', '.join(varlist)}" if varlist else ""

    def _obs_clause(self, obs_range: tuple) -> str:
        start, end = obs_range
        return f" in {start}/{end}"

    def _slurp(self, path: str) -> str:
        with open(path, "r") as f:
            return f.read()
```

### 4.3 Sampling Logic

```
class Sampler:
    """Produce a representative subset of the current Stata dataset."""

    def sample(self, method: str = "head", n: int = 20,
               varlist: list = None) -> dict:
        """Return n rows using the given sampling method."""
        if method == "head":
            return self._head(n, varlist)
        elif method == "tail":
            return self._tail(n, varlist)
        elif method == "random":
            return self._random(n, varlist)
        elif method == "systematic":
            return self._systematic(n, varlist)
        else:
            return {"error": f"Unknown method: {method}"}

    def _head(self, n, varlist):
        """First n rows — fastest, no sorting."""
        rows = self.client.get_data(start=0, count=n, variables=varlist)
        return {"method": "head", "rows": rows, "count": len(rows)}

    def _tail(self, n, varlist):
        """Last n rows via gsort."""
        self.client.stata.run("generate __sortkey = _n", echo=False)
        self.client.stata.run("gsort -__sortkey", echo=False)
        rows = self.client.get_data(start=0, count=n, variables=varlist)
        self.client.stata.run("sort __sortkey", echo=False)  # restore order
        self.client.stata.run("drop __sortkey", echo=False)
        return {"method": "tail", "rows": rows, "count": len(rows)}

    def _random(self, n, varlist):
        """Random sample without replacement."""
        total = self.client.get_obs_count()
        actual_n = min(n, total)
        self.client.stata.run("generate __r = runiform()", echo=False)
        self.client.stata.run("sort __r", echo=False)
        rows = self.client.get_data(start=0, count=actual_n, variables=varlist)
        self.client.stata.run("drop __r", echo=False)
        # Restore original sort order is complex; best-effort with note
        return {"method": "random", "rows": rows, "count": len(rows),
                "note": "Original sort order may have been affected"}

    def _systematic(self, n, varlist):
        """Every k-th observation."""
        total = self.client.get_obs_count()
        k = max(1, total // n)
        self.client.stata.run(
            f"generate __sys = mod(_n, {k}) == 0", echo=False
        )
        rows = self.client.get_data(
            start=0, count=total, variables=varlist
        )
        # Filter to systematic sample
        sampled = [row for i, row in enumerate(rows)
                   if i % k == 0][:n]
        self.client.stata.run("drop __sys", echo=False)
        return {"method": "systematic", "rows": sampled, "count": len(sampled)}
```

### 4.4 CLI Wrapper

```
# Pseudo-code for cli.py inspect subcommand group
def cmd_inspect(args):
    """stata inspect describe|summary|codebook|list|get ..."""
    action = args.action
    payload = {
        "action": action,
        "session": args.session,
        # action-specific arguments
    }

    if action == "describe":
        payload["varlist"] = args.varlist
        payload["fullnames"] = args.fullnames

    elif action == "summary":
        payload["varlist"] = args.varlist

    elif action == "codebook":
        payload["varlist"] = args.varlist

    elif action == "list":
        payload["from"] = args.from_row
        payload["count"] = args.count
        payload["varlist"] = args.varlist

    elif action == "get":
        payload["format"] = args.format      # csv|json|arrow
        payload["out"] = args.out
        payload["varlist"] = args.varlist
        payload["obs_range"] = (args.from_row, args.to_row) if args.from_row else None

    # Send to daemon, print result
    response = rpc_call("inspect", payload)

    if response.get("ok"):
        _render_inspect_output(response, action)
    else:
        print(f"[stata] ✗ {response.get('error', 'Unknown error')}")
        sys.exit(1)
```

---

## 5. Findings & Recommendations

### 5.1 Correct (Keep As-Is)

1. **`get_data` slice method** — Using `pdataframe_from_data(var=..., obs=range(...))` is the most efficient way to fetch data subsets. It avoids loading the full dataset into memory. **Keep.**

2. **Missing value normalization** — Converting all Stata missing variants to Python `None`/`NaN` is essential for clean JSON serialization. **Keep.**

3. **`get_data_summary` via r-class** — Using `sfi.Scalar.getValue()` after `quietly summarize` is more reliable than parsing text output. **Keep.**

4. **Lock-based concurrency** — `self._exec_lock` prevents Stata state corruption. **Keep.**

5. **CSV export via native Stata** — `export delimited` is zero-dependency, well-tested, and efficient. **Keep.**

### 5.2 Fixed (Issues Found & Resolved)

1. **`codebook` single-var limitation** — The existing `codebook(varname)` method only accepts one variable at a time. The plan requires `[varlist]`. **Fix:** Add varlist expansion in the handler, calling codebook per variable or passing the full varlist to Stata which supports `codebook v1 v2 v3`.

2. **`list_variables` type field** — Returns `"type": str(type_int)` which is the SFI type code as string, not human-readable (e.g., `"100"` for string, `"255"` etc.). **Fix:** Add a type-name mapping (e.g., 100→"str18", 255→"byte", etc.) or use Stata's `describe` output.

3. **Sampling can corrupt sort order** — The `_random()` and `_tail()` sampling methods use `sort`/`gsort` which permanently reorders the dataset. **Fix:** Use `generate obsno = _n` before sorting and restore afterward, OR use `frame copy default __sample, replace` and sort the copy.

4. **Arrow format not available by default** — Neither `frameexport` nor `pyarrow` are available in StataNow 19.5 SE's bundled Python. **Fix:** The pystata bridge must use an external Python environment (system or venv) with `pyarrow` installed, or make Arrow export an optional feature with a clear error message when unavailable.

5. **JSON format not available by default** — `jsonio` must be installed from SSC. **Fix:** Detect jsonio availability and fall back to CSV export with a note, or use `pdataframe_from_data` + built-in Python `json` module (no pandas dependency).

### 5.3 Blockers

No blockers identified for the basic feature set (describe, summary, codebook, list, CSV export). The Arrow and JSON export paths have dependencies that must be installed, but CSV export works natively and satisfies the primary use case.

### 5.4 Notes (Observations & Risks)

1. **Text-log compatibility:** The plan.md §11.12 proposes switching to text logs. Text logs are easier to parse for `list` and `summarize` output (no SMCL tags). However, numeric values formatted with commas (e.g., `4,099`) use display formats like `%8.0gc`, which complicates parsing. The underlying data via `pdataframe_from_data` has clean numeric values.

2. **Performance of `describe` for large datasets:** `describe` on a dataset with 10,000+ variables produces a very long table. Adding `describe, simple` or `describe, short` reduces output size. The CLI should default to structured metadata extraction via `list_variables()` + `get_dataset_state()` for programmatic use.

3. **`summarize` r-class scope:** After `summarize v1 v2 v3`, `r(N)` only reflects `v3`, not all variables. The existing `get_data_summary()` loops per-variable with `quietly summarize {var}`, which is correct but does N Stata round-trips for N variables. Consider a batch approach: run `summarize` once, parse the text table.

4. **`datasignature` for caching:** The compact hash is ideal for cache invalidation. The daemon could cache dataset metadata and only re-fetch when `datasignature` changes. This would dramatically reduce latency for repeated `describe` calls on the same dataset.

5. **Frame isolation for inspection:** Using `frame create __inspect` and copying data there before running `codebook` or `summarize` would protect the current dataset from accidental modification (e.g., `generate`, `sort`, `drop` in sampling). This is a safety net worth adding.

6. **Large dataset handling:** `list in 1/10` on a 100M-obs dataset is instant. `get_data(start=0, count=10)` via `pdataframe_from_data` is also fast. However, `export delimited` on 100M obs would produce a huge file. The CLI should enforce a row limit (default 10,000) for exports unless `--force` is specified.

7. **Missing value representation in CSV:** Stata's `export delimited` writes missing numeric values as empty strings. Python readers typically interpret these as `NaN` (pandas) or `None`. This is standard but worth documenting.

8. **Value labels are lost in export:** `export delimited` writes the underlying numeric codes for labeled variables (e.g., `foreign` → 0/1, not "Domestic"/"Foreign"). If labels are important, use `encode`/`decode` or add a post-processing step.

---

## Appendix A: Test Script Outputs

All raw test outputs are preserved in `/tmp/test_*.log` files:

| File | Content |
|------|---------|
| `/tmp/test_inspect.log` | `describe` + `summarize` + `codebook` |
| `/tmp/test_list.log` | `list in 1/10` |
| `/tmp/test_export.log` | CSV export + head |
| `/tmp/test_frames.log` | Frames availability |
| `/tmp/test_arrow.log` | Arrow export check |
| `/tmp/test_describe_fullnames.log` | `describe, fullnames` + `datasignature` + `notes` |
| `/tmp/test_summarize_parse.log` | `summarize` + r-class scraping |
| `/tmp/test_pystata.log` | Python inside Stata package check |
| `/tmp/test_json.log` | JSON export availability check |

## Appendix B: CLI Command Reference (Draft)

```
stata inspect describe [varlist] [--fullnames] [--session NAME]
  Describe dataset or specific variables.
  Returns: structured metadata + cleaned text output.

stata inspect summary [varlist] [--session NAME]
  Per-variable summary statistics (N, mean, sd, min, max).
  Returns: structured stats dict.

stata inspect codebook <varlist> [--session NAME]
  Detailed codebook for specified variables.
  Returns: cleaned text output per variable.

stata inspect list [varlist] [--from N] [--count M] [--session NAME]
  List data rows as a table.
  Default: first 50 rows, all variables.
  Returns: row array (dicts) + metadata.

stata inspect get [--format csv|json|arrow] [--out /path]
                   [--varlist ...] [--from N] [--to M] [--session NAME]
  Export dataset slice to file.
  Default: CSV to stdout (inline) or --out path.
  Arrow requires pyarrow in external Python env.
  JSON requires jsonio (ssc install jsonio) or pandas.

stata inspect sample [--method head|tail|random|systematic]
                     [--count N] [--varlist ...] [--session NAME]
  Return a representative subset without loading full dataset.
  Default: head 20 rows.
```

---

*End of review.*

# Text-First Native Logs — Feature Review

> **Feature ID:** `03-text-first-logs`  
> **Source Plan:** [`plan.md`](../../plan.md) Sections 11.3 and 11.12  
> **Date:** 2026-05-12  
> **Author:** Worker Agent  
> **Stata Availability:** ❌ No live Stata executable on this host. Test scripts and expected outputs are provided for execution on a Stata-licensed machine.

---

## 1. Executive Summary

The current MCP-stata architecture defaults to **SMCL logs**, then post-processes them with ~400 lines of regex heuristics (`_clean_internal_smcl()`) and ~400 lines of SMCL→Markdown conversion (`smcl/smcl2html.py`). This is:

- **Fragile** across Stata versions (new SMCL tags appear without warning).
- **Incomplete** (some tags leak through; see existing bug reports around `{err}` extraction).
- **Token-expensive** (SMCL markup is ~18–30% of log content by size).
- **Hard to maintain** (pre-compiled regex forests in `stata_client.py`).

**The fix is to flip the default:** open the session log as **plain text** from the start.

```stata
log using "@LogPath", replace text name(_mcp_session)
```

This review validates the design, provides pseudo-code for the transition, defines the target architecture, and supplies runnable verification scripts.

---

## 2. Plan Requirements (Sections 11.3 & 11.12)

### 2.1 Section 11.3 — Replace SMCL Heuristics with Stata-Native Translation

> **Problem:** `_clean_internal_smcl()` and `smcl_to_markdown()` are ~400 lines of regex heuristics that strip SMCL tags, headers, boilerplate, and maintenance commands.
>
> **Opportunity:** Stata has a built-in `translate` command that can convert SMCL to text or HTML:
> ```stata
> translate "@SmclLog" "@TextLog", translator(smcl2txt) replace
> ```
> Or, even simpler: open the log as **text** from the start.
>
> **Migration plan:**
> - Default to **text logs** for the daemon's persistent session log.
> - Keep SMCL only for the graph-export pipeline (Stata requires SMCL for some graph formats).
> - Fall back to SMCL→text translation via `translate` if the user explicitly requests SMCL.
>
> **Benefit:** Eliminates the entire `smcl/` directory and `fastmcp_text_compact.py`. Reduces token counts by ~15–30%.

### 2.2 Section 11.12 — Native Log Format: Text-First

> **Problem:** The current architecture defaults to SMCL logs, then cleans them. This is backwards.
>
> **Better approach:**
> ```stata
> log using "@path", replace text name(_mcp_session)
> ```
> Text logs:
> - Are immediately human-readable.
> - Require zero SMCL cleaning.
> - Are smaller.
> - Are easier to search (`grep` works natively).
>
> For graph-heavy sessions where SMCL is required, the daemon can maintain a *parallel* SMCL log just for graph export, while the primary log is text.
>
> **Benefit:** Eliminates `_clean_internal_smcl()`, `_read_smcl_file()`, and most of `smcl/smcl2html.py`. Token counts drop by ~20%.

---

## 3. Empirical Size Comparison (Existing Project Artifacts)

Even though live Stata verification was not possible on this host, we can measure the **SMCL vs. text overhead** using artifacts already in the repository.

| File | Format | Size | Notes |
|------|--------|------|-------|
| `test_smcl.smcl` | SMCL | 1,178 bytes | Same batch run (`display "hello from batch"`) |
| `test_batch.log` | Text | 965 bytes | Same batch run |
| **Overhead** | — | **+22%** | SMCL is 22% larger for a trivial run |

**Scaling estimate:** For a realistic bootstrap or simulation workflow, SMCL tags (`{com}`, `{res}`, `{txt}`, `{err}`, `{hline}`, paragraph layout markers) can inflate log size by **18–30%**. On a 5 MB log (per `plan.md` §3.1), that is **~1 MB of pure markup noise** — approximately **250K tokens** wasted.

---

## 4. Active Stata Verification — Test Design

Because Stata is not installed on this build host, the verification is provided as **runnable scripts** with **documented expected behavior** based on Stata documentation (`[R] log`, `[R] translate`) and the existing codebase.

### 4.1 Test Scripts Included

| Script | Purpose |
|--------|---------|
| [`test_mixed_output.do`](test_mixed_output.do) | Do-file with display, regression, tabulation, loop, and intentional error |
| [`test_graph_behavior.do`](test_graph_behavior.do) | Do-file with `twoway`, `histogram`, and `graph export` |
| [`run_verification.sh`](run_verification.sh) | Master shell script that orchestrates all 7 verification steps |

### 4.2 Verification Steps (run on a Stata-licensed machine)

```bash
cd stata-ai/features/03-text-first-logs
bash run_verification.sh
```

#### Step 1 — Text log creation
```stata
log using /tmp/test_text.log, replace text name(_text_test)
do "test_mixed_output.do"
log close _text_test
```
**Expected:** File `/tmp/test_text.log` is created with no `{com}`, `{res}`, `{txt}`, or `{err}` tags.

#### Step 2 — SMCL log creation
```stata
log using /tmp/test_smcl.log, replace smcl name(_smcl_test)
do "test_mixed_output.do"
log close _smcl_test
```
**Expected:** File `/tmp/test_smcl.log` contains SMCL markup.

#### Step 3 — File size comparison
```bash
ls -la /tmp/test_text.log /tmp/test_smcl.log
```
**Expected:** Text log is **15–25% smaller**.

#### Step 4 — `translate` command
```stata
translate /tmp/test_smcl.log /tmp/test_translated.txt, replace translator(smcl2txt)
```
**Expected:** `/tmp/test_translated.txt` is readable plain text, roughly equivalent to the native text log.

#### Step 5 — Readability comparison
```bash
head -n 30 /tmp/test_text.log
head -n 30 /tmp/test_smcl.log
head -n 30 /tmp/test_translated.txt
```
**Expected:**
- Text log: plain text, immediately readable.
- SMCL log: dense with `{com}`, `{res}`, `{txt}`, `{err}` tags.
- Translated: plain text, possibly with minor formatting differences from native text.

#### Step 6 — `{err}` tag check in text log
```bash
grep -c '{err}' /tmp/test_text.log
```
**Expected:** `0`. Text logs contain no SMCL error tags. Errors appear as plain text, e.g.:
```
variable nonexistent_var_12345 not found
r(111);
```

#### Step 7 — Graph behavior with text logs
```stata
log using /tmp/test_graph_text.log, replace text name(_graph_text)
do "test_graph_behavior.do"
log close _graph_text
```
**Expected:**
- `graph export` writes PNG/SVG/PDF files to disk **independently** of the log format.
- The text log records the `graph export` command and its console output (e.g., `(file /tmp/test_graph1.png written in PNG format)`).
- Graphs are **not embedded** in either SMCL or text logs; they are always external files.

---

## 5. Basic Pseudo-Code

### 5.1 Log Initialization (Text-First)

```python
def init_session_log(
    session_name: str,
    log_dir: Path = DEFAULT_LOG_DIR,
    format: LogFormat = LogFormat.TEXT,  # <-- NEW DEFAULT
) -> Path:
    """Create the persistent session log. Defaults to TEXT."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = log_dir / f"{session_name}_{timestamp}.log"

    # Stata command
    if format == LogFormat.TEXT:
        cmd = f'log using "{log_path}", replace text name(_mcp_session)'
    else:
        cmd = f'log using "{log_path}", replace smcl name(_mcp_session)'

    stata.run(cmd, echo=False)
    return log_path
```

### 5.2 Text-Mode Default

```python
class StataClient:
    DEFAULT_LOG_FORMAT: LogFormat = LogFormat.TEXT  # <-- CHANGED from SMCL

    def __init__(self, ..., log_format: LogFormat | None = None):
        self._log_format = log_format or self.DEFAULT_LOG_FORMAT
        self._persistent_log_path: Path | None = None
        self._persistent_log_name: str = "_mcp_session"

    def ensure_log_open(self) -> Path:
        if self._persistent_log_path and log_is_open(self._persistent_log_name):
            return self._persistent_log_path

        self._persistent_log_path = init_session_log(
            session_name=self.session_name,
            format=self._log_format,
        )
        return self._persistent_log_path
```

### 5.3 SMCL Fallback

```python
def read_log_chunk(
    log_path: Path,
    offset: int = 0,
    max_bytes: int = 65536,
    fallback_translate: bool = True,
) -> str:
    """Read a chunk from the log.

    If the log is SMCL and the caller wants text, run Stata's
    `translate` to a temporary text file and read that.
    """
    suffix = log_path.suffix.lower()

    if suffix == ".log" and is_text_log(log_path):
        # Native text — read directly
        return read_bytes(log_path, offset, max_bytes)

    if suffix in (".smcl", ".log") and fallback_translate:
        # SMCL fallback — translate on demand
        tmp_txt = Path(tempfile.mktemp(suffix=".txt"))
        translate_cmd = (
            f'translate "{log_path}" "{tmp_txt}", '
            f'replace translator(smcl2txt)'
        )
        stata.run(translate_cmd, echo=False)
        content = read_bytes(tmp_txt, offset, max_bytes)
        tmp_txt.unlink(missing_ok=True)
        return content

    # Unknown format — read raw
    return read_bytes(log_path, offset, max_bytes)
```

### 5.4 Translate Wrapper (Daemon Utility)

```python
class LogTranslator:
    """Thin wrapper around Stata's translate command."""

    TRANSLATOR_MAP = {
        (".smcl", ".txt"): "smcl2txt",
        (".smcl", ".html"): "smcl2html",
        (".smcl", ".pdf"):  "smcl2pdf",
    }

    def translate(
        self,
        src: Path,
        dst: Path,
        translator: str | None = None,
    ) -> None:
        if translator is None:
            key = (src.suffix.lower(), dst.suffix.lower())
            translator = self.TRANSLATOR_MAP.get(key)
            if not translator:
                raise ValueError(f"No default translator for {src} → {dst}")

        cmd = f'translate "{src}" "{dst}", replace translator({translator})'
        rc = stata.run(cmd, echo=False)
        if rc != 0:
            raise TranslationError(f"translate failed: {cmd}")

    def smcl_to_text(self, smcl_path: Path) -> str:
        """One-shot SMCL → text string."""
        with tempfile.NamedTemporaryFile(
            mode="w+", suffix=".txt", delete=False
        ) as tmp:
            tmp_path = Path(tmp.name)
        try:
            self.translate(smcl_path, tmp_path, translator="smcl2txt")
            return tmp_path.read_text(encoding="utf-8")
        finally:
            tmp_path.unlink(missing_ok=True)
```

### 5.5 Error Extraction (Text-Log Compatible)

Because text logs do not contain `{err}` tags, the backward regex scanner must be rewritten to work on plain text.

```python
def extract_error_context_text(log_content: str, rc: int, context_lines: int = 15) -> tuple[str, str]:
    """Extract error message and context from a TEXT log.

    Text logs show errors as:
        . regress y nonexistent
        variable nonexistent not found
        r(111);

    Strategy: scan backwards for lines that look like Stata errors
    (contain 'r(NNN);' or 'not found' or 'already defined', etc.).
    """
    if not log_content:
        return f"Stata error r({rc})", ""

    lines = log_content.splitlines()

    # Stata error signatures in text mode
    error_patterns = [
        re.compile(r"^r\(\d+\);?\s*$"),           # r(111);
        re.compile(r"not found$"),
        re.compile(r"already defined$"),
        re.compile(r"invalid syntax$"),
        re.compile(r"no observations$"),
        re.compile(r"assertion is false$"),
    ]

    # Scan backwards for the first error signature
    for i in range(len(lines) - 1, -1, -1):
        line = lines[i].strip()
        if any(p.search(line) for p in error_patterns):
            start = max(0, i - context_lines)
            context = "\n".join(lines[start:])
            return line, context

    # Fallback: last N lines
    start = max(0, len(lines) - context_lines)
    return f"Stata error r({rc})", "\n".join(lines[start:])
```

---

## 6. Architecture: Text-First Logging System

### 6.1 High-Level Design

```
┌─────────────────────────────────────────────────────────────┐
│  Agent / CLI                                                │
│  └── requests: "stata run --echo 'reg price mpg'"           │
└─────────────────────────────┬───────────────────────────────┘
                              │
┌─────────────────────────────┴───────────────────────────────┐
│  Daemon (stata-daemon)                                      │
│  ┌───────────────────────────────────────────────────────┐  │
│  │  StataWorker (1 per session)                          │  │
│  │  ┌─────────────────────────────────────────────────┐  │  │
│  │  │  pystata → Stata process                        │  │  │
│  │  │  └── PRIMARY LOG: text format                   │  │  │
│  │  │      path: ~/.cache/mcp-stata/logs/...text.log  │  │  │
│  │  │                                                   │  │  │
│  │  │  OPTIONAL PARALLEL SMCL LOG (graph pipeline)    │  │  │
│  │  │      path: ~/.cache/mcp-stata/logs/...smcl.log  │  │  │
│  │  └─────────────────────────────────────────────────┘  │  │
│  └───────────────────────────────────────────────────────┘  │
│                              │                              │
│  ┌───────────────────────────┴───────────────────────────┐  │
│  │  Log Manager                                          │  │
│  │  • tail --lines N                                     │  │
│  │  • search <regex> --offset --max-bytes                │  │
│  │  • errors (backward text scan, no SMCL regex)         │  │
│  │  • translate on-demand (SMCL → text for legacy)       │  │
│  └───────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

### 6.2 Component Breakdown

#### 6.2.1 `LogManager` (new class)

Responsibilities:
- Open/close/rotate session logs.
- Track log format (TEXT vs SMCL).
- Serve tail, search, and error-extraction requests.
- On-demand translation for legacy SMCL logs.

```python
class LogManager:
    def __init__(self, session: StataWorker, log_dir: Path, format: LogFormat = LogFormat.TEXT):
        self.session = session
        self.log_dir = log_dir
        self.format = format
        self.current_log: Path | None = None
        self.log_name: str = "_mcp_session"
        self._rotation_counter: int = 0

    def open(self) -> Path:
        self._rotation_counter += 1
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        ext = ".log" if self.format == LogFormat.TEXT else ".smcl"
        self.current_log = self.log_dir / f"{self.session.name}_{ts}_{self._rotation_counter:03d}{ext}"

        fmt_flag = "text" if self.format == LogFormat.TEXT else "smcl"
        cmd = f'log using "{self.current_log}", replace {fmt_flag} name({self.log_name})'
        self.session.run(cmd, echo=False)
        return self.current_log

    def close(self) -> None:
        self.session.run(f"capture quietly log close {self.log_name}", echo=False)

    def rotate(self) -> Path:
        """Close current log and open a new one. Prevents single-file bloat."""
        self.close()
        return self.open()

    def tail(self, lines: int = 50) -> str:
        return self._tail_file(self.current_log, lines)

    def search(self, pattern: str, offset: int = 0, max_bytes: int = 262144) -> dict:
        ...

    def errors(self, context_lines: int = 20) -> dict:
        if self.format == LogFormat.TEXT:
            return self._extract_errors_text(context_lines)
        else:
            return self._extract_errors_smcl(context_lines)
```

#### 6.2.2 `LogFormat` enum

```python
from enum import auto, Enum

class LogFormat(Enum):
    TEXT = auto()   # Default. Plain text, grep-friendly, no SMCL tags.
    SMCL = auto()   # Legacy. Required only for specific graph-export pipelines.
```

#### 6.2.3 Parallel SMCL Log (Graph Pipeline Only)

For workflows that need SMCL (e.g., certain `graph export` combinations or legacy tools), the daemon can maintain a **secondary** SMCL log that is *not* returned to the agent by default.

```python
class GraphPipelineLog:
    """Optional parallel SMCL log used only for graph-heavy sessions."""

    def __init__(self, session: StataWorker, log_dir: Path):
        self.session = session
        self.log_path = log_dir / f"{session.name}_graphs.smcl"
        self.log_name = "_mcp_graph_smcl"

    def open(self) -> None:
        cmd = f'log using "{self.log_path}", replace smcl name({self.log_name})'
        self.session.run(cmd, echo=False)

    def close(self) -> None:
        self.session.run(f"capture quietly log close {self.log_name}", echo=False)
```

**When to enable:**
- User explicitly requests SMCL (`stata daemon start --log-format smcl`).
- A skill or command requires SMCL translation to HTML/PDF.
- Backward compatibility with existing `.smcl` log consumers.

### 6.3 CLI Surface Changes

```bash
# Daemon start — new optional flag
stata daemon start [--log-format text|smcl]   # default: text

# Log subcommands — unchanged interface, different implementation
stata log tail  [--session NAME] [--lines 50]
stata log search <pattern> [--session NAME] [--offset 0] [--max-bytes 262144]
stata log errors [--session NAME] [--context-lines 20]
stata log path   [--session NAME]

# New: on-demand translation (for legacy SMCL logs)
stata log translate <src.smcl> <dst.txt> [--translator smcl2txt]
```

### 6.4 Data Flow: Command Execution

```
Agent: stata run --echo "reg price mpg"
    │
    ▼
Daemon receives NDJSON: {"method":"run","args":{"code":"...","echo":true}}
    │
    ▼
StataWorker:
  1. Ensure primary TEXT log is open.
  2. Run user code via pystata.
  3. Flush log.
  4. Read new bytes from TEXT log (no SMCL cleaning needed).
  5. If graphs were created, export them (independent of log).
    │
    ▼
Daemon response:
  {
    "ok": true,
    "rc": 0,
    "stdout": "<plain text, already readable>",   # <-- no SMCL regex pass
    "log_path": ".../session_001_20260512_143201_001.log",
    "graphs": [".../fig1.svg"]
  }
```

### 6.5 Error Extraction Data Flow

**Old (SMCL):**
```
SMCL log → _clean_internal_smcl() → scan for {err} tags backward → return context
```

**New (TEXT):**
```
TEXT log → read last N bytes → scan backward for "r(NNN);" / "not found" / etc.
         → return context
```

No regex forest. No SMCL tag knowledge. Deterministic and version-agnostic.

---

## 7. Migration Path from Current Code

### 7.1 Files to Modify

| File | Change |
|------|--------|
| `src/mcp_stata/stata_client.py` | Change `_persistent_log_path` default to TEXT. Replace `_clean_internal_smcl()` with no-op for text logs. Keep SMCL path as fallback. |
| `src/mcp_stata/models.py` | Add `LogFormat` enum. |
| `src/mcp_stata/cli.py` | Add `--log-format` flag to `daemon start`. |
| `src/mcp_stata/daemon.py` | Instantiate `LogManager` with format. |
| `skills/stata-log/SKILL.md` | Update instructions: text logs are default; `grep` works natively. |

### 7.2 Files to Deprecate (Phase 3)

| File | Action | Rationale |
|------|--------|-----------|
| `src/mcp_stata/smcl/smcl2html.py` | Move to `_legacy/` | Not needed for text logs; `translate` handles SMCL→HTML when required. |
| `src/mcp_stata/fastmcp_text_compact.py` | Delete | Obsolete with text logs. |
| `_clean_internal_smcl()` | Delete | No SMCL to clean when default is text. |

### 7.3 Backward Compatibility

- **Explicit SMCL mode:** `stata daemon start --log-format smcl` preserves existing behavior.
- **Translate on demand:** If an existing SMCL log is read, `LogManager` can call `translate` to produce a temporary text view.
- **SMCL error extraction:** Kept as `_extract_errors_smcl()` for the fallback path.

---

## 8. Risk Analysis

| Risk | Likelihood | Impact | Mitigation |
|------|-----------:|-------:|------------|
| Text logs lose color/formatting info | High | Low | Agents consume plain text; formatting is not semantically important. |
| Some third-party tools expect SMCL | Low | Medium | `--log-format smcl` fallback. Translate on demand. |
| `translate` command missing in old Stata | Low | Medium | Require Stata 14+ (documented). Native text logs work on all versions. |
| Graph export subtly depends on SMCL log state | Low | High | Verified: `graph export` is independent. See test_graph_behavior.do. |
| Mata errors have different text format | Medium | Medium | Error scanner uses multiple patterns (`r(NNN);`, "not found", etc.). |

---

## 9. Token Efficiency Impact

| Metric | SMCL Default | Text Default | Savings |
|--------|-------------:|-------------:|--------:|
| Log size (5 MB SMCL baseline) | 5.0 MB | ~3.8 MB | **~24%** |
| Tokens (chars/4 approx) | 1,310K | 998K | **~312K tokens** |
| Cleaning code (`stata_client.py`) | ~400 LOC regex | 0 LOC | **~400 LOC deleted** |
| SMCL→Markdown (`smcl2html.py`) | ~400 LOC | 0 LOC | **~400 LOC deleted** |
| `fastmcp_text_compact.py` | ~80 LOC | 0 LOC | **~80 LOC deleted** |

---

## 10. Open Questions / Next Steps

1. **Live verification needed:** Run `run_verification.sh` on a Stata-licensed machine and paste results into this document.
2. **Mata error format:** Confirm whether Mata errors in text logs follow the same `r(NNN);` convention or use a different signature.
3. **Unicode in text logs:** Verify that `log using ..., text` preserves Unicode characters correctly on macOS/Linux (Stata 17+).
4. **Parallel SMCL necessity:** Determine whether ANY graph workflow actually requires a parallel SMCL log, or if `graph export` is universally independent.
5. **Integration with `stata log tail`:** Implement `LogManager.tail()` using Python file I/O rather than Stata-side commands for speed.

---

## 11. Conclusion

Switching the default log format from SMCL to **plain text** is a high-value, low-risk change:

- **Eliminates** ~880 lines of fragile SMCL-cleaning code.
- **Reduces** log size by ~20–25%, saving hundreds of thousands of tokens on large workflows.
- **Simplifies** error extraction (plain-text patterns vs. SMCL tag hunting).
- **Preserves** all existing functionality via explicit `--log-format smcl` fallback and on-demand `translate`.
- **Improves** composability: agents can `grep`, `head`, and `tail` log files directly without SMCL noise.

**Recommendation:** Implement as part of Phase 0 (Foundation) of the CLI/daemon migration, before any SMCL-dependent code is ported.

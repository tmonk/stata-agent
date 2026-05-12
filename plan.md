# Stata-AI: Skills-First CLI/Daemon Architecture Plan

**Date:** 2026-05-12  
**Scope:** Full migration from MCP server to a skill-first, CLI-native Stata integration.  
**Status:** Architecture validated by 12 feature reviews. Ready for implementation.

---

## 1. Executive Summary

The current `mcp-stata` project ships as a monolithic MCP server (`server.py`, ~2,500 lines) exposing ~20 tools via FastMCP. This plan defines a migration to a **skill-first, CLI-native** architecture consisting of:

- One lightweight **daemon** (`stata-daemon`) that owns Stata via `pystata` and speaks NDJSON over a Unix domain socket (TCP on Windows).
- One **CLI** (`stata`) with subcommands (`run`, `inspect`, `graph`, `log`, `task`, `daemon`, `help`, `lint`, `doctor`) that agents invoke via Bash.
- A set of **skills** (`skills/*/SKILL.md`) that tell the agent which CLI commands to run, loaded on demand.

**Key validated findings that shape this architecture:**

| Finding | Impact on Architecture |
|---------|----------------------|
| `sfi.breakIn()` does **not exist** in StataNow 19.5 (Feature 11). | Break/cancel must use **SIGTERM + worker restart**. Session state is lost on break. |
| Batch mode (`-b`) produces **text logs by default**, not SMCL (Feature 2). | Default to **text logs**; eliminate the SMCL-cleaning pipeline (~880 LOC deleted). |
| `graph dir, memory` captures all graph state in **0.000s** (Feature 4). | Replace ~1,010 LOC of streaming graph cache with a **20-line post-run delta check**. |
| SMCL `{err}` tags miss Mata errors and assertions (Feature 5). | Use **structured markers** (`[MCP-ERROR]`) injected via `capture noisily` wrappers. |
| `stata-se -b` blocks `help`; `-q` produces clean stdout text (Feature 12). | `stata help` is a **stateless subprocess**; no daemon involvement. |
| pystata is single-threaded; one command blocks the session (Feature 7). | Background tasks are **queued per session**, not parallel within a session. |
| Stata batch mode **always returns exit code 0**, even on errors (Feature 9). | Error detection is **log-parser based**, never process-exit-code based. |
| Text logs are ~20–25% smaller than SMCL and `grep`-native (Feature 3). | Error extraction uses plain-text regex (e.g., `r(111);`, `assertion is false`). |

---

## 2. Target Architecture

### 2.1 Component Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  Agent Context                                                               │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐                         │
│  │ SKILL.md    │  │ SKILL.md    │  │ SKILL.md    │  ...                     │
│  │ stata-run   │  │ stata-inspect│  │ stata-graph │                         │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘                         │
│         └─────────────────┴─────────────────┘                                │
│                           │                                                  │
│                    ┌──────┴──────┐                                          │
│                    │  Bash tool  │                                          │
│                    └──────┬──────┘                                          │
└───────────────────────────┼─────────────────────────────────────────────────┘
                            │
              ┌─────────────┴─────────────┐
              │   `stata` CLI binary      │
              │   (Python entry point)    │
              │   • argparse subcommands  │
              │   • thin NDJSON client    │
              └─────────────┬─────────────┘
                            │ NDJSON over Unix socket / TCP localhost
              ┌─────────────┴─────────────┐
              │   `stata-daemon`          │
              │   (1 per user)            │
              │   • NDJSON router         │
              │   • Task queue            │
              │   • Log manager           │
              │   • Worker process pool   │
              └─────────────┬─────────────┘
                            │ multiprocessing.spawn + Pipe
              ┌─────────────┴─────────────┐
              │   StataWorker(s)          │
              │   • 1 per named session   │
              │   • pystata / SFI         │
              │   • text-log capture      │
              │   • structured markers    │
              └─────────────┬─────────────┘
                            │
              ┌─────────────┴─────────────┐
              │   Stata Engine            │
              │   (persistent state)      │
              └───────────────────────────┘
```

### 2.2 Design Principles

1. **Progressive disclosure.** Load only the skill you need (~150 tokens), when you need it. No perpetual MCP schema tax.
2. **Never return the full log by default.** A 5 MB log is ~1.3M tokens. The default response is either a truncated tail (success) or extracted error context (failure), plus a `log_path`.
3. **Text-first logs.** Open logs as `log using ..., text` from the start. Eliminates SMCL cleaning and reduces token noise by ~20–25%.
4. **Explicit graph export.** The daemon reports graph deltas (created/dropped/current) after each command. The agent decides what to export.
5. **Process-level isolation.** Each session is a separate `multiprocessing.spawn` worker. Break/cancel kills the worker with SIGTERM and restarts it.
6. **Stateless where possible.** `help`, `lint`, `doctor`, and `discover` need no daemon session. They run as standalone CLI commands or thin subprocess wrappers.

---

## 3. CLI Surface

A single entry point `stata` with subcommands.

```bash
# Lifecycle
stata daemon start  [--session NAME] [--port 0] [--log-format text|smcl]
stata daemon stop   [--session NAME]
stata daemon status [--session NAME]

# Execution
stata run [--session NAME] [--echo] [--background] [--strict] [--max-output-lines N] "code"
stata run [--session NAME] [--echo] [--background] --file /path/to/file.do
stata break [--session NAME]

# Data & Inspection
stata inspect describe  [--session NAME] [varlist] [--fullnames]
stata inspect summary   [--session NAME] [varlist]
stata inspect codebook  [--session NAME] [varlist]
stata inspect list      [--session NAME] [varlist] [--from N] [--count M]
stata inspect get       [--session NAME] [--format csv|json|arrow] [--out /path]
stata inspect sample    [--session NAME] [--method head|tail|random|systematic] [--count N]

# Results
stata results [--session NAME] [--return r|e|s]

# Graphs
stata graph list   [--session NAME]
stata graph export [--session NAME] --name NAME --format pdf|png|svg [--out /path]
stata graph export-all [--session NAME] --format pdf|png [--outdir /path]

# Help (stateless — no daemon)
stata help <topic> [--format syntax|options|examples|summary|full] [--max-lines N]

# Logs
stata log tail   [--session NAME] [--lines N] [--bytes N]
stata log search <pattern> [--session NAME] [--offset 0] [--max-bytes N]
stata log errors [--session NAME] [--context-lines N]
stata log path   [--session NAME]

# Background Tasks
stata task status  --task-id ID [--wait] [--timeout N] [--tail-lines N]
stata task cancel  --task-id ID
stata task list    [--session NAME]

# Utilities
stata lint   /path/to/file.do
stata doctor
stata discover

# Mock mode (for CI / no-license testing)
stata daemon start --mock
```

**Key behaviors:**
- `--session` defaults to `default`.
- `stata run` auto-starts the daemon if not running (with a warning printed to stderr).
- `--background` returns a `task_id`; the agent polls with `stata task status --task-id ID --wait`.
- `--strict` disables the `capture noisily` wrapper so Stata stops on error natively (useful for do-files that rely on `set break` semantics).
- All output defaults to compact markdown; `--json` available for structured consumers.

---

## 4. Daemon Protocol

### 4.1 Transport

- **macOS/Linux:** Unix domain socket at `~/.cache/mcp-stata/sessions/<name>.sock`
- **Windows:** TCP `127.0.0.1:<port>`
- **Metadata:** `~/.cache/mcp-stata/sessions/<name>.json` contains transport details.

### 4.2 Wire Format: NDJSON

Every message is a single line of JSON terminated by `\n`. No HTTP headers.

**Request:**
```json
{"id": "uuid", "method": "run", "args": {"code": "reg price mpg", "echo": true}}
```

**Response (success):**
```json
{"id": "uuid", "ok": true, "stdout": "...", "rc": 0, "log_path": "/tmp/...", "graphs": {"created":["g1"],"dropped":[],"current":["g1","g2"]}}
```

**Response (error):**
```json
{"id": "uuid", "ok": false, "error": "variable y not found", "error_code": "STATA_ERROR", "rc": 111, "error_context": "...", "log_path": "/tmp/..."}
```

**Streaming notification (background tasks):**
```json
{"event": "task_started", "task_id": "...", "log_path": "..."}
{"event": "progress", "task_id": "...", "percent": 45, "eta_seconds": 28}
{"event": "task_done", "task_id": "...", "rc": 0, "log_path": "..."}
```

### 4.3 Supported Methods

| Method | Args | Returns |
|--------|------|---------|
| `run` | `code`, `echo`, `background`, `strict`, `max_output_lines` | `stdout`, `rc`, `log_path`, `graphs`, `task_id` (if background) |
| `run_file` | `path`, `echo`, `background`, `strict` | same as `run` |
| `break` | — | `acknowledged`, `worker_restarted`, `note` |
| `inspect_describe` | `varlist`, `fullnames` | `text`, `variables`, `dataset` |
| `inspect_summary` | `varlist` | `variables` (stats dict) |
| `inspect_codebook` | `varlist` | `variables` (text per var) |
| `inspect_list` | `varlist`, `from`, `count` | `rows`, `total_obs`, `returned` |
| `inspect_get` | `format`, `out_path`, `varlist`, `obs_range` | `path`, `size_bytes` |
| `results` | `class` (r/e/s) | `stored_results` |
| `graph_list` | — | `graph_names` |
| `graph_export` | `name`, `format`, `out_path` | `file_path` |
| `log_tail` | `lines`, `bytes` | `text` |
| `log_search` | `pattern`, `offset`, `max_bytes` | `matches`, `next_offset` |
| `log_errors` | `context_lines` | `rc`, `message`, `context`, `source` |
| `task_status` | `task_id`, `wait`, `timeout`, `tail_lines` | `status`, `percent`, `eta_seconds`, `rc`, `log_tail` |
| `task_cancel` | `task_id` | `cancelled` |
| `task_list` | — | `tasks[]` |
| `health` | — | `status`, `pid`, `session_name` |
| `stop` | — | `acknowledged` |

---

## 5. Session & Worker Model

### 5.1 Session Lifecycle

- **1 daemon process** per user. Lightweight NDJSON router.
- **1 StataWorker process** per named session. Default session is `"default"`.
- Workers are spawned via `multiprocessing.get_context("spawn")` and communicate with the daemon over a `multiprocessing.Pipe`.
- Workers are reused across CLI invocations, preserving Stata state (`use auto`, then `reg price mpg`).
- If a worker crashes or is killed (break/cancel), the daemon auto-restarts it on the next request.
- No history snapshots, no diff tracking, no profile code.

### 5.2 Worker Isolation

The daemon uses **Option A: Pipe-based worker** because:
1. The current `worker.py` already works.
2. `pystata`/`sfi` has known thread-safety limitations.
3. The pipe abstraction isolates Stata crashes from the daemon.

### 5.3 Auto-Start

`stata run` auto-starts the default-session daemon if not running. The CLI prints a warning to stderr so the agent knows what happened. Named sessions must be started explicitly: `stata daemon start --session thesis`.

### 5.4 Idle Timeout

The daemon shuts down after 30 minutes of inactivity, cleaning up sockets and workers. The next `stata run` auto-starts it again.

---

## 6. Log Management — The Critical Path

### 6.1 Default: Text Logs

The daemon opens the session log as **plain text** from the start:

```stata
log using "<path>", replace text name(_mcp_session)
```

This eliminates the need for SMCL cleaning and reduces token noise by ~20–25%.

### 6.2 Default Response Contract

**On success:**
```
[stata] ✓ Completed (rc=0, 45.2s)
[stata] Output truncated to last 1,000 tokens.
[stata] Full log: ~/.cache/mcp-stata/logs/default_20260512_143201_001.log

... (last ~1,000 tokens of plain text output) ...
```

**On failure:**
```
[stata] ✗ Failed (rc=111)
[stata] Error: variable z_nonexistent not found
[stata] Context:
  . regress y z_nonexistent
  variable z_nonexistent not found
  r(111);
[stata] Full log: ~/.cache/mcp-stata/logs/default_20260512_143201_001.log
```

### 6.3 Log Subcommands

```bash
stata log tail   [--session NAME] [--lines 50] [--bytes 65536]
stata log search <pattern> [--session NAME] [--offset 0] [--max-bytes 262144]
stata log errors [--session NAME] [--context-lines 20]
stata log path   [--session NAME]
```

### 6.4 Log Rotation

| Aspect | Rule |
|--------|------|
| Location | `~/.cache/mcp-stata/logs/<session>_<timestamp>_<seq>.log` |
| Rotation trigger | Every 100 commands OR every 50 MB |
| Format | Plain text by default; SMCL only if daemon started with `--log-format smcl` |
| Persistence | Kept for daemon lifetime; TTL cleanup every 24h |
| Agent access | Direct `read` of the file path once disclosed |

### 6.5 Backward Error Scan

- **Fast path:** Read the last 32 KB of the log, scan lines in reverse for error signatures (`r(NNN);`, `not found`, `assertion is false`, `<istmt>: NNN`). Expected time: **<1 ms** for typical errors (which are always near the tail).
- **Fallback:** Only if the fast path yields nothing, scan deeper with chunked reads. Full backward scan of a 6.4 MB file: **~80–125 ms**.

---

## 7. Structured Error Extraction

### 7.1 Stata-Side Wrapper

Every user command is wrapped in `capture noisily` with structured marker injection:

```stata
capture noisily {
    <user code>
}
if _rc != 0 {
    display as error "[MCP-ERROR] rc=" _rc
    display as error "[MCP-MSG] `:display _rc[message]'"
}
```

This catches **all** error types that set `_rc`: standard errors, Mata errors, assertions, program errors, nested errors.

### 7.2 Python Parser

The daemon's `ErrorExtractor` operates in two phases:

1. **Phase 1 (forward scan):** Look for `[MCP-ERROR]` and `[MCP-MSG]` markers. Authoritative when present.
2. **Phase 2 (fallback backward scan):** Scan backwards for native text error signatures:
   - `r(NNN);` — Stata return codes
   - `<istmt>: NNN <msg>` — Mata errors
   - `assertion is false` — Assertion failures
   - `not found`, `invalid syntax`, `no observations` — Common errors

### 7.3 Mata Mode

Mata commands (`mata: ...` or `mata ... end`) are detected and wrapped with `capture noisily mata: ...`.

### 7.4 `--strict` Mode

When `stata run --strict` is used, the daemon skips the `capture noisily` wrapper and runs the code natively. This preserves Stata's native stop-on-error semantics for do-files that depend on it. The parser falls back to Phase 2 backward scan.

### 7.5 File Mode

For `stata run --file analysis.do`, the daemon wraps the entire `do "file.do"` call in a single `capture noisily` block. The `_rc` reflects the **last** command in the do-file. This is the correct semantic choice; the daemon should not second-guess do-file control flow.

---

## 8. Graph Handling

### 8.1 Delta Detection

The daemon runs `graph dir, memory` before and after each command, then computes the delta:

```python
before = snapshot_graphs(stata)   # set of names from r(list)
# ... run user code ...
after = snapshot_graphs(stata)
delta = {
    "created": sorted(after - before),
    "dropped": sorted(before - after),
    "current": sorted(after),
}
```

This replaces ~1,010 LOC of streaming graph cache with ~20–40 LOC.

### 8.2 Export is Explicit

The agent decides what to export and when:

```bash
stata run --echo "twoway scatter price mpg, name(fig1, replace)"
stata graph export --name fig1 --format svg --out ./figures/fig1.svg
```

`graph export-all` iterates over `snapshot_graphs()` and exports each one.

### 8.3 Unnamed Graphs

Stata maintains exactly one unnamed graph, named `"Graph"` in `r(list)`. The skill encourages the agent to name graphs explicitly. `export-all` renames `"Graph"` to `_unnamed`.

---

## 9. Break / Cancel

### 9.1 Reality Check

- `sfi.breakIn()` **does not exist** in StataNow 19.5.
- SIGINT is ignored by Stata (SIG_IGN). Only SIGTERM reliably stops a running Stata command.
- The current `_request_break_in()` code in `stata_client.py` is a **silent no-op**.

### 9.2 Architecture: SIGTERM + Worker Restart

```
CLI: stata break
  → Daemon sends SIGTERM to the worker subprocess
  → Worker dies immediately (state lost)
  → Daemon auto-restarts a fresh worker
  → CLI prints: "Break acknowledged. Worker restarted. Session state has been reset."
```

### 9.3 Cancellation

For background tasks, `stata task cancel --task-id ID` sends SIGTERM to the worker running the task, then restarts the worker. The task registry is updated to `cancelled`.

### 9.4 Optional Checkpointing (Future)

Before long-running commands, the daemon can auto-save the dataset to `~/.cache/mcp-stata/checkpoints/<session>/`. On restart after break, the daemon offers to restore the checkpoint.

---

## 10. Help System

### 10.1 Stateless Subprocess

Help is read-only and fast (~28ms). It does **not** route through the daemon. The CLI runs:

```bash
stata-se -q -e "help <topic>"
```

with `TERM=dumb` to suppress terminal escape sequences.

### 10.2 Why Not Batch Mode

`stata-se -b` blocks help with `"request ignored because of batch mode"`. `-q` (quiet interactive) is required.

### 10.3 Section Extraction

`help regress` is ~20 KB / ~5,000 tokens. The CLI supports section extraction:

```bash
stata help regress --format syntax    # Syntax only
stata help regress --format options   # Options only
stata help regress --format examples  # Examples only
stata help regress --format summary   # Syntax + Stored results
stata help regress --max-lines 100    # Hard line cap
```

### 10.4 What Gets Deleted

- `get_help()` in `stata_client.py` (~80 LOC)
- Early interception logic in `run_command_streaming()` (~60 LOC)
- `_extract_help_topic()`, `_HELP_TOPIC_RE`, `_HELP_BARE_RE` (~30 LOC)
- SMCL→Markdown help path in `smcl2html.py` (~400 LOC)
- **Total:** ~570 LOC deleted

---

## 11. Mock / Stata-Free Test Mode

### 11.1 Purpose

Enable CI tests and development without a Stata license. The mock daemon speaks the same NDJSON protocol as the real daemon.

### 11.2 Architecture

```
Mock Daemon
  ├── Command Router (regex/prefix/exact matching)
  ├── Response Database (JSON file of canned responses)
  ├── Syntax Validator (lightweight regex-based Stata validator)
  └── State Machine (optional, minimal)
```

### 11.3 Response Database

A JSON file maps normalized commands to response objects. Example entry:

```json
{
  "pattern": "sysuse auto, clear",
  "type": "exact",
  "response": {
    "success": true,
    "rc": 0,
    "output": "(1978 automobile data)",
    "state_updates": {
      "dataset": {
        "name": "auto",
        "observations": 74,
        "variables": ["make", "price", "mpg", ...]
      }
    }
  }
}
```

### 11.4 CLI Activation

```bash
stata daemon start --mock
```

All subsequent `stata` commands talk to the mock backend.

---

## 12. Skill Migration

### 12.1 Directory Layout

```
mcp-stata/
├── skills/                          # NEW top-level
│   ├── stata-toolkit/
│   │   └── SKILL.md                 # Root skill (~400 tokens)
│   ├── stata-run/
│   │   └── SKILL.md                 # (~150 tokens)
│   ├── stata-inspect/
│   │   └── SKILL.md                 # (~125 tokens)
│   ├── stata-graph/
│   │   └── SKILL.md                 # (~150 tokens)
│   ├── stata-log/
│   │   └── SKILL.md                 # (~130 tokens)
│   ├── stata-results/
│   │   └── SKILL.md                 # (~100 tokens)
│   ├── stata-help/
│   │   └── SKILL.md                 # (~100 tokens)
│   ├── stata-lint/
│   │   └── SKILL.md                 # (~120 tokens)
│   ├── stata-setup/
│   │   └── SKILL.md                 # (~280 tokens)
│   ├── stata-environment-diagnose/
│   │   └── SKILL.md                 # (~100 tokens)
│   ├── stata-causal-inference/
│   │   ├── SKILL.md
│   │   └── references/
│   ├── stata-data-audit/
│   │   ├── SKILL.md
│   │   └── references/
│   ├── stata-replication/
│   │   ├── SKILL.md
│   │   └── scripts/
│   ├── stata-publication-qa/
│   │   ├── SKILL.md
│   │   └── scripts/
│   └── ...
│
├── plugin/                          # DEPRECATED during Phase 3
│   └── skills -> ../skills          # Symlink preserved
```

### 12.2 Command Mapping (MCP → CLI)

| Current MCP Function | CLI Replacement | Skill |
|---------------------|-----------------|-------|
| `stata_run(code, echo)` | `stata run --echo "..."` | `stata-run` |
| `stata_run(code, is_file=True)` | `stata run --echo --file /path.do` | `stata-run` |
| `stata_run(code, background=True)` | `stata run --background --echo ...` | `stata-run` |
| `stata_inspect_data(action="describe")` | `stata inspect describe` | `stata-inspect` |
| `stata_inspect_data(action="summary")` | `stata inspect summary [varlist]` | `stata-inspect` |
| `stata_inspect_data(action="codebook")` | `stata inspect codebook [varlist]` | `stata-inspect` |
| `stata_inspect_data(action="list")` | `stata inspect list [varlist] [--from N]` | `stata-inspect` |
| `stata_inspect_data(action="get")` | `stata inspect get --format csv --out /path` | `stata-inspect` |
| `stata_inspect_data(action="lint")` | `stata lint /path/to/file.do` | `stata-lint` |
| `stata_manage_graphs(action="list")` | `stata graph list` | `stata-graph` |
| `stata_manage_graphs(action="export")` | `stata graph export --name NAME --format png` | `stata-graph` |
| `stata_manage_graphs(action="export_all")` | `stata graph export-all --format png --outdir ./figures` | `stata-graph` |
| `stata_get_results(include_matrices=True)` | `stata results [--return r\|e\|s]` | `stata-results` |
| `stata_read_log(path, tail_lines=50)` | `stata log tail --lines 50` | `stata-log` |
| `stata_read_log(path, query=...)` | `stata log search <pattern>` | `stata-log` |
| `stata_help(topic)` | `stata help <topic>` | `stata-help` |
| `stata_manage_session(action="detect")` | Implicit in first `stata run` | `stata-setup` |
| `stata_manage_session(action=...)` | `stata daemon start/stop/status` | `stata-toolkit` |
| `stata_task_status(task_id, wait=True)` | `stata task status --task-id <id> --wait` | `stata-run` |
| `stata_control(action="break")` | `stata break [--session NAME]` | `stata-toolkit` |
| `stata_control(action="cancel")` | `stata task cancel --task-id <id>` | `stata-toolkit` |
| `stata_load_data(path)` | `stata run --echo "use ..."` | `stata-run` |
| `stata_doctor()` | `stata doctor` | `stata-toolkit` |
| `write_file(path, content)` | Agent's native `write` tool | — |

### 12.3 Log-Handling Discipline (Embedded in Every Skill)

Every skill that calls `stata run` must remind the agent:

> 1. If a command fails (`rc != 0`), run `stata log errors` first. This is fast (< 5 ms) and returns ~64 tokens of error context.
> 2. Only if the error context is ambiguous, use `stata log tail --lines 100` or `stata log search <pattern>`.
> 3. Never read the full log file into context.

---

## 13. File-Level Migration Plan

### 13.1 New / Rewritten Files

| Path | Action | Description |
|------|--------|-------------|
| `src/mcp_stata/cli.py` | **Create** | Argparse subcommands; thin wrapper around RPC client. |
| `src/mcp_stata/cli_help.py` | **Create** | Stateless help subcommand (subprocess `-q` mode + section extractor). |
| `src/mcp_stata/daemon.py` | **Create** | NDJSON server; process manager; spawns `StataWorker`s. |
| `src/mcp_stata/rpc_client.py` | **Create** | Connects to daemon socket; sends NDJSON; returns parsed dict. |
| `src/mcp_stata/task_queue.py` | **Create** | In-memory task registry with LRU eviction. |
| `src/mcp_stata/background_runner.py` | **Create** | Async background execution + progress extraction. |
| `src/mcp_stata/log_manager.py` | **Create** | Log rotation, tail, search, backward error scan. |
| `src/mcp_stata/error_extractor.py` | **Create** | Structured marker parser + fallback text scanner. |
| `src/mcp_stata/graph_delta.py` | **Create** | Pre/post `graph dir, memory` delta computation. |
| `src/mcp_stata/mock_daemon.py` | **Create** | Protocol-compatible mock backend for CI. |
| `src/mcp_stata/__main__.py` | **Rewrite** | Entry point: `python -m mcp_stata` → `stata` CLI. |

### 13.2 Heavily Refactored Files

| Path | Action | Description |
|------|--------|-------------|
| `src/mcp_stata/sessions.py` | **Refactor** | Strip to ~100 LOC: worker spawn, pipe routing, stop/kill. Remove history, snapshots, diff, profile. |
| `src/mcp_stata/worker.py` | **Refactor** | Remove profile code, simplify message types, keep break signal pipe listener (for SIGTERM coordination). |
| `src/mcp_stata/stata_client.py` | **Refactor** | Remove `get_help()`, `_clean_internal_smcl()`, early-interception logic, `as_json` parameters. Unify `run_command`/`run_do_file`. Default to text logs. |

### 13.3 Preserved Files (mostly unchanged)

| Path | Note |
|------|------|
| `src/mcp_stata/discovery.py` | Still needed for auto-discovery and `stata doctor`. |
| `src/mcp_stata/linter.py` | Still needed for `stata lint`. |
| `src/mcp_stata/graph_detector.py` | **Evaluate** — may be deleted after graph delta is implemented. |
| `src/mcp_stata/native_ops.py` / Rust extension | Still needed for fast sorting/filtering if used by data inspection. |
| `src/mcp_stata/models.py` | Keep Pydantic models; strip MCP envelope types. |
| `src/mcp_stata/config.py` | Unchanged. |
| `src/mcp_stata/utils.py` | Unchanged. |

### 13.4 Deprecated / Removed Files

| Path | Action |
|------|--------|
| `src/mcp_stata/server.py` | **Move** to `src/mcp_stata/_legacy/mcp_server.py`. Keep for transition. Remove FastMCP import from top-level init. |
| `src/mcp_stata/fastmcp_text_compact.py` | **Delete** after text-log migration. |
| `src/mcp_stata/toolkit_catalog_data.py` | **Delete** after skill rewrite. |
| `src/mcp_stata/ui_http.py` | **Evaluate** — make optional or delete. |
| `src/mcp_stata/smcl/smcl2html.py` | **Move** to `_legacy/` — not needed for text logs; keep for `--log-format smcl` fallback. |

---

## 14. Implementation Phases

### Phase 0: Foundation (4–6 weeks)

**Goal:** Build the CLI/daemon without breaking the existing MCP server.

- [ ] Create `cli.py`, `rpc_client.py`, `daemon.py`.
- [ ] Implement `stata daemon start/stop/status`.
- [ ] Implement `stata run` and `stata inspect describe`.
- [ ] Refactor `sessions.py` to remove history/diff/snapshots (~100 LOC target).
- [ ] Switch default log format to **text** in `stata_client.py`.
- [ ] Add `pyproject.toml` script entry: `stata = "mcp_stata.cli:main"`.
- [ ] Shell-level tests: start, run, stop, state persistence.
- [ ] **Pseudocode for Phase 0 files:** See `features/01-cli-daemon/review.md` §3 (cli.py, daemon.py, rpc_client.py, session spawn).

### Phase 1: Feature Parity (4–6 weeks)

**Goal:** Every MCP tool has a CLI equivalent.

- [ ] `stata graph list / export / export-all` (graph_delta.py).
- [ ] `stata results`.
- [ ] `stata help` (cli_help.py, stateless subprocess).
- [ ] `stata log tail / search / errors` (log_manager.py).
- [ ] `stata lint`.
- [ ] `stata doctor`.
- [ ] `stata run --background` + `stata task status/cancel/list` (task_queue.py, background_runner.py).
- [ ] `stata break` (SIGTERM + restart).
- [ ] `stata inspect summary / codebook / list / get / sample`.
- [ ] **Pseudocode for Phase 1 files:**
  - Log management: `features/02-log-mitigation/review.md` §3 (LogRotator, Truncator, BackwardScanner, PaginatedReader).
  - Text-first logs: `features/03-text-first-logs/review.md` §5 (LogManager, LogFormat, translate wrapper).
  - Graph handling: `features/04-graph-handling/review.md` §5 (snapshot_graphs, compute_graph_delta, export_graph).
  - Error extraction: `features/05-error-extraction/review.md` §5 (ErrorWrapper, ErrorExtractor, daemon integration).
  - Session management: `features/06-session-management/review.md` §3–4 (simplified session dict, worker spawn, auto-start).
  - Background tasks: `features/07-background-tasks/review.md` §4 (TaskQueue, BackgroundRunner, status endpoint).
  - Data inspection: `features/08-data-inspection/review.md` §4 (InspectHandler, FormatConverter, Sampler).
  - Help system: `features/12-help-system/review.md` §3 (help_command, limit_help_output, resolve_topic).

### Phase 2: Skill Migration (2–3 weeks)

**Goal:** Rewrite all skills to reference CLI commands.

- [ ] Rewrite `stata-toolkit/SKILL.md` as root skill.
- [ ] Rewrite core specialist skills (`stata-run`, `stata-inspect`, `stata-graph`, `stata-log`, `stata-results`, `stata-help`, `stata-lint`, `stata-setup`).
- [ ] Rewrite workflow specialist skills (`stata-causal-inference`, `stata-data-audit`, etc.).
- [ ] Add `scripts/` subdirs where Python helpers are needed.
- [ ] Remove/repurpose `manifest.json` and `tool-reference.md`.
- [ ] Validate token budgets with `scripts/count_skill_tokens.py`.
- [ ] **Mapping reference:** `features/10-skill-migration/review.md` §3.4 and §4.

### Phase 3: Mock Backend & CI (2–3 weeks)

**Goal:** Enable tests without a Stata license.

- [ ] Create `responses/canned.json` with entries for common commands.
- [ ] Implement `mock_daemon.py` (command router + response DB + syntax validator).
- [ ] Write `tests/cli/test_mock_mode.sh`.
- [ ] GitHub Actions workflow: `ci-mock.yml`.
- [ ] **Pseudocode for mock backend:** `features/09-mock-test-mode/review.md` §5.

### Phase 4: Deprecation & Cleanup (1–2 weeks)

**Goal:** Make MCP optional, then remove it.

- [ ] Move `server.py` to `mcp_stata._legacy_server`.
- [ ] Make `mcp[cli]` an optional dependency (`pip install mcp-stata[mcp]`).
- [ ] Update installer to add `stata` to PATH and add skills folder to agent working dirs.
- [ ] Update README: lead with skills/CLI; move MCP to "Alternative transport" appendix.

### Phase 5: Polish (ongoing)

- [ ] Native shell completions (`stata --bash-completion`).
- [ ] `stata run --file -` to accept stdin.
- [ ] Final token audit: compare MCP vs. skills for a standard regression workflow.
- [ ] **Pseudocode for break/cancel (updated):** `features/11-break-cancel/review.md` §4 (SIGTERM + restart architecture).

---

## 15. Risk Analysis & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| **sfi.breakIn() missing** | High | Use SIGTERM + worker restart (Feature 11 review). |
| **Windows socket support** | High | TCP localhost on Windows; Unix sockets on macOS/Linux (Feature 1 review). |
| **pystata not in system Python** | Medium | Daemon runs inside the project's venv where `stata_setup` is configured. Subprocess fallback for non-pystata environments (Feature 1 review). |
| **Daemon crash loses Stata state** | Medium | Identical to MCP server crash today. Auto-restart on next request. Document that long jobs should use `--background`. |
| **Agent forgets to start daemon** | Low | `stata run` auto-starts with stderr warning. |
| **Multiple agents collide on default session** | Low | Session names isolate state. Default is per-user; concurrent agents share state (document `--session` best practices). |
| **Text logs break graph export** | Low | Verified: `graph export` is independent of log format (Feature 4 review). |
| **SMCL tags lost in text logs** | Low | SMCL is opt-in (`--log-format smcl`). Translate on-demand for legacy. |
| **Backward scan misses errors** | Low | Structured markers catch 100% of `_rc`-setting errors. Fallback regex covers Mata, assertions, and standard errors (Feature 5 review). |
| **Mock mode gives false confidence** | Medium | Always run a subset of tests against real Stata before release (Feature 9 review). |
| **Help system `-q` mode differences** | Low | Tested on StataNow 19.5. `-q` supported since Stata 9 (Feature 12 review). |

---

## 16. Success Criteria

1. A standard regression workflow (`use auto`, `reg price mpg`, `esttab`, export graph) executes via Bash CLI + skills with **no MCP tool schema** in context.
2. **Total skill tokens** for an active Stata workflow ≤ 600 tokens (root + one specialist).
3. A **5 MB log** returns an error context of < 200 tokens in < 5 ms (fast path).
4. The **daemon starts in < 2s** and `stata run "display 1+1"` returns in < 3s on a warm session.
5. All existing unit tests for `stata_client`, `discovery`, `SMCL` (legacy path), and `linter` pass.
6. **Mock mode** runs the full CLI test suite without a Stata license.
7. **Skills are loadable** by pi/Claude Code/Cursor via standard `@skills/stata-run/SKILL.md` patterns.

---

## 17. References to Feature Reviews

Each feature review contains detailed pseudocode, test results, and implementation checklists. Coders should read the relevant review before implementing each subsystem.

| Feature | Review File | Contains Pseudocode For |
|---------|-------------|------------------------|
| 01 CLI-Daemon Core | `features/01-cli-daemon/review.md` | `cli.py`, `daemon.py`, `rpc_client.py`, session spawn, NDJSON protocol spec, transport auto-detection. |
| 02 Log Mitigation | `features/02-log-mitigation/review.md` | `LogRotator`, `Truncator`, backward `ErrorScanner`, `PaginatedReader`, performance benchmarks, file lifecycle rules. |
| 03 Text-First Logs | `features/03-text-first-logs/review.md` | `LogManager`, `LogFormat` enum, text-log initialization, SMCL→text `translate` fallback, error extraction for text logs. |
| 04 Graph Handling | `features/04-graph-handling/review.md` | `snapshot_graphs()`, `compute_graph_delta()`, `export_graph()`, CLI `graph list/export/export-all`, unnamed graph handling. |
| 05 Error Extraction | `features/05-error-extraction/review.md` | `ErrorWrapper` (Stata-side `capture noisily` + markers), `ErrorExtractor` (Python parser), Mata/assertion handling, `--strict` mode. |
| 06 Session Management | `features/06-session-management/review.md` | Simplified session dict, auto-start logic, named session routing, `multiprocessing.spawn` worker, what to remove from `sessions.py`. |
| 07 Background Tasks | `features/07-background-tasks/review.md` | `TaskQueue`, `BackgroundRunner`, progress marker extraction, ETA estimation, `stata task status/cancel/list` CLI. |
| 08 Data Inspection | `features/08-data-inspection/review.md` | `InspectHandler`, `FormatConverter` (CSV/JSON/Arrow), `Sampler` (head/tail/random/systematic), CLI inspect subcommands. |
| 09 Mock Test Mode | `features/09-mock-test-mode/review.md` | `mock_daemon.py`, response database JSON schema, `command_router`, `syntax_validator`, `state_machine`, CI pipeline. |
| 10 Skill Migration | `features/10-skill-migration/review.md` | Skill directory layout, command mapping table (MCP → CLI), token budgets, skill template, `count_skill_tokens.py`. |
| 11 Break/Cancel | `features/11-break-cancel/review.md` | SIGTERM-based break, worker restart architecture, signal handler, cleanup after break, current dead-code analysis. |
| 12 Help System | `features/12-help-system/review.md` | Stateless `stata help` CLI, section extraction, topic resolution, terminal escape stripping, what to delete from `stata_client.py`. |

---

*End of plan. This document, together with the 12 feature reviews, constitutes the complete implementation specification.*

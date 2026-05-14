# Features & Flows Inventory

> Generated 2026-05-14 as part of the performance benchmark phase.
> This document enumerates every real-Stata flow in the stata-agent codebase,
> with code locations, entry points, and dependencies.

---

## 1. CLI-Daemon Lifecycle

| Property | Value |
|----------|-------|
| **Entry point** | `stata daemon start\|stop\|status [--session NAME] [--mock]` |
| **Source** | `src/stata_agent/cli.py` — `cmd_daemon_start()`, `cmd_daemon_stop()`, `cmd_daemon_status()` |
| **Core classes** | `StataDaemon` in `daemon.py`, `SessionManager` in `session.py` |
| **Transport** | Unix domain socket (NDJSON protocol) via `JsonProtocol` in `daemon.py` |
| **Key sub-flows** | |
| | `_start_daemon()` — spawns daemon subprocess, polls for socket |
| | `_ensure_daemon()` — auto-starts daemon if not running |
| | `RpcClient._connect()` — Unix socket or TCP fallback |
| | `StataDaemon.start()` — creates socket, listens for connections |
| | `SessionManager.get_or_create()` — spawns/reuses worker processes |

---

## 2. Code Execution (`run`)

| Property | Value |
|----------|-------|
| **Entry point** | `stata run [--session NAME] [--echo] [--background] [--strict] <code>` |
| **Source** | `cli.py` → `cmd_run()` → `RpcClient.call("run", ...)` → `StataDaemon.dispatch("run", ...)` → `_call_worker()` → `_dispatch()` in `worker.py` → `StataClient.run()` in `stata_client.py` |
| **Core classes** | `RpcClient`, `StataDaemon`, `StataClient`, `WorkerHandle` |
| **Key sub-flows** | |
| | `cmd_run()` — validates args, calls RPC, prints result |
| | `RpcClient.call()` — sends NDJSON request, reads response |
| | `_call_worker()` — sends method over multiprocessing.Pipe, waits for result |
| | `StataClient.run()` — wraps code in `capture noisily`, executes via `pystata.stata.run()`, extracts errors, computes graph delta |
| | `_print_run_result()` — formats stdout, graphs, errors |
| | `run_file` variant — same path but loads code from `.do` file |

---

## 3. Break/Cancel

| Property | Value |
|----------|-------|
| **Entry point** | `stata break [--session NAME]` |
| **Source** | `cli.py` → `cmd_break()` → `RpcClient.call("break", ...)` → `StataDaemon.dispatch("break", ...)` → `SessionManager.send_break()` |
| **Core classes** | `SessionManager` in `session.py` |
| **Key sub-flows** | |
| | `SessionManager.send_break()` — sends SIGTERM to worker, cleans up, auto-restarts |
| | Worker restart — new process spawned transparently |

---

## 4. Data Inspection

| Property | Value |
|----------|-------|
| **Entry point** | `stata inspect describe|summary|codebook|list|get [varlist...]` |
| **Source** | `cli.py` → `cmd_inspect_describe/summary/codebook/list/get()` → `RpcClient.call("inspect_*", ...)` → `StataDaemon.dispatch("inspect_*", ...)` → worker → `StataClient.inspect_*()` |
| **Core classes** | `StataClient` in `stata_client.py` |
| **Key sub-flows** | |
| | `inspect_describe()` — reads variable names/types/labels via SFI `Data` API |
| | `inspect_summary()` — runs `summarize, detail`, reads log |
| | `inspect_codebook()` — runs `codebook`, reads log |
| | `inspect_list()` — runs `list`, reads log |
| | `inspect_get()` — exports data as CSV/JSON/Arrow via `export delimited`, `jsonio`, or pyarrow |

---

## 5. Graph Operations

| Property | Value |
|----------|-------|
| **Entry point** | `stata graph list|export|export-all [options]` |
| **Source** | `cli.py` → `cmd_graph_list/export/export_all()` → `RpcClient.call("graph_list"/"graph_export", ...)` |
| **Core classes** | `StataClient` in `stata_client.py` (snapshot_graphs, export_graph) |
| **Key sub-flows** | |
| | `snapshot_graphs()` — runs `quietly graph dir, memory`, parses `r(list)` |
| | `export_graph()` — runs `graph display` + `graph export` |
| | `compute_graph_delta()` — pure function, pre/post snapshot comparison |
| | `graph_list` — returns graph names from worker |
| | `graph_export_all` — loops over all graphs, exports each |

---

## 6. Stored Results

| Property | Value |
|----------|-------|
| **Entry point** | `stata results [--session NAME] [--return r\|e\|s]` |
| **Source** | `cli.py` → `cmd_results()` → `RpcClient.call("results", ...)` → worker → `StataClient.get_results()` |
| **Core classes** | `StataClient` in `stata_client.py` |
| **Key sub-flows** | |
| | Runs `return list`/`ereturn list`/`sreturn list` in Stata |
| | Reads macro values via SFI `Macro.getGlobal()` |
| | Returns structured dict of stored results |

---

## 7. Log Operations

| Property | Value |
|----------|-------|
| **Entry point** | `stata log tail|search|errors|path [options]` |
| **Source** | `cli.py` → `cmd_log_tail/search/errors/path()` |
| **Core classes** | `LogRotator`, `ErrorExtractor`, `tail_file`, `search_in_log`, `paginated_read` in `log_manager.py` and `error_extractor.py` |
| **Key sub-flows** | |
| | `log tail` — reads last N lines of session log via `tail_file()` |
| | `log search` — regex search in log with pagination |
| | `log errors` — runs `ErrorExtractor.extract_from_tail()` or `extract_deep()` |
| | `log path` — returns current log directory |

---

## 8. Log Management (internal, implicit)

| Property | Value |
|----------|-------|
| **Source** | `log_manager.py` |
| **Key sub-flows** | |
| | `LogRotator` — per-session log rotation (by command count or file size) |
| | `truncate_for_agent()` — tail-preferring truncation for AI tokens |
| | `truncate_for_error()` — head-preferring truncation for error context |
| | `tail_file()` — efficient tail via seek-backwards |
| | `search_in_log()` — paginated regex search |
| | `paginated_read()` — chunked log reader with offset tracking |
| | `cleanup_old()` — TTL-based old log cleanup |

---

## 9. Error Extraction

| Property | Value |
|----------|-------|
| **Source** | `error_extractor.py` |
| **Core classes** | `ErrorExtractor` |
| **Key sub-flows** | |
| | `extract()` — full 2-phase parser (markers + fallback backward scan) |
| | `extract_from_tail()` — fast path, reads last 32 KB |
| | `extract_deep()` — full-file backward scan in 8 KB chunks |
| | Phase 1: `_marker_extract()` — forward scan for `[AGENT-ERROR]` markers |
| | Phase 2: `_fallback_extract()` — backward scan for `r(NNN);`, Mata errors, assertions, break, native messages |
| | Pattern matching: `R_CODE_RE`, `MATA_ERROR_RE`, `ASSERTION_RE`, `BREAK_ERROR_RE`, `NOT_FOUND_RE`, etc. |

---

## 10. Linter

| Property | Value |
|----------|-------|
| **Entry point** | `stata lint /path/to/file.do` |
| **Source** | `cli.py` → `cmd_lint()` → `lint_file()` / `lint_text()` + `format_lint_results()` in `linter.py` |
| **Key sub-flows** | |
| | `lint_file()` — reads file, delegates to `lint_text()` |
| | `lint_text()` — checks: unclosed braces, Mata block tracking, quote balance, version statement, shell commands, deprecated `set memory` |
| | `format_lint_results()` — readable summary with error/warning counts |

---

## 11. Doctor / Environment Check

| Property | Value |
|----------|-------|
| **Entry point** | `stata doctor [--json]` |
| **Source** | `cli.py` → `cmd_doctor()` |
| **Key sub-flows** | |
| | Python version check |
| | Cache directory verification |
| | Stata discovery via `find_stata_path()` |
| | pystata availability check |
| | Daemon health check via RPC |
| | Update state check |
| | JSON mode delegates to `scripts/install/verify.py` |

---

## 12. statest Test Framework

| Property | Value |
|----------|-------|
| **Entry point** | `stata test discover|run|run-all [options]` |
| **Source** | `cli.py` → `cmd_test_discover/run/run_all()` → `statest/runner.py` |
| **Core classes** | `StatestSessionPool`, `TestSuiteSummary`, `TestResult`, `AssertionFailure` in `statest/` |
| **Key sub-flows** | |
| | `discover_tests()` — glob for `test_*.do` files |
| | `run_test()` — runs setup → test → teardown in a pooled session |
| | `StatestSessionPool` — manages warm Stata sessions |
| | `_fetch_assertion_failure()` — reads statest_* scalars via RPC |
| | `run_tests()` — parallel or sequential execution with JUnit XML output |
| | `write_junit_xml()` — JUnit XML serialization |

---

## 13. Help System

| Property | Value |
|----------|-------|
| **Entry point** | `stata help <topic> [--format syntax|options|examples|summary|full] [--max-lines N]` |
| **Source** | `cli.py` → `cmd_help()` |
| **Key sub-flows** | |
| | Finds Stata binary via `find_stata_path()` |
| | Spawns `stata-se -q` subprocess with `help <topic>` |
| | Strips terminal control codes via regex |
| | Section extraction for syntax/options/examples/summary |
| | Line limiting |
| | Timeout handling at 30s |

---

## 14. Background Tasks

| Property | Value |
|----------|-------|
| **Entry point** | `stata task status|cancel|list [options]` |
| **Source** | `cli.py` → `cmd_task()` → daemon dispatch |
| **Key sub-flows** | |
| | `task status` — polls task by ID, optional wait+tail |
| | `task cancel` — cancels running task via break |
| | `task list` — lists all registered background tasks |
| | `_background_run()` — async execution in daemon |

---

## 15. Skills Installer

| Property | Value |
|----------|-------|
| **Entry point** | `stata install-skills [--dry-run] [--uninstall] [--agents ...]` |
| **Source** | `skills_installer.py` |
| **Key sub-flows** | |
| | `install_skills()` — detects agents, creates links/copies |
| | `uninstall_skills()` — removes skill links |
| | `_detect_agents()` — checks for Claude Code, Codex, Gemini, etc. |
| | `_create_link_or_copy()` — symlink with copy fallback |
| | `build_plugin_manifests()` — rewrites `{{VERSION}}` in JSON manifests |

---

## 16. Upgrade / Auto-Update

| Property | Value |
|----------|-------|
| **Entry point** | `stata upgrade [--force] [--quiet] [--to VERSION]` |
| **Source** | `skills_installer.py` — `check_and_upgrade()`, `_fetch_latest_version()` |
| **Key sub-flows** | |
| | `check_and_upgrade()` — two-phase check (version file sync + remote fetch) |
| | `_fetch_latest_version()` — fetches from Worker or PyPI |
| | `_parse_version()` — semver comparison |
| | Lock-based concurrent upgrade prevention |
| | `_discover_stata_agent_binary()` — finds binary for re-exec |

---

## 17. Stata Discovery

| Property | Value |
|----------|-------|
| **Entry point** | `stata discover` |
| **Source** | `discovery.py` |
| **Key sub-flows** | |
| | `find_stata_candidates()` — platform-specific path enumeration |
| | `verify_stata_install()` — runs binary in quiet mode, checks exit code |
| | `find_stata_path()` — cache-first, returns first working candidate |
| | `_parse_edition_from_binary()` — SE/MP/BE detection from filename |
| | Platform support: macOS (.app bundles), Windows (Program Files), Linux |

---

## 18. Session Management (internal)

| Property | Value |
|----------|-------|
| **Source** | `session.py` |
| **Core classes** | `SessionManager`, `WorkerHandle` |
| **Key sub-flows** | |
| | `get_or_create()` — reuse existing session or spawn worker |
| | `create()` — spawn `_worker_main()` process, wait for ready signal |
| | `stop()` — graceful shutdown with 5s timeout, then force-kill |
| | `stop_all()` — shutdown all sessions |
| | `send_break()` — SIGTERM + auto-restart |
| | `_worker_main()` in `worker.py` — pystata init + command loop |

---

## 19. Worker (internal)

| Property | Value |
|----------|-------|
| **Source** | `worker.py` |
| **Key sub-flows** | |
| | `_worker_main()` — initializes pystata via `stata_setup`, enters command loop |
| | `_dispatch()` — routes method calls to `StataClient` methods |
| | `_result_to_dict()` — serializes `RunResult` for pipe transport |

---

## 20. RPC Client

| Property | Value |
|----------|-------|
| **Source** | `rpc_client.py` |
| **Core classes** | `RpcClient`, `RpcError` |
| **Key sub-flows** | |
| | `call()` — NDJSON send/recv over Unix socket or TCP |
| | `_connect()` — socket path resolution with TCP fallback |
| | `is_alive()` — health check via RPC |
| | `is_daemon_running()` — static socket existence check |

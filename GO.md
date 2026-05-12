# Build Orchestration Prompt: `stata-agent`

---

## Mission

Build the `stata-agent` project in full, from scratch, as a completely independent Python package. This is a ground-up implementation guided by a detailed spec. You are the orchestrator: read the spec, divide the work into self-contained parallel streams where possible, spawn subagents to implement each feature, then integrate and verify the full system end-to-end.

---

## Where Everything Lives

**New project root (build here):**
`~/projects/stata-agent/`

It already has a git repo (`.git/`) and `features/` directory. It has **no source code yet**. Build the package here.

**Primary spec:**
`~/projects/stata-agent/plan.md`
Read this in full before spawning any subagents. It defines the architecture, CLI surface, daemon protocol, skills layout, and all success criteria.

**Feature review files** — one per feature; each contains architecture, pseudo-code, empirical Stata test results, risks, and a concrete implementation checklist. These are the primary brief for each subagent:

| Feature | Review file |
|---------|-------------|
| 01 — CLI + Daemon core | `features/01-cli-daemon/review.md` |
| 02 — Log size mitigation | `features/02-log-mitigation/review.md` |
| 03 — Text-first logs | `features/03-text-first-logs/review.md` |
| 04 — Graph handling | `features/04-graph-handling/review.md` |
| 05 — Structured error extraction | `features/05-error-extraction/review.md` |
| 06 — Session management | `features/06-session-management/review.md` |
| 07 — Background tasks | `features/07-background-tasks/review.md` |
| 08 — Data inspection & export | `features/08-data-inspection/review.md` |
| 09 — Mock/Stata-free test mode | `features/09-mock-test-mode/review.md` |
| 10 — Skill migration | `features/10-skill-migration/review.md` |
| 11 — Break/cancel mechanism | `features/11-break-cancel/review.md` |
| 12 — Help system | `features/12-help-system/review.md` |

**Reference implementation (context only — do not copy or import):**
`~/projects/mcp-stata/src/mcp_stata/`
Key files for algorithm and Stata-behaviour reference: `stata_client.py`, `discovery.py`,
`sessions.py`, `worker.py`, `linter.py`, `smcl/`, `graph_detector.py`.
The new code must have **zero imports, zero references, and zero dependencies** on this path.

**Existing test artifacts in the feature directories (use as test inputs):**

| Path | Purpose |
|------|---------|
| `features/02-log-mitigation/test_scripts/large_log_smcl_6mb.smcl` | 6 MB SMCL log for backward-scan benchmarks |
| `features/05-error-extraction/test_scripts/` | Reference `.do` + `.log` files covering all error classes |
| `features/06-session-management/test_artifacts/` | `.dta` files and do-files for session tests |
| `features/07-background-tasks/test_scripts/longjob.do`, `bigjob.do` | Background task stimulus |
| `features/09-mock-test-mode/responses/` | Canned Stata output (display_1plus1.txt, sysuse_auto.txt, reg_price_mpg.txt, …) |
| `features/12-help-system/help_regress_clean_output.txt` | Reference help text for help-system tests |

---

## What to Build

**Package identity:**
- Package name: `stata-agent`
- Python package: `stata_agent`
- Entry point: `stata = "stata_agent.cli:main"`
- Minimum Python: 3.11
- `pyproject.toml` with `[project.scripts]`, `[project.optional-dependencies]` (at minimum a `mock` extra for CI)
- No FastMCP, no `mcp` library, no references to `mcp_stata`

**Target directory layout:**

```
stata-agent/
├── src/stata_agent/
│   ├── __init__.py
│   ├── __main__.py          # delegates to cli.main()
│   ├── cli.py               # argparse entry point, all subcommands
│   ├── daemon.py            # asyncio NDJSON Unix socket server
│   ├── rpc_client.py        # NDJSON client (sync)
│   ├── session.py           # StataSession: slim worker wrapper (~150 LOC)
│   ├── worker.py            # StataWorker process: pystata wrapper
│   ├── stata_client.py      # pystata operations: run, inspect, graph, results, log
│   ├── discovery.py         # Stata executable auto-discovery
│   ├── error_extractor.py   # Backward log scan + structured marker parsing
│   ├── log_manager.py       # Text log lifecycle, rotation, tail, search
│   ├── graph_handler.py     # Post-run delta detection via `graph dir, memory`
│   ├── mock_backend.py      # Stata-free mock daemon for CI
│   ├── linter.py            # do-file static analysis
│   └── models.py            # Pydantic models for internal use only
├── skills/
│   ├── stata-toolkit/SKILL.md
│   ├── stata-run/SKILL.md
│   ├── stata-inspect/SKILL.md
│   ├── stata-graph/SKILL.md
│   ├── stata-results/SKILL.md
│   ├── stata-log/SKILL.md
│   ├── stata-help/SKILL.md
│   ├── stata-lint/SKILL.md
│   └── stata-setup/SKILL.md
├── tests/
│   ├── conftest.py
│   ├── unit/
│   ├── integration/
│   └── cli/                 # shell-level tests (.sh scripts)
├── pyproject.toml
└── README.md
```

---

## Critical Implementation Notes

These are findings from the feature reviews that will break a naive implementation if ignored.

1. **pystata is not on system Python.** `discovery.py` must locate Stata's bundled Python and call `stata_setup` to configure pystata. The worker process must run inside the Python that has pystata, or invoke `stata_setup` first. See `features/01-cli-daemon/review.md` §1.4.

2. **Stata batch mode (`-b`) writes a `.log` to CWD, not stdout.** The daemon MUST use pystata (stateful, in-process) as the primary execution path. Subprocess batch mode destroys state between calls. See `features/01-cli-daemon/review.md` §1.5.

3. **Text logs by default.** Open the session log with `log using <path>, replace text`. Do NOT use SMCL logs. Do NOT implement a SMCL-to-Markdown converter. See `features/03-text-first-logs/review.md`.

4. **`sfi.breakIn()` does not exist in StataNow 19.5.** Use `SIGTERM` to the worker process as the break signal. The CLI `stata break` sends a `break` RPC; the daemon translates this to SIGTERM on the worker. See `features/11-break-cancel/review.md`.

5. **Error extraction must handle Mata, assertions, and programs.** Wrap every command in `capture noisily { ... }` and emit `[MCP-ERROR] rc=N` and `[MCP-MSG] <message>` markers. Parse these markers from the text log. Do NOT rely on `{err}` SMCL tags. See `features/05-error-extraction/review.md`.

6. **Graph detection is a post-run delta**, not a streaming cache. Before execution: record `graph dir, memory` → `r(list)`. After: record again and diff. Return the delta as `graphs[]`. See `features/04-graph-handling/review.md`.

7. **Help system uses `stata-se -q` (quiet interactive), not `-b`.** Batch mode rejects help. Pipe `help <topic>\nexit\n` to stdin, capture stdout, strip terminal control codes. See `features/12-help-system/review.md`.

8. **Mock backend must speak the full daemon protocol.** When `stata daemon start --mock` is used, `mock_backend.py` starts a daemon that matches canned responses from `features/09-mock-test-mode/responses/` to incoming `run` requests by matching command text. See `features/09-mock-test-mode/review.md`.

9. **Log size mitigation is not optional.** Every `run` response must include `log_path` and never the full log text inline. On success, return at most 1000 tokens of tail. On failure, return structured error markers only (~60 tokens). The backward scan on a 6 MB log must complete in under 5 ms. See `features/02-log-mitigation/review.md`.

10. **Session management is minimal.** No history snapshots, no diffs, no profile code. One default session. Named sessions via `--session`. `session.py` target is ~150 LOC. See `features/06-session-management/review.md`.

---

## Test-Driven Development Rules

- Write tests **before** implementation for each module. Subagents must include a test file as their first deliverable.
- All unit tests must pass without a live Stata licence (`MCP_STATA_MOCK=1`).
- Tests requiring live Stata must be marked `@pytest.mark.requires_stata` and auto-skipped when Stata is unavailable.
- Use canned responses in `features/09-mock-test-mode/responses/` as test fixtures for the mock backend.
- Shell-level tests live in `tests/cli/` as `.sh` scripts and test the CLI end-to-end via subprocess.
- The backward-scan benchmark test must assert: scanning `features/02-log-mitigation/test_scripts/large_log_smcl_6mb.smcl` completes in < 5 ms and returns < 200 tokens of output.

---

## Git Discipline

**Both the orchestrator and every subagent must commit their work as they go.** Do not leave completed units of work uncommitted. Follow these rules precisely:

### Commit Format

Use [Conventional Commits](https://www.conventionalcommits.org/):

```
<type>(<scope>): <short imperative summary>

<body>
```

**Types:** `feat`, `fix`, `test`, `refactor`, `docs`, `chore`

**Scope:** use the feature number or module name, e.g. `feat(01-cli-daemon)`, `test(error-extractor)`, `chore(scaffold)`.

**Body:** Write a full description — not a bullet list of file names. Explain:
- What was built or changed and why
- Any non-obvious design decisions made (and what was rejected)
- Known limitations or follow-on work the next subagent should be aware of

**Example of a good commit:**

```
feat(01-cli-daemon): implement NDJSON daemon with Unix socket transport

The daemon is an asyncio server that listens on a Unix domain socket at
~/.cache/stata-agent/sessions/<name>.sock. It maintains a registry of
StataSession objects and routes incoming NDJSON requests to the appropriate
session worker via a multiprocessing Pipe (Option A from the review).

TCP fallback for Windows is wired but untested; the transport is selected
at startup based on sys.platform. Unix socket paths are unlinked on clean
shutdown via both atexit and SIGTERM handlers to avoid stale-socket errors
on restart.

The `health` method is intentionally lightweight (no Stata call) so the
CLI can use it as a liveness probe without side effects.
```

**Example of a bad commit (reject this pattern):**

```
add daemon and client files
```

### When to Commit

Commit at each of these natural checkpoints — do not batch them together:

1. After creating the project scaffold and `pyproject.toml` (before any source code)
2. After writing tests for a module (before writing the implementation)
3. After a module's implementation passes its tests
4. After writing skill files
5. After the full integration test suite passes

All working-tree changes must be committed before a subagent reports completion. The orchestrator must verify this before integrating a subagent's output.

### Commit Scope for Subagents

Each subagent should produce a sequence of commits like:

```
test(02-log-mitigation): add backward scan benchmark and unit tests
feat(02-log-mitigation): implement error_extractor and log_manager
```

Not one monolithic commit covering an entire feature.

---

## Suggested Parallelisation Strategy

After reading the plan and all 12 review files, proceed in this order:

**Wave 1 — fully independent, run in parallel:**

- **Subagent A:** Project scaffold — `pyproject.toml`, `src/stata_agent/__init__.py`, `tests/conftest.py`, `mock_backend.py`, canned-response fixtures from `features/09-mock-test-mode/responses/`. Verify `pip install -e .` succeeds. Commit: `chore(scaffold)`.

- **Subagent B:** `discovery.py` — Stata executable auto-discovery across macOS, Linux, and Windows path conventions. No Stata required to implement; unit-test with mocked filesystem. Commit: `test(discovery)` then `feat(discovery)`.

- **Subagent C:** `error_extractor.py` + `log_manager.py` — pure Python, no Stata dependency. Test against fixture files in `features/02-log-mitigation/test_scripts/` and `features/05-error-extraction/test_scripts/`. Must include the 6 MB backward-scan benchmark. Commit: `test(02-log-mitigation)` then `feat(02-log-mitigation)`.

**Wave 2 — depends on Wave 1 completing:**

- **Subagent D:** `daemon.py` + `rpc_client.py` + `session.py` (features 01, 06). Wire the mock backend so all daemon tests run without Stata. Commit sequence: `test(01-cli-daemon)` → `feat(01-cli-daemon)` → `test(06-session-management)` → `feat(06-session-management)`.

- **Subagent E:** `stata_client.py` + `graph_handler.py` (features 04, 08). Implement pystata operations: run, inspect (describe/summary/codebook/list/get), graph delta, results retrieval. Tests use the mock backend. Commit sequence: `test(stata-client)` → `feat(stata-client)` → `test(04-graph-handling)` → `feat(04-graph-handling)`.

- **Subagent F:** `linter.py` + help system subprocess wrapper (feature 12). Both are stateless. Tests use the reference output at `features/12-help-system/help_regress_clean_output.txt`. Commit: `test(12-help-system)` then `feat(12-help-system)`.

**Wave 3 — depends on Wave 2:**

- **Subagent G:** `cli.py` + `__main__.py` — all subcommands fully wired: `daemon start/stop/status`, `run`, `inspect describe/summary/codebook/list/get`, `graph list/export/export-all`, `results`, `log tail/search/errors/path`, `help`, `lint`, `doctor`, `discover`, `task status`. Commit: `test(cli)` then `feat(cli)`.

- **Subagent H:** Background task system inside the daemon + `stata task status` CLI subcommand (feature 07). Commit: `test(07-background-tasks)` then `feat(07-background-tasks)`.

**Wave 4 — finalisation:**

- **Subagent I:** All 9 skill files in `skills/`. Write `SKILL.md` for: `stata-toolkit`, `stata-run`, `stata-inspect`, `stata-graph`, `stata-results`, `stata-log`, `stata-help`, `stata-lint`, `stata-setup`. Each must be under 400 tokens, use only `stata <subcommand>` CLI syntax, and include the log-safety instructions described in plan.md §3.4. Verify token counts with `wc -w` as a proxy. Commit: `docs(10-skill-migration): add all skill files`.

- **Subagent J:** Full integration test against the mock daemon — start mock daemon, run `sysuse auto` then `reg price mpg` (verifying state persistence), export a graph, verify `log_path` is present, verify output is truncated to ≤1000 tokens, verify error format on a failing command. Commit: `test(integration): add end-to-end integration suite`.

The orchestrator integrates each wave's output, runs `python -m pytest tests/ -m "not requires_stata"` after each wave, fixes any cross-module issues, commits fixes, and only then launches the next wave.

---

## Success Criteria

The build is complete when all of the following are true:

1. `stata run --echo "display 1+1"` (with mock daemon) returns `rc=0` and `stdout` containing `2`.
2. `stata run "reg price mpg"` after `stata run "sysuse auto"` uses the same mock session and succeeds (state persistence).
3. A backward scan of `features/02-log-mitigation/test_scripts/large_log_smcl_6mb.smcl` completes in < 5 ms and returns < 200 tokens.
4. `python -m pytest tests/ -m "not requires_stata"` exits 0.
5. All 9 skill files exist, each is < 400 tokens, and none contains any MCP tool reference.
6. `pip install -e .` succeeds in the `stata-agent/` directory.
7. `git log --oneline` shows a clean sequence of conventional commits with no "WIP" or "add files" messages.

---

## What NOT to Do

- Do not import from `mcp_stata`, `fastmcp`, `mcp`, or any path under `mcp-stata/src/`.
- Do not create SMCL-parsing code. Text logs eliminate this.
- Do not implement history snapshots, session diffs, or profile code.
- Do not create a `StreamingGraphCache` or `GraphCreationDetector`. The 20-line delta approach replaces them.
- Do not implement `sfi.breakIn()` — it does not exist. Use SIGTERM.
- Do not write SKILL.md files that reference MCP tool names (`stata_run`, `stata_inspect_data`, etc.).
- Do not leave uncommitted work at the end of a subagent run.
- Do not write one-line commit messages for substantive changes.

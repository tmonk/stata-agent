# Build Prompt: Migrate `statest` to `stata-agent`

**Scope:** Extract the `statest` Stata testing framework from `mcp-stata` and rebuild it as a first-class subsystem of `stata-agent`, replacing its MCP-session coupling with the new NDJSON daemon protocol and adding `stata test` CLI subcommands.

This prompt is a companion to `GO.md`. It assumes the core `stata-agent` package (daemon, CLI, session, rpc_client) is already built or being built in parallel. `statest` depends on the daemon being runnable — do not start implementation until `stata run` works end-to-end (even in mock mode).

---

## Where Everything Lives

**Working directory:**
`~/projects/stata-agent/`

**Source to migrate from (read-only reference — do not import):**
`~/projects/mcp-stata/src/mcp_stata/statest/`

Files to read before starting:

| File | What it contains |
|------|-----------------|
| `statest.mata` | The entire Mata assertion library + Stata program wrappers. Pure Stata/Mata — zero Python coupling. |
| `runner.py` | Async Python test runner. Coupled to `mcp_stata.sessions.SessionManager` via `session.call(...)`. This is the file that needs the most work. |
| `models.py` | `AssertionFailure`, `TestResult`, `TestSuiteSummary` Pydantic models. No mcp_stata imports — migrate verbatim. |
| `junit.py` | JUnit XML serialisation. No mcp_stata imports — migrate verbatim. |
| `__init__.py` | Public API re-exports. Migrate verbatim, updating import paths. |
| `tests/` | Full test suite: `test_mata/`, `test_runner/`, `test_fixtures/`, `test_sessions/`, `expected_failures/`, `statest_conftest.do`. Migrate all of these to `tests/statest/` in the new project. |

**README for full feature description:**
`~/projects/mcp-stata/src/mcp_stata/statest/README.md`

---

## What `statest` Is

`statest` is a pytest-equivalent for Stata. It discovers `test_*.do` files, runs each in an isolated Stata session, collects structured failure metadata via Mata scalars, and can export JUnit XML for CI.

**Assertions available in test `.do` files:**
```stata
st_assert_scalar r(mean), expected(6165.257) tol(0.001)
st_assert_macro  e(cmd),   expected("regress")
st_assert_rc     111,      cmd("use nonexistent.dta")
st_assert_matrix r(table), expected(M) tol(0.001)
```

These are defined entirely in `statest.mata` — they have no Python dependency and require no changes.

**Fixture conventions (unchanged):**

| File | Scope | When it runs |
|------|-------|-------------|
| `statest_conftest.do` | Suite | Once before the suite, in a dedicated session |
| `statest_setup.do` | Per-test | In the test session, before the test file |
| `statest_teardown.do` | Per-test | In the test session, after the test file (always) |

---

## The Coupling Problem

The existing `runner.py` is wired to `mcp_stata.sessions.SessionManager` through these call sites:

| Call in `runner.py` | What it does | New equivalent |
|---------------------|-------------|----------------|
| `session_manager.get_or_create_session(sid, startup_do_file=statest.mata)` | Spawns a Stata session and loads the Mata library | `stata daemon start --session <sid>` then `stata run --session <sid> --file statest.mata` |
| `session.call("run_command", {"code": "statest_reset", ...})` | Resets assertion counter | `RpcClient(session=sid).call("run", {"code": "statest_reset"})` |
| `session.call("run_command_structured", {"code": setup_code, ...})` | Runs setup and captures `rc` | `RpcClient(session=sid).call("run", {"code": setup_code})` |
| `session.call("run_do_file", {"path": path, ...})` | Runs the test `.do` file | `RpcClient(session=sid).call("run_file", {"path": path})` |
| `session.call("get_stored_results", {"force_fresh": True})` | Reads `r()` scalars to get failure metadata | `RpcClient(session=sid).call("results", {"class": "r"})` |
| `session_manager.stop_session(sid)` | Tears down the Stata session | `RpcClient(session=sid).call("stop", {})` |

The `StatestSessionPool` uses `asyncio.Queue` to reuse warm sessions. In the new architecture the daemon already owns session lifetime, so the pool becomes a lightweight wrapper over named daemon sessions. The asyncio machinery stays; only the `acquire`/`release` bodies change.

---

## Target Layout

```
stata-agent/
├── src/stata_agent/
│   └── statest/
│       ├── __init__.py          # re-exports: run_tests, run_test, discover_tests, write_junit_xml
│       ├── runner.py            # rewritten: RpcClient-based, no session_manager import
│       ├── models.py            # verbatim copy (update package name in any comments only)
│       ├── junit.py             # verbatim copy
│       └── statest.mata         # verbatim copy — pure Stata/Mata, no changes needed
├── skills/
│   └── stata-test/
│       └── SKILL.md             # new skill (see below)
└── tests/
    └── statest/                 # migrated test suite
        ├── statest_conftest.do
        ├── expected_failures/   # fail_*.do files
        ├── test_fixtures/       # setup/teardown .do files
        ├── test_mata/           # assertion unit tests
        ├── test_runner/         # runner self-tests
        └── test_sessions/       # session isolation tests
```

---

## New CLI Surface

Add a `test` subcommand group to `cli.py`. The MCP tools (`stata_run_tests`, `stata_run_test`, `stata_discover_tests`, `stata_get_test_results`) become:

```bash
# Discover test files without running them
stata test discover <path>

# Run a single test file
stata test run <file.do> [--session NAME] [--junit <out.xml>]

# Run all tests under a directory
stata test run-all <path> [--parallel] [--workers N] [--junit <out.xml>] [--session NAME]
```

**Output format (success):**
```
[statest] Ran 7 tests in 4.3s
[statest] ✓ 7 passed
```

**Output format (failure):**
```
[statest] Ran 7 tests in 4.1s
[statest] ✗ 1 failed, 6 passed

FAILED tests/test_mata/test_assert_scalar_pass.do
  assertion 2: st_assert_scalar
  expected: 5000.0
  actual:   6165.257
  rc: 9
  log: ~/.cache/stata-agent/logs/statest-a3f1_20260512_001.log (last 20 lines follow)
  ...
```

The `--json` global flag (from the main CLI) wraps the `TestSuiteSummary` as JSON for structured consumers.

---

## Implementation Details

### 1. `runner.py` — Rewrite

The new runner must:

- Accept a `daemon_session: str = "default"` parameter instead of `session_manager: Any`.
- Use `RpcClient` (from `stata_agent.rpc_client`) for all Stata communication.
- Start named daemon sessions for isolated test runs via `stata daemon start --session <sid>` (or by calling the daemon's `start_session` RPC method directly if one is added).
- Load `statest.mata` by sending its contents as a `run_file` RPC to each new session — do this once per session acquisition, not once per test.
- Keep `StatestSessionPool` but rewrite `acquire` to start a new named daemon session and load `statest.mata`, and `release` to send `run` with `"statest_reset\nclear all"`.
- Keep `_fetch_assertion_failure` but replace `session.call("get_stored_results", ...)` with `RpcClient.call("results", {"class": "r"})`.
- Keep the `parallel` path using `asyncio.gather` — no change needed here.
- Keep `run_test`'s setup/teardown logic exactly as-is; only the transport calls change.

**One important difference from the current implementation:** The current runner calls `run_command_structured` (a special MCP method that returns structured data). In the new daemon, all `run` responses return `{"ok": bool, "rc": int, "stdout": str, "log_path": str, ...}`. There is no separate "structured" variant — `rc` is always present in the response. Adjust accordingly.

**Session naming convention for isolated test sessions:**
`statest-<uuid8>` — e.g. `statest-a3f1c920`. This prevents collisions with user sessions.

**`statest.mata` loading path:** The file lives at `src/stata_agent/statest/statest.mata`. The runner must resolve this path relative to its own `__file__` using `Path(__file__).parent / "statest.mata"`, exactly as the current implementation does.

### 2. `models.py` and `junit.py` — Verbatim

Copy these files exactly. Update only:
- Remove any `from mcp_stata` imports (there are none in these files currently).
- Change `mcp_stata.statest` references in docstrings/comments if any exist.

### 3. `statest.mata` — Verbatim

Copy without any changes. It is pure Stata/Mata with no Python coupling whatsoever.

### 4. `SKILL.md` — New Skill

Create `skills/stata-test/SKILL.md`. It must be under 400 tokens. Example structure:

```markdown
---
name: stata-test
description: Discover and run statest test suites for Stata do-files.
---

## Stata Test

Run the statest testing framework against Stata do-files.

### Discover tests

```bash
stata test discover tests/
```

### Run a single test

```bash
stata test run tests/test_means.do
```

### Run a full suite

```bash
stata test run-all tests/ --junit reports/results.xml
```

### On failure

The output shows which assertion failed, the expected vs actual values, and the
last 20 lines of that test's log. To read the full log:

```bash
stata log tail --session <statest-session-id> --lines 100
```

### Writing tests

Each test file is a `.do` file named `test_*.do`. Assertions:

```stata
sysuse auto, clear
summarize price
st_assert_scalar r(mean), expected(6165.257) tol(0.001)
st_assert_macro  e(cmd),   expected("regress")
st_assert_rc     111,      cmd("use nonexistent.dta")
```

Fixtures: place `statest_setup.do` and `statest_teardown.do` alongside the test files.
Suite-level setup: `statest_conftest.do` in the suite root directory.
```

---

## Test-Driven Development

Write tests in this order:

**Step 1 — pure Python unit tests (no Stata, no daemon):**
- `tests/unit/test_statest_models.py` — construct `TestResult` and `TestSuiteSummary`, serialise to JSON, verify fields.
- `tests/unit/test_statest_junit.py` — call `write_junit_xml` on a fixture summary, parse the output XML, assert structure.
- `tests/unit/test_statest_discover.py` — call `discover_tests` on a temp directory with mock `.do` files, verify sorted output.

**Step 2 — mock daemon integration tests:**
- `tests/integration/test_statest_runner_mock.py` — start the mock daemon, run `tests/statest/test_mata/test_assert_scalar_pass.do` through the runner, assert `success=True`, `rc=0`, `log_path` is set.
- Test a known failure: run `tests/statest/expected_failures/fail_assert_scalar_fail.do`, assert `success=False`, `failure.expected == "5000"`, `failure.actual` is close to `"6165.257"`, `assertion_index == 1`.

  Note: The mock backend cannot execute real Stata assertions. For failure tests, add a canned response to the mock backend that simulates a `rc=9` return with the `statest_assertion_index`, `statest_expected`, and `statest_actual` scalars set in `r()`. See `features/09-mock-test-mode/responses/` for the pattern.

- Test teardown: verify teardown runs even when the test fails.

**Step 3 — CLI tests:**
- `tests/cli/test_statest_cli.sh` — shell test that calls `stata test discover tests/statest/`, asserts it lists the expected `.do` files; calls `stata test run-all tests/statest/test_mata/ --json`, asserts the JSON output contains `passed > 0` and `failed == 0`.

**Step 4 — live Stata tests (mark `requires_stata`):**
- Run the full migrated test suite in `tests/statest/` against a real Stata session. Every `test_*.do` in `test_mata/`, `test_runner/`, `test_fixtures/`, `test_sessions/` should pass. Every file in `expected_failures/` should produce `success=False`.

---

## Git Discipline

Follow the same rules as `GO.md`. Commit at each checkpoint using Conventional Commits with a full body.

Suggested commit sequence:

```
chore(statest): scaffold statest subpackage with verbatim models, junit, and statest.mata

feat(statest): implement RpcClient-based runner replacing session_manager coupling

test(statest): add unit tests for models, junit serialisation, and test discovery

test(statest): add mock-daemon integration tests for pass and failure paths

feat(statest): add stata test discover/run/run-all CLI subcommands

docs(statest): add stata-test skill file

test(statest): migrate .do test suite to tests/statest/

test(statest): add shell-level CLI test for statest subcommands
```

Each commit body must explain what changed and why — particularly any decisions made about the session pool redesign or the mock backend extension for failure simulation.

---

## What NOT to Do

- Do not import from `mcp_stata` or any path under `mcp-stata/src/`.
- Do not rewrite `statest.mata` — it is pure Stata/Mata and works as-is.
- Do not add a separate HTTP server or MCP tool registration — the CLI subcommands are the only interface.
- Do not change the assertion API (`st_assert_scalar`, etc.) — test files across user projects depend on this interface being stable.
- Do not make `StatestSessionPool` synchronous — keep it asyncio-based so `--parallel` works without blocking.
- Do not skip teardown on failure — the current logic that always runs teardown is correct and must be preserved.

---

## Success Criteria

1. `stata test discover tests/statest/` lists all `test_*.do` files in the migrated suite.
2. `stata test run-all tests/statest/test_mata/` (mock mode) exits 0 with all tests passing.
3. Running `fail_assert_scalar_fail.do` through the runner returns `success=False`, `failure.assertion_index == 1`, `failure.expected == "5000"`.
4. `write_junit_xml` produces valid XML that parses cleanly with `xml.etree.ElementTree`.
5. `python -m pytest tests/unit/test_statest_*.py tests/integration/test_statest_runner_mock.py` exits 0 with `MCP_STATA_MOCK=1`.
6. The `stata-test` skill file exists and is under 400 tokens (`wc -w` proxy check).
7. `git log --oneline` shows no uncommitted work and no one-line commit messages for substantive changes.

# Review: Mock / Stata-Free Test Mode

**Date:** 2026-05-12
**Source plan section:** 11.10 (Add a Mock/Stata-Free Test Mode)
**Context:** Migration from MCP server (`server.py`) to CLI-native architecture. The mock backend enables CI tests and development without a Stata license.

---

## 1. Current Mock Infrastructure (Existing Code)

The repo already has a `tests/conftest.py` with Python mock scaffolding and `tests/server/test_mock_protocol.py`. Here is what exists today:

### conftest.py (already functional)
- `_setup_stata_mocks_if_needed()` — conditionally mocks `sfi`, `pystata`, `stata_setup` modules using `unittest.mock.MagicMock` when Stata is absent or `MCP_STATA_MOCK=1`.
- `stata_client` fixture — builds a `StataClient` in mock mode, creating a `/tmp/mock_session.smcl` log file and a dummy `/tmp/regress.sthlp` help file.
- `detect_stata_version()` — wraps `discovery.find_stata_path()` to detect Stata without loading the C library (avoids uncatchable `exit()`).
- `pytest_collection_modifyitems` — auto-marks `requires_stata` tests and skips them in mock mode.

### test_mock_protocol.py (3 basic tests)
- `test_mock_command_execution` — monkeypatches log readers to return `{txt}Mock Stata output\n`; verifies success.
- `test_mock_error_handling` — monkeypatches `sfi.Scalar.getValue` to return rc=111; verifies error extraction.
- `test_mock_data_retrieval` — calls `get_data(count=5)` with try/except to exercise the code path.

**Limitation:** These tests mock at the *Python method level*, not at the *daemon protocol level*. They test the old MCP server code path, not the new CLI daemon.

---

## 2. Real Stata Output Reference (Captured)

All outputs were captured from `/usr/local/bin/stata-se` (StataNow 19.5 SE, batch mode). See `responses/` subdirectory for full files.

### Key Format Observations

| Command | Output Pattern | SMCL Tags? | Key Tokens |
|---------|---------------|------------|------------|
| `sysuse auto, clear` | `(1978 automobile data)` | No | Parenthesized confirmation |
| `reg price mpg` | Full ANOVA table + coefficient table | No (text log) | `Source`, `Model/Residual/Total`, `_cons`, `mpg` |
| `display 1+1` | `2` | No | Single numeric result |
| `error 111` | `invalid syntax` + `r(111);` | No | `invalid syntax`, `r(CODE);` |
| `capture error 111` | (silent) + `_rc = 111` | No | `_rc` access required |
| `describe` | Table of 12 variables + metadata | No | `Contains data from`, `Observations`, `Variable name/type/format/label` |
| `summarize price mpg` | 2-row table with Obs/Mean/SD/Min/Max | No | `Obs`, `Mean`, `Std. dev.`, `Min`, `Max` |
| `tabulate rep78` | Frequency table with Cum.% | No | `Freq.`, `Percent`, `Cum.` |
| `assert 1==0` | `r(9);` (assertion failed) | No | rc=9 is unique to assert |
| Uncaught error | `r(111);` + do-file terminates | No | Does NOT execute subsequent lines |
| Success do-file | `end of do-file` | No | Clean exit |

### Critical Finding: Exit Code Behavior

**`stata-se -b do file.do` always returns exit code 0**, even on fatal errors like `error 111` (uncatchable). The error is communicated only through the log content (`r(111);`). This means the mock daemon must detect errors by parsing output, not by checking process exit codes.

Tested scenarios:
- Success do-file → exit 0
- Uncaught `error 111` → exit 0 (log contains `r(111);`)
- Uncaught `assert 1==0` → exit 0 (log contains `r(9);`)

Contrast: `stata-se -e 'command'` (inline) also returns exit 0 always in batch mode.

### Batch Log Format (Text Mode)

Every log begins with a banner:
```
  ___  ____  ____  ____  ____ ®
 /__    /   ____/   /   ____/      StataNow 19.5
... (license/version info)
```
Then each command is echoed with a `. ` prompt prefix:
```
. command_here
output_here
```
The command echo is essential for the mock to distinguish user commands from output.

---

## 3. Commands Used in Existing Test Files

From the 30+ `.do` files in `features/` and `tests/`, the most frequently used commands are:

| Command | Frequency | Used In |
|---------|-----------|---------|
| `sysuse auto, clear` | ~15 | Almost every test do-file |
| `display "..."` | ~20 | Every test |
| `regress price mpg [weight]` | ~10 | Regression tests, graph tests |
| `describe` | ~8 | Log mitigation tests |
| `summarize [varlist]` | ~6 | Session tests, log tests |
| `error <code>` | ~8 | Error extraction tests |
| `capture <command>` | ~12 | Error handling tests |
| `assert <condition>` | ~4 | Error extraction tests |
| `tabulate <var>` | ~2 | Log tests |
| `set more off` | ~6 | Batch mode setup |
| `log using ..., replace` | ~6 | Log format tests |
| `graph export ...` | ~3 | Graph tests |
| `forvalues i = 1/N` | ~4 | Large log generation |
| `program define` | ~4 | Error extraction tests |
| `mata:` | ~4 | Mata error tests |
| `predict` | ~2 | Regression diagnostics |
| `count if` | ~2 | Session tests |
| `save`, `use` | ~4 | Session state tests |
| `gen` (generate) | ~1 | Break test |

---

## 4. Architecture for the Mock Test Backend

### 4.1 Design Principles

1. **Protocol-compatible** — the mock daemon speaks the same line-delimited JSON protocol as the real daemon (section 2.1 of plan).
2. **Stateless by default** — each command is independent unless stateful commands (`use`, `gen`, `replace`) are explicitly tracked.
3. **Minimal state machine** — track only: current dataset (name, vars, obs), last estimation results (e-class), last return code (_rc), and graph list.
4. **Deterministic** — same command → same output, always. No randomness.
5. **Self-documenting** — the response database is a readable JSON file, not code.

### 4.2 Component Diagram

```
┌──────────────────────────────────────────────────┐
│                   CLI Frontend                     │
│  stata daemon start --mock                         │
└──────────────────┬───────────────────────────────┘
                   │
┌──────────────────▼───────────────────────────────┐
│              Mock Daemon (mock_daemon.py)          │
│                                                    │
│  ┌─────────────┐  ┌──────────────┐  ┌──────────┐  │
│  │ Command     │  │ Response     │  │ Syntax   │  │
│  │ Router      │──┤ Database     │──┤ Validator│  │
│  └──────┬──────┘  └──────────────┘  └──────────┘  │
│         │                                           │
│  ┌──────▼──────┐                                   │
│  │ State       │  (optional: tracks use/gen/      │
│  │ Machine     │   reg/predict for stateful cmds) │
│  └─────────────┘                                   │
└──────────────────────────────────────────────────┘
```

### 4.3 Protocol Interface

Same as real daemon: line-delimited JSON over Unix domain socket (or TCP on Windows).

**Request:**
```json
{"id": 1, "method": "run", "params": {"code": "sysuse auto, clear"}}
```

**Response (success):**
```json
{"id": 1, "result": {"success": true, "rc": 0, "output": "(1978 automobile data)"}}
```

**Response (error):**
```json
{"id": 1, "result": {"success": false, "rc": 111, "output": "invalid syntax\\nr(111);"}}
```

**Response (table output):**
```json
{"id": 1, "result": {"success": true, "rc": 0, "output": "      Source |       SS ...", "tables": [...], "ereturn": {...}}}
```

---

## 5. Pseudo-Code

### 5.1 Mock Daemon

```
module mock_daemon

import: json, socket, argparse, response_db, syntax_validator, state_machine

function main():
    args = parse_args()  # --port, --socket-path
    db = response_db.load("responses/canned.json")
    validator = syntax_validator.SyntaxValidator()
    state = state_machine.StateMachine()

    server = start_unix_socket(args.socket_path) or start_tcp(args.port)
    listen for connections

    for each connection:
        while connected:
            request = read_line_delimited_json(conn)
            response = handle_request(request, db, validator, state)
            send_line_delimited_json(conn, response)

function handle_request(request, db, validator, state):
    id = request.id
    method = request.method  # "run", "help", "describe", "graphs", etc.

    if method == "run":
        return handle_run(request.params.code, db, validator, state)
    elif method == "help":
        return handle_help(request.params.topic, db)
    elif method == "graphs":
        return handle_list_graphs(state)
    elif method == "stop":
        return {"id": id, "result": {"success": true}}
    else:
        return {"id": id, "error": {"code": -1, "message": f"Unknown method: {method}"}}
```

### 5.2 Command Router

```
module command_router

# Routing strategy:
# 1. Normalize the command string (strip whitespace, collapse multiple spaces)
# 2. Match against known command patterns (ordered by specificity)
# 3. If matched, return canned response
# 4. If not matched, fall back to syntax validator + generic response

PRECEDENCE_ORDER = [
    ("exact",      ["sysuse auto, clear", "set more off"]),
    ("prefix",     ["display ", "capture ", "cap ", "quietly "]),
    ("regex",      [
        r"^reg(ress)?\s+\w+",          # regression
        r"^summarize\s",                # summarize
        r"^tab(ulate)?\s",              # tabulate
        r"^des(cribe)?$",               # describe alone
        r"^assert\s",                   # assertion
        r"^error\s+\d+",                # error command
        r"^log using",                  # log management
        r"^graph\s",                    # graph commands
        r"^predict\s",                  # prediction
        r"^gen(erate)?\s",              # variable generation
        r"^drop\s",                     # drop/keep
        r"^keep\s",
    ]),
    ("fallback",   [".*"]),             # unrecognized → generic "syntax is valid" response
]

function route(command, db, state):
    command = command.strip()
    normalized = normalize_spaces(command)

    # 1. Check exact match
    if exact_match(normalized, db.exact_responses):
        return db.exact_responses[normalized]

    # 2. Check prefix match (e.g., "display X" → expression evaluator)
    for prefix in PREFIX_MATCHES:
        if normalized.startswith(prefix):
            return handle_prefix_command(normalized, prefix, db, state)

    # 3. Check regex match
    for pattern in REGEX_MATCHES:
        if re.match(pattern, normalized):
            return handle_regex_command(normalized, pattern, db, state)

    # 4. Fallback: validate syntax, return generic success
    return handle_fallback(normalized, db)
```

### 5.3 Response Database

```
module response_db

# Format: JSON file mapping normalized command → response object
# Stored at: responses/canned.json (extensible, data-driven)

TYPE DEFINITIONS:

CommandPattern = {
    pattern: str,           # exact text or regex
    type: "exact" | "regex",
    response: Response
}

Response = {
    success: bool,
    rc: int,
    output: str,            # the complete output text (as it would appear in log)
    tables: list[Table]?,   # optional parsed table data for structured access
    ereturn: dict?,         # optional e-class results (for post-estimation)
    rclass: dict?,          # optional r-class results
    state_updates: {        # state machine changes
        dataset: str?,
        vars: list[str]?,
        last_rc: int?,
        estimation: dict?
    }
}

Table = {
    title: str,
    headers: list[str],
    rows: list[list[str]],
    footer: str?
}

Example entry for "sysuse auto, clear":
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
                "path": "/Applications/StataNow/ado/base/a/auto.dta",
                "observations": 74,
                "variables": 12,
                "vars": ["make", "price", "mpg", "rep78", "headroom", "trunk",
                         "weight", "length", "turn", "displacement", "gear_ratio", "foreign"],
                "labels": {
                    "make": "Make and model",
                    "price": "Price",
                    ...
                }
            }
        }
    }
}
```

### 5.4 Syntax Validator

```
module syntax_validator

# A lightweight Stata syntax validator (regex-based, not a full parser).
# Purpose: validate commands not in the response database.
# Scope: reject obvious syntax errors, accept everything else.

VALIDATION RULES:

1. Basic structure
   - Command is not empty
   - No unmatched quotes (simple heuristic)
   - No unmatched parentheses/brackets

2. Command recognition
   - Known command name at start (from a dictionary of ~200 Stata commands)
   - Or expression (starts with `display`, `local`, `global`, `return scalar`)
   - Or assignment (`gen newvar = ...`, `replace ...`)
   - Or Mata block (`mata: ...` / `mata ... end`)

3. Variable references
   - If after `use`, `sysuse`, `webuse`: dataset name must be alphanumeric
   - If after `regress`, `summarize`, etc: variable names must be alphanumeric or `_`-prefixed
   - Wildcards (`*`, `?`) are valid

4. Common error patterns
   - `regress` with too few arguments (< 2 varnames) → error
   - `error` with non-numeric argument → error
   - `use` with missing filename → error
   - `display` with missing expression → error (but `display ""` is OK)
   - `set` with unknown option → warn
   - `assert` with missing condition → error

5. Rejection strategy
   - If validation fails: return {"success": false, "rc": 198, "output": "invalid syntax\\nr(198);"}
   - If validation passes but unknown: return {"success": true, "rc": 0, "output": ""}

PSEUDO-CODE:

function validate(command):
    """Returns (is_valid, rc, message)"""
    if is_empty(command):
        return (False, 198, "empty command")

    if has_unmatched_quotes(command):
        return (False, 198, "unmatched quotes")

    cmd_name = extract_command_name(command)

    if is_known_command(cmd_name):
        return validate_known_command(cmd_name, rest_of_command)
    elif is_assignment(command):
        return validate_assignment(command)
    elif is_mata_block(command):
        return validate_mata_block(command)
    else:
        # Unknown command → warn but accept (Stata allows user programs)
        return (True, 0, "")

function validate_known_command(cmd_name, args):
    match cmd_name:
        case "use" | "sysuse" | "webuse":
            if args is empty: return (False, 198, "no dataset specified")
            return (True, 0, "")
        case "regress" | "reg":
            parts = split_on_comma(args)
            varlist = parts[0].split()
            if len(varlist) < 2: return (False, 198, "too few variables specified")
            return (True, 0, "")
        case "error":
            arg = args.strip()
            if not arg.isdigit(): return (False, 198, "invalid error code")
            return (True, 0, "")
        case "assert":
            if args.strip() == "": return (False, 198, "assert requires condition")
            return (True, 0, "")
        case "display":
            if args.strip() in ["", `"`]: return (True, 0, "")  # empty display OK
            return (True, 0, "")
        case _:
            return (True, 0, "")
```

### 5.5 State Machine (Optional)

```
module state_machine

# Tracks the minimum state needed for realistic Stata session simulation.

class StateMachine:
    fields:
        dataset: DatasetInfo | None
        last_rc: int  (default 0)
        estimation: EstimationInfo | None
        graphs: list[GraphInfo]
        macros_global: dict[str, str]
        macros_local: dict[str, str]  # per-session

    def update_from_response(self, response):
        """Apply state_updates from a Response object."""
        if response.state_updates:
            if "dataset" in response.state_updates:
                self.dataset = response.state_updates.dataset
            if "last_rc" in response.state_updates:
                self.last_rc = response.state_updates.last_rc
            if "estimation" in response.state_updates:
                self.estimation = response.state_updates.estimation

    def resolve_variable(self, name):
        """Given a variable name, return its type and position (for describe/summarize)."""
        if self.dataset and name in self.dataset.vars:
            idx = self.dataset.vars.index(name)
            return self.dataset.variable_info[idx]
        return None
```

---

## 6. Implementation Plan

### Phase 1: Response Database (data-driven, no Python code)

Create `responses/canned.json` with entries for all commands from section 3.
Format as described in 5.3. Prioritize:
- `sysuse auto, clear` (most common)
- `display *` (generic expression evaluator)
- `regress price mpg` (most common estimation)
- `describe` (most common data inspection)
- `summarize`, `tabulate`, `assert`, `error`

### Phase 2: Syntax Validator

Implement `mock/validator.py` with 80% coverage of common command patterns.
Target: accept all valid Stata, reject only clear syntax errors.

### Phase 3: Mock Daemon

Implement `stata-daemon` with `--mock` flag that:
- Loads `responses/canned.json`
- Starts the same Unix socket (or TCP) as the real daemon
- Routes commands through: command_router → response_db → syntax_validator → state_machine
- Returns JSON responses matching the real daemon format

### Phase 4: Shell-Level Integration Tests

Write `tests/cli/test_mock_mode.sh` that:
1. Starts `stata daemon start --mock`
2. Sends commands via the CLI or direct socket write
3. Verifies responses match the real-output equivalents in `responses/`
4. Stops the daemon
5. Runs entirely without a Stata license

### Phase 5: CI Pipeline

- GitHub Actions workflow: `ci-mock.yml`
- Matrix: `ubuntu-latest`, `macos-latest`, `windows-latest`
- Steps: checkout → Python setup → `pip install -e .` → `stata daemon start --mock` → run tests
- Mark existing Stata-requiring tests with `@pytest.mark.requires_stata` (already done in conftest.py)
- Skip them in mock mode; run only mock-compatible tests

---

## 7. Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Canned responses drift from real Stata output | Medium | Medium | Version-tag responses to Stata version; regenerate on upgrade |
| Syntax validator is too permissive (accepts invalid Stata) | High | Low | Validator is a best-effort gate; CI will still catch issues via real Stata runs |
| State machine missing critical state transitions | Medium | Medium | Start with no state machine; add state only when tests require it |
| Commands in the wild don't match canned patterns | High | Low | Fallback to generic "valid syntax" response; mock is for CI, not production |
| Windows path/socket differences | Low | High | Plan Unix sockets for macOS/Linux, TCP fallback for Windows |
| Mock mode gives false confidence | Medium | Medium | Always run a subset of tests against real Stata before release |

---

## 8. Integration with Existing Mock Infrastructure

The existing `conftest.py` mocks at the `sfi/pystata` Python level. The new mock daemon mocks at the **protocol** level. These serve different purposes:

- **Python-level mocks** (existing) — for testing Python code that wraps `sfi` calls (e.g., `StataClient.run_command_structured()`)
- **Daemon-level mocks** (proposed) — for testing the CLI and integration pipeline end-to-end without Stata

Both can coexist. The daemon-level mock is the one that enables CI.

Transition path:
1. Old MCP server tests → use Python-level mocks (existing)
2. New CLI daemon tests → use daemon-level mock (proposed)
3. Both → share `responses/canned.json` as the source of truth for expected outputs

---

## 9. Correct / Fixed / Blocker / Note Summary

### Correct
- Plan section 11.10 correctly identifies the problem (no Stata license = no CI) and solution (mock backend).
- Existing `conftest.py` Python-level mocks are functional for the old MCP server tests.
- `test_mock_protocol.py` exercises 3 basic scenarios and demonstrates the pattern.
- Plan's directory layout (`stata-ai/features/09-mock-test-mode`) is ready for the implementation.

### Fixed
- Created `responses/` subdirectory with 10 captured real Stata outputs for reference (see section 2).
- Documented the critical finding that `stata-se -b` always returns exit code 0 (even on errors), which the mock must handle by parsing output content.

### Blocker
- The empty `09-mock-test-mode/` directory has no implementation yet. This is expected per the plan (step 6 of "Immediate Next Steps").
- No `canned.json` response database exists yet.
- No mock daemon (`mock_daemon.py`) exists yet.
- No shell-level mock-mode integration tests exist yet.

### Note
- The mock should **not** try to replicate Stata's behavior perfectly — that's impossible and defeats the purpose. It should be "good enough" for CI: correct output format for common commands, graceful fallback for everything else.
- The response database should be data-driven (JSON), not code-driven, so it can be updated without changing Python code.
- The syntax validator should be intentionally simple (regex-based) — a full Stata parser would be a separate project.
- The state machine should be optional and minimal. Most CI tests don't need stateful interaction.
- Consider adding a `--mock-verbose` flag that logs which response pattern was matched for debugging.
- The captured outputs in `responses/` use text log format (not SMCL). The mock should default to text-format output to match the plan's "text-first" direction (section 3 and 11.12).
- `stata-se -e 'command'` (inline execute) produces output to stdout but also writes a log file in the current directory. The mock daemon can skip log files entirely.

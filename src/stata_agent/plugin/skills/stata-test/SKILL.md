---
name: stata-test
description: Discover and run statest test suites for Stata do-files.
---

The argument is a path to a test file or directory containing test files.

## CLI Reference

| Command | Description |
|---|---|
| `stata test discover <path>` | List `test_*.do` files under a directory |
| `stata test run <file>` | Run a single test file |
| `stata test run-all <path>` | Run all tests under a directory |

**Discovering tests:**
- Call `stata test discover <path>` to list `test_*.do` files under the given path.
- If no test files are found, report that.

**Running a single test file:**
- Call `stata test run <file>` to execute a single `test_*.do` file.
- Display the results: pass/fail status, which assertions passed or failed, and any error output.

**Running all tests under a directory:**
- Call `stata test run-all <path>` to execute every `test_*.do` file in the directory tree.
- Display a summary of results across all test files.

**On failure:**
Output shows which assertion failed, expected vs actual values, and the last 20 lines of the test log.

## Writing tests

Name test files `test_*.do`. Use these assertions:

```stata
st_assert_scalar r(mean), expected(6165.257) tol(0.001)
st_assert_macro  e(cmd),   expected("regress")
st_assert_rc     111,      cmd("use nonexistent.dta")
st_assert_matrix r(table), expected(M) tol(0.001)
```

## Fixtures

| File | Scope | When |
|------|-------|------|
| `statest_setup.do` | Per-test | Before each test file |
| `statest_teardown.do` | Per-test | After test (always) |
| `statest_conftest.do` | Suite | Once before the suite |

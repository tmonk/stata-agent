# stata-test

Discover and run statest test suites for Stata do-files.

## Commands

- `stata test discover <path>` — List `test_*.do` files
- `stata test run <file>` — Run a single test file
- `stata test run-all <path>` — Run all tests under a directory

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

## On failure

Output shows which assertion failed, expected vs actual values, and
last 20 lines of the test log.

#!/usr/bin/env bash
# Shell-level integration test for statest CLI subcommands.
# Requires: `stata` on PATH (pip install -e .)
set -euo pipefail

cd "$(dirname "$0")/../.."
PROJECT_ROOT=$(pwd)

TMPDIR=$(mktemp -d)
trap "rm -rf '$TMPDIR'" EXIT

# Create test .do files
mkdir -p "$TMPDIR/tests"
cat > "$TMPDIR/tests/test_alpha.do" << 'DOEOF'
st_assert_scalar 1, expected(1)
DOEOF

cat > "$TMPDIR/tests/test_beta.do" << 'DOEOF'
st_assert_scalar 2, expected(2)
DOEOF

export STATA_AGENT_MOCK=1

echo "=== test discover ==="
OUTPUT=$(stata test discover "$TMPDIR/tests" 2>&1)
echo "$OUTPUT"
echo "$OUTPUT" | grep -q "test_alpha.do" || { echo "FAIL: test_alpha.do not discovered"; exit 1; }
echo "$OUTPUT" | grep -q "test_beta.do"  || { echo "FAIL: test_beta.do not discovered"; exit 1; }
echo "$OUTPUT" | grep -q "Found 2 test file" || { echo "FAIL: wrong count"; exit 1; }

echo "=== test run-all ==="
OUTPUT=$(stata test run-all "$TMPDIR/tests" --mock 2>&1)
echo "$OUTPUT"
echo "$OUTPUT" | grep -q "Ran 2 tests" || { echo "FAIL: missing summary"; exit 1; }
echo "$OUTPUT" | grep -q "passed" || { echo "FAIL: expected pass"; exit 1; }

echo "=== test run-all --json ==="
JSON=$(stata --json test run-all "$TMPDIR/tests" --mock 2>&1)
echo "$JSON"
echo "$JSON" | grep -q '"passed": 2' || { echo "FAIL: expected passed:2"; exit 1; }
echo "$JSON" | grep -q '"total_tests": 2' || { echo "FAIL: expected total 2"; exit 1; }

echo "=== test discover (empty) ==="
EMPTY=$(mktemp -d)
OUTPUT=$(stata test discover "$EMPTY" 2>&1)
echo "$OUTPUT"
echo "$OUTPUT" | grep -q "No test files found" || { echo "FAIL: expected empty message"; exit 1; }
rm -rf "$EMPTY"

echo "=== all CLI tests passed ==="

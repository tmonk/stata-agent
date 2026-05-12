#!/usr/bin/env bash
# Test: State persistence across multiple `stata run` invocations
set -euo pipefail

SESSION="test_state_$$
SOCK="$HOME/.cache/mcp-stata/sessions/${SESSION}.sock"

cleanup() {
    stata daemon stop --session "$SESSION" 2>/dev/null || true
    rm -f "$SOCK"
}
trap cleanup EXIT

echo "=== Starting daemon ==="
stata daemon start --session "$SESSION"
sleep 2

echo "=== Step 1: Load data ==="
RESULT=$(stata run --session "$SESSION" --echo 'sysuse auto, clear' --json)
RC=$(echo "$RESULT" | python3 -c "import sys,json; print(json.load(sys.stdin)['result'].get('rc',1))")
if [ "$RC" != "0" ]; then
    echo "FAIL: load data failed"
    exit 1
fi

echo "=== Step 2: Run regression (must see auto dataset) ==="
RESULT=$(stata run --session "$SESSION" --echo 'reg price mpg' --json)
RC=$(echo "$RESULT" | python3 -c "import sys,json; print(json.load(sys.stdin)['result'].get('rc',1))")
if [ "$RC" != "0" ]; then
    echo "FAIL: regression failed (dataset not persisted?)"
    exit 1
fi

echo "=== Step 3: Predict (post-estimation requires state) ==="
RESULT=$(stata run --session "$SESSION" --echo 'predict yhat' --json)
RC=$(echo "$RESULT" | python3 -c "import sys,json; print(json.load(sys.stdin)['result'].get('rc',1))")
if [ "$RC" != "0" ]; then
    echo "FAIL: predict failed (estimation results not persisted?)"
    exit 1
fi

echo "=== ALL STATE TESTS PASSED ==="

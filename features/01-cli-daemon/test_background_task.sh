#!/usr/bin/env bash
# Test: Background task execution and polling
set -euo pipefail

SESSION="test_bg_$$
SOCK="$HOME/.cache/mcp-stata/sessions/${SESSION}.sock"

cleanup() {
    stata daemon stop --session "$SESSION" 2>/dev/null || true
    rm -f "$SOCK"
}
trap cleanup EXIT

echo "=== Starting daemon ==="
stata daemon start --session "$SESSION"
sleep 2

echo "=== Submit background task ==="
RESULT=$(stata run --session "$SESSION" --background --echo 'sleep 2000' --json)
TASK_ID=$(echo "$RESULT" | python3 -c "import sys,json; print(json.load(sys.stdin)['result']['task_id'])")
echo "Task ID: $TASK_ID"

echo "=== Poll for completion (max 30s) ==="
for i in $(seq 1 30); do
    STATUS=$(stata task status --session "$SESSION" --task-id "$TASK_ID" --json)
    STATE=$(echo "$STATUS" | python3 -c "import sys,json; print(json.load(sys.stdin)['result']['status'])")
    echo "  poll $i: $STATE"
    if [ "$STATE" == "done" ] || [ "$STATE" == "failed" ]; then
        break
    fi
    sleep 1
done

if [ "$STATE" != "done" ]; then
    echo "FAIL: background task did not complete"
    exit 1
fi

echo "=== ALL BACKGROUND TESTS PASSED ==="

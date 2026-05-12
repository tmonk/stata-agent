#!/usr/bin/env bash
# Test: Daemon lifecycle — start, run command, verify state persistence, stop
set -euo pipefail

SESSION="test_cli_daemon_$$
SOCK="$HOME/.cache/mcp-stata/sessions/${SESSION}.sock"
META="$HOME/.cache/mcp-stata/sessions/${SESSION}.json"

cleanup() {
    echo "[cleanup] stopping daemon..."
    stata daemon stop --session "$SESSION" 2>/dev/null || true
    rm -f "$SOCK" "$META"
}
trap cleanup EXIT

echo "=== 1. Start daemon ==="
stata daemon start --session "$SESSION"
sleep 2

if [ ! -S "$SOCK" ]; then
    echo "FAIL: socket not created"
    exit 1
fi
echo "PASS: socket exists"

echo "=== 2. Health check via Python ==="
python3 <<PY
import json, socket, sys
sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
sock.connect("$SOCK")
sock.sendall(b'{"id":"h1","method":"health","args":{}}\n')
resp = json.loads(sock.recv(4096).decode().strip())
assert resp["ok"] == True, resp
assert resp["result"]["status"] == "running", resp
print("PASS: health check")
PY

echo "=== 3. Run command ==="
stata run --session "$SESSION" --echo 'display "hello daemon"'

echo "=== 4. State persistence ==="
stata run --session "$SESSION" --echo 'sysuse auto'
stata run --session "$SESSION" --echo 'reg price mpg'

echo "=== 5. Stop daemon ==="
stata daemon stop --session "$SESSION"
sleep 1

if [ -S "$SOCK" ]; then
    echo "FAIL: socket still exists after stop"
    exit 1
fi
echo "PASS: socket removed"

echo "=== ALL TESTS PASSED ==="

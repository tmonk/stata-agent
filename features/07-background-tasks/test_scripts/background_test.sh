#!/bin/bash
# Test 2: Run Stata in background, poll PID, tail log
set -e

cd /tmp/stata-bg-test

# Clean up any previous run
rm -f longjob.log

echo "=== Starting Stata in background ==="
stata-se -b do longjob.do > /tmp/stata-bg-test/background_stdout.log 2>&1 &
STATA_PID=$!
echo "Stata PID: $STATA_PID"

# Record start time
START_TIME=$(date +%s)

# Poll loop: check process status and log
echo "=== Polling every 2 seconds ==="
while kill -0 $STATA_PID 2>/dev/null; do
    ELAPSED=$(($(date +%s) - START_TIME))
    # Process status
    PS_OUTPUT=$(ps -p $STATA_PID -o pid,state,%cpu,%mem,etime 2>/dev/null || echo "process gone")
    # Log tail
    LOG_TAIL=$(tail -3 longjob.log 2>/dev/null || echo "(no log yet)")
    echo "[${ELAPSED}s] PID=$STATA_PID | $PS_OUTPUT | Log: $LOG_TAIL"
    sleep 2
done

ELAPSED=$(($(date +%s) - START_TIME))
echo "=== Process finished after ${ELAPSED}s ==="

# Show exit status
wait $STATA_PID 2>/dev/null
EXIT_CODE=$?
echo "Exit code: $EXIT_CODE"

# Show final log
echo "=== Final log tail ==="
tail -5 longjob.log

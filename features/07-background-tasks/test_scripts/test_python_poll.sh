#!/bin/bash
# Test 5: Use Python polling script against a running Stata job
cd /tmp/stata-bg-test

rm -f longjob.log

# Start Stata in background
stata-se -b do longjob.do > /dev/null 2>&1 &
STATA_PID=$!
echo "Stata PID: $STATA_PID"

# Wait for log file to appear
sleep 2

# Run Python poller
python3 poll_log.py --pid $STATA_PID --log /tmp/stata-bg-test/longjob.log --interval 2.0 --timeout 120

echo ""
echo "Poll script exit code: $?"

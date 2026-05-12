#!/bin/bash
# Test 7: SIGTERM/SIGINT handling during long Stata operations
cd /tmp/stata-bg-test

cleanup() {
    kill $STATA_PID 2>/dev/null
    wait $STATA_PID 2>/dev/null
}

echo "=== Test 7a: SIGTERM during longjob ==="
rm -f longjob.log sterm.log

stata-se -b do longjob.do > sterm.log 2>&1 &
STATA_PID=$!
echo "Started PID $STATA_PID"

sleep 10

echo "Sending SIGTERM to PID $STATA_PID..."
kill -TERM $STATA_PID

sleep 2

# Check if process is still alive
if kill -0 $STATA_PID 2>/dev/null; then
    echo "Process still alive after SIGTERM (ignored?)"
    kill -KILL $STATA_PID 2>/dev/null
else
    echo "Process terminated by SIGTERM"
fi

wait $STATA_PID 2>/dev/null
echo "Exit code: $?"
echo "Log tail:"
tail -5 longjob.log 2>/dev/null || echo "(no log file)"
echo ""

echo "=== Test 7b: SIGINT during longjob ==="
rm -f longjob.log sint.log

stata-se -b do longjob.do > sint.log 2>&1 &
STATA_PID=$!
echo "Started PID $STATA_PID"

sleep 10

echo "Sending SIGINT to PID $STATA_PID..."
kill -INT $STATA_PID

sleep 2

if kill -0 $STATA_PID 2>/dev/null; then
    echo "Process still alive after SIGINT (ignored?)"
    kill -KILL $STATA_PID 2>/dev/null
else
    echo "Process terminated by SIGINT"
fi

wait $STATA_PID 2>/dev/null
echo "Exit code: $?"
echo "Log tail:"
tail -5 longjob.log 2>/dev/null || echo "(no log file)"
echo ""

echo "=== Test 7c: Ctrl+C equivalent (SIGINT with -q mode) ==="
rm -f longjob.log sint2.log

# Run in -q mode (interactive, not batch)
stata-se -q do longjob.do > sint2.log 2>&1 &
STATA_PID=$!
echo "Started PID $STATA_PID in -q mode"

sleep 10

echo "Sending SIGINT to PID $STATA_PID..."
kill -INT $STATA_PID

sleep 3

if kill -0 $STATA_PID 2>/dev/null; then
    echo "Process alive after SIGINT, sending SIGTERM..."
    kill -TERM $STATA_PID
    sleep 2
    if kill -0 $STATA_PID 2>/dev/null; then
        echo "Process still alive, sending SIGKILL..."
        kill -KILL $STATA_PID
    fi
else
    echo "Process terminated by SIGINT"
fi

wait $STATA_PID 2>/dev/null
echo "Exit code: $?"
echo "Log tail:"
tail -10 longjob.log 2>/dev/null || echo "(no log file)"
echo "Log content (sint2.log):"
tail -20 sint2.log

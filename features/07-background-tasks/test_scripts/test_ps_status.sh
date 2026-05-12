#!/bin/bash
# Test 4: Process status checking
cd /tmp/stata-bg-test

rm -f longjob.log

# Start Stata
stata-se -b do longjob.do > /dev/null 2>&1 &
STATA_PID=$!
echo "Stata PID: $STATA_PID"

sleep 5

echo "=== ps output (default) ==="
ps -p $STATA_PID -o pid,state,%cpu,%mem,etime 2>&1

echo ""
echo "=== ps with more detail ==="
ps -p $STATA_PID -o pid,state,stat,%cpu,%mem,vsize,rss,etime,args 2>&1

echo ""
echo "=== pgrep check ==="
pgrep -P $STATA_PID 2>/dev/null || echo "(no child processes)"

echo ""
echo "=== /proc check (macOS: proc_info) ==="
if command -v vmmap &>/dev/null; then
    vmmap -summary $STATA_PID 2>&1 | head -5
else
    echo "vmmap not available, trying lsof:"
    lsof -p $STATA_PID 2>/dev/null | head -5 || echo "lsof not available or no open files"
fi

wait $STATA_PID 2>/dev/null
echo "=== Finished ==="

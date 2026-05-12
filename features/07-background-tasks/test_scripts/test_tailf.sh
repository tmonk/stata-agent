#!/bin/bash
# Test 3: tail -f on a log file while Stata is writing it
cd /tmp/stata-bg-test

# Clean up
rm -f longjob.log tailf_output.txt

# Start Stata in background
stata-se -b do longjob.do > /dev/null 2>&1 &
STATA_PID=$!
echo "Stata PID: $STATA_PID"

# Wait for log file to appear
sleep 3

echo "=== Starting tail -f in background, waiting for 8 seconds ==="
# Use background tail with sleep-based termination
tail -f longjob.log > tailf_output.txt 2>&1 &
TAIL_PID=$!

sleep 8

# Kill tail
kill $TAIL_PID 2>/dev/null
wait $TAIL_PID 2>/dev/null

echo "=== Tail captured $(wc -l < tailf_output.txt) lines ==="
echo "=== First 10 lines of tail output ==="
head -10 tailf_output.txt
echo "=== Last 10 lines of tail output ==="
tail -10 tailf_output.txt

# Wait for Stata to finish
wait $STATA_PID 2>/dev/null
echo "Stata finished with exit code: $?"

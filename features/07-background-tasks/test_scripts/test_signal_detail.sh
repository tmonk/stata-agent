#!/bin/bash
# Test 7d-f: Detailed signal behavior
cd /tmp/stata-bg-test

echo "=== Test 7d: Does -b mode respond to a second SIGTERM? ==="
rm -f longjob.log
stata-se -b do longjob.do > /dev/null 2>&1 &
STATA_PID=$!
sleep 8
echo "Sending SIGTERM..."
kill -TERM $STATA_PID 2>/dev/null
sleep 1
if kill -0 $STATA_PID 2>/dev/null; then
    echo "Still alive after first SIGTERM, sending again..."
    kill -TERM $STATA_PID 2>/dev/null
    sleep 1
    if kill -0 $STATA_PID 2>/dev/null; then
        echo "Still alive after second SIGTERM, killing..."
        kill -KILL $STATA_PID 2>/dev/null
    fi
fi
wait $STATA_PID 2>/dev/null
echo "Exit: $?"
echo ""

echo "=== Test 7e: Log-based progress estimation accuracy ==="
rm -f longjob.log
stata-se -b do longjob.do > /dev/null 2>&1 &
STATA_PID=$!
sleep 1

# Track log growth over time for progress estimation
START_TIME=$(date +%s%N | cut -b1-13)
LAST_SIZE=0
LAST_PROGRESS=""
SAMPLE_COUNT=0

while kill -0 $STATA_PID 2>/dev/null; do
    NOW=$(date +%s%N | cut -b1-13)
    ELAPSED=$(( (NOW - START_TIME) / 1000 ))
    
    if [ -f longjob.log ]; then
        SIZE=$(stat -f%z longjob.log 2>/dev/null || echo 0)
        if [ "$SIZE" != "$LAST_SIZE" ]; then
            GROWTH=$((SIZE - LAST_SIZE))
            CURRENT_PROGRESS=$(grep "PROGRESS:" longjob.log 2>/dev/null | tail -1 | sed 's/.*PROGRESS: //')
            if [ "$CURRENT_PROGRESS" != "$LAST_PROGRESS" ] && [ -n "$CURRENT_PROGRESS" ]; then
                # Estimate completion percentage
                CURRENT_NUM=$(echo "$CURRENT_PROGRESS" | cut -d/ -f1)
                TOTAL_NUM=$(echo "$CURRENT_PROGRESS" | cut -d/ -f2)
                if [ -n "$TOTAL_NUM" ] && [ "$TOTAL_NUM" -gt 0 ]; then
                    PCT=$((CURRENT_NUM * 100 / TOTAL_NUM))
                    ESTIMATED_TOTAL=$((ELAPSED * 100 / (PCT + 1)))
                    ESTIMATED_REMAINING=$((ESTIMATED_TOTAL - ELAPSED))
                    echo "[${ELAPSED}s] Progress: $CURRENT_PROGRESS (${PCT}%) | Log: ${SIZE}B (${GROWTH}B growth) | Est. total: ${ESTIMATED_TOTAL}s | Remaining: ~${ESTIMATED_REMAINING}s"
                fi
                LAST_PROGRESS="$CURRENT_PROGRESS"
            fi
            LAST_SIZE=$SIZE
            SAMPLE_COUNT=$((SAMPLE_COUNT + 1))
        fi
    fi
    sleep 1
done

wait $STATA_PID 2>/dev/null
echo "Total samples: $SAMPLE_COUNT"
echo ""

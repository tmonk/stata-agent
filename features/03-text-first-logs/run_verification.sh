#!/usr/bin/env bash
# =============================================================================
# Text-First Native Logs — Active Stata Verification Script
# =============================================================================
# This script runs the verification tests described in the review.
# Run with: bash run_verification.sh
#
# Requirements: Stata executable in PATH (stata, stata-mp, or stata-se)
# =============================================================================

set -euo pipefail

# --- Discover Stata executable ---
STATA_BIN=""
for candidate in stata-mp stata-se stata; do
    if command -v "$candidate" &>/dev/null; then
        STATA_BIN="$candidate"
        break
    fi
done

if [[ -z "$STATA_BIN" ]]; then
    # macOS common locations
    for path in /Applications/Stata/StataMP.app/Contents/MacOS/StataMP \
                /Applications/Stata/StataSE.app/Contents/MacOS/StataSE \
                /Applications/Stata/Stata.app/Contents/MacOS/Stata \
                /Applications/StataNow/StataNow.app/Contents/MacOS/StataNow; do
        if [[ -x "$path" ]]; then
            STATA_BIN="$path"
            break
        fi
    done
fi

if [[ -z "$STATA_BIN" ]]; then
    echo "ERROR: No Stata executable found. Please ensure Stata is installed and in PATH."
    exit 1
fi

echo "=== Using Stata: $STATA_BIN ==="
echo ""

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# =============================================================================
# 1. Run with text log
# =============================================================================
echo "=== TEST 1: Text log ==="
# We need to wrap the do-file inside a log:
cat > /tmp/run_text.do <<'EOF'
log using /tmp/test_text.log, replace text name(_text_test)
do "__DIR__/test_mixed_output.do"
log close _text_test
EOF
sed "s|__DIR__|${DIR}|g" /tmp/run_text.do > /tmp/run_text_final.do
"$STATA_BIN" -q -b do /tmp/run_text_final.do

echo "Text log created: /tmp/test_text.log"
ls -la /tmp/test_text.log 2>/dev/null || echo "  (file not found — Stata may use .txt extension)"
echo ""

# =============================================================================
# 2. Run with SMCL log
# =============================================================================
echo "=== TEST 2: SMCL log ==="
cat > /tmp/run_smcl.do <<'EOF'
log using /tmp/test_smcl.log, replace smcl name(_smcl_test)
do "__DIR__/test_mixed_output.do"
log close _smcl_test
EOF
sed "s|__DIR__|${DIR}|g" /tmp/run_smcl.do > /tmp/run_smcl_final.do
"$STATA_BIN" -q -b do /tmp/run_smcl_final.do

echo "SMCL log created: /tmp/test_smcl.log"
ls -la /tmp/test_smcl.log 2>/dev/null || echo "  (file not found)"
echo ""

# =============================================================================
# 3. Compare file sizes
# =============================================================================
echo "=== TEST 3: File size comparison ==="
ls -la /tmp/test_text.log /tmp/test_smcl.log 2>/dev/null || true
echo ""

# =============================================================================
# 4. Test translate command
# =============================================================================
echo "=== TEST 4: translate SMCL → text ==="
"$STATA_BIN" -q -b -e "translate /tmp/test_smcl.log /tmp/test_translated.txt, replace translator(smcl2txt)"
ls -la /tmp/test_translated.txt 2>/dev/null || echo "  (translated file not found)"
echo ""

# =============================================================================
# 5. Compare readability — first 30 lines
# =============================================================================
echo "=== TEST 5: Readability comparison (first 30 lines) ==="
echo "--- TEXT log (first 30 lines) ---"
head -n 30 /tmp/test_text.log 2>/dev/null || echo "  (n/a)"
echo ""
echo "--- SMCL log (first 30 lines) ---"
head -n 30 /tmp/test_smcl.log 2>/dev/null || echo "  (n/a)"
echo ""
echo "--- TRANSLATED log (first 30 lines) ---"
head -n 30 /tmp/test_translated.txt 2>/dev/null || echo "  (n/a)"
echo ""

# =============================================================================
# 6. Check for {err} tags in text log
# =============================================================================
echo "=== TEST 6: Check for SMCL {err} tags in text log ==="
if [[ -f /tmp/test_text.log ]]; then
    ERR_COUNT=$(grep -c '{err}' /tmp/test_text.log || true)
    echo "Found {err} occurrences in text log: $ERR_COUNT"
    if [[ "$ERR_COUNT" -eq 0 ]]; then
        echo "PASS: Text log contains no SMCL error tags."
    else
        echo "FAIL: Text log still contains SMCL tags."
        grep -n '{err}' /tmp/test_text.log | head -5
    fi
else
    echo "  (text log not found)"
fi
echo ""

# =============================================================================
# 7. Graph behavior with text logs
# =============================================================================
echo "=== TEST 7: Graph behavior with text log ==="
cat > /tmp/run_graph_text.do <<'EOF'
log using /tmp/test_graph_text.log, replace text name(_graph_text)
do "__DIR__/test_graph_behavior.do"
log close _graph_text
EOF
sed "s|__DIR__|${DIR}|g" /tmp/run_graph_text.do > /tmp/run_graph_text_final.do
"$STATA_BIN" -q -b do /tmp/run_graph_text_final.do

echo "Graph files exported:"
ls -la /tmp/test_graph*.png 2>/dev/null || echo "  (no PNG files found)"
echo ""
echo "Text log with graphs:"
ls -la /tmp/test_graph_text.log 2>/dev/null || true
echo ""

# =============================================================================
# 8. Summary
# =============================================================================
echo "=== VERIFICATION SUMMARY ==="
echo "Stata executable: $STATA_BIN"
echo ""
echo "Files generated:"
ls -la /tmp/test_text.log /tmp/test_smcl.log /tmp/test_translated.txt /tmp/test_graph_text.log /tmp/test_graph*.png 2>/dev/null || true
echo ""
echo "Done."

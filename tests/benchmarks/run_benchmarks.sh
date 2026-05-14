#!/usr/bin/env bash
# Run the full benchmark suite and save results to benchmarks/history/
# Usage: ./tests/benchmarks/run_benchmarks.sh [--quick] [pytest_args...]

set -euo pipefail

cd "$(git rev-parse --show-toplevel 2>/dev/null || echo "$(dirname "$0")/../..")"

QUICK=""
PYTEST_ARGS=()

for arg in "$@"; do
    if [ "$arg" = "--quick" ]; then
        QUICK="--benchmark-min-rounds=2 --benchmark-warmup"
    else
        PYTEST_ARGS+=("$arg")
    fi
done

echo "=== stata-agent Benchmark Suite ==="
echo "Starting: $(date)"
echo "Git commit: $(git rev-parse --short HEAD 2>/dev/null || echo 'unknown')"
echo ""

mkdir -p benchmarks/history

if [ ${#PYTEST_ARGS[@]} -eq 0 ]; then
    uv run pytest tests/benchmarks/ \
        --benchmark-only \
        --benchmark-autosave \
        $QUICK
else
    uv run pytest tests/benchmarks/ \
        --benchmark-only \
        --benchmark-autosave \
        $QUICK \
        "${PYTEST_ARGS[@]}"
fi

echo ""
echo "=== Benchmark complete: $(date) ==="
echo "Results in: benchmarks/history/"
ls -lt benchmarks/history/ | head -5

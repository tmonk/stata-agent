#!/usr/bin/env python3
"""Benchmark backward error scan: practical last-chunk-first approach."""
import os
import re
import sys
import time

ERROR_PATTERNS = [
    re.compile(r'r\(\d+\)'),
    re.compile(r'variable .* not found'),
    re.compile(r'invalid '),
    re.compile(r'no observations'),
    re.compile(r'{err}'),
]


def fast_scan_log_practical(filepath: str, tail_bytes: int = 32768, max_lines: int = 20) -> str:
    """
    Practical backward scan: read the last `tail_bytes` first.
    If errors found there, return them. Only scan deeper if needed.
    This matches real-world usage where errors are in the most recent output.
    """
    file_size = os.path.getsize(filepath)
    if file_size == 0:
        return ""

    matched = []

    with open(filepath, 'rb') as f:
        # Strategy 1: scan last tail_bytes only (fast path)
        start = max(0, file_size - tail_bytes)
        f.seek(start)
        data = f.read()
        # Skip to first newline if we started mid-line
        nl = data.find(b'\n')
        if nl != -1 and start > 0:
            data = data[nl+1:]
        lines = data.decode('utf-8', errors='replace').splitlines()
        for line in reversed(lines):
            if any(p.search(line) for p in ERROR_PATTERNS):
                matched.append(line)
                if len(matched) >= max_lines:
                    return '\n'.join(reversed(matched))

        # Strategy 2: if nothing in tail, do full backward scan
        if start > 0:
            pos = start
            partial = b""
            while pos > 0 and len(matched) < max_lines:
                read_size = min(8192, pos)
                pos -= read_size
                f.seek(pos)
                chunk = f.read(read_size)
                combined = chunk + partial
                nl = combined.rfind(b'\n')
                if nl == -1:
                    partial = combined
                    continue
                partial = combined[:nl]
                lines = combined[nl+1:].split(b'\n')
                for line in reversed(lines):
                    if not line:
                        continue
                    s = line.decode('utf-8', errors='replace')
                    if any(p.search(s) for p in ERROR_PATTERNS):
                        matched.append(s)
                        if len(matched) >= max_lines:
                            break

    return '\n'.join(reversed(matched))


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <logfile>")
        sys.exit(1)

    filepath = sys.argv[1]
    file_size = os.path.getsize(filepath)
    print(f"File: {filepath}")
    print(f"Size: {file_size:,} bytes ({file_size / 1024 / 1024:.2f} MB)")
    print()

    times = []
    for _ in range(10):
        start = time.perf_counter()
        result = fast_scan_log_practical(filepath)
        elapsed = time.perf_counter() - start
        times.append(elapsed)
    avg_ms = sum(times) / len(times) * 1000
    print(f"Practical backward scan (avg of 10): {avg_ms:.3f} ms (min: {min(times)*1000:.3f} ms)")
    print(f"Result length: {len(result)} chars, ~{len(result)//4} tokens")
    if result:
        print("Matched content:")
        print(result[:500])
    else:
        print("No errors found.")

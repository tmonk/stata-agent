#!/usr/bin/env python3
"""Benchmark backward error scan on a large Stata log file (highly optimized)."""
import os
import re
import sys
import time

# Compile raw byte patterns for pre-filtering
ERROR_BYTE_PATTERNS = [p.pattern.encode('utf-8') for p in [
    re.compile(r'r\(\d+\)'),
    re.compile(r'variable .* not found'),
    re.compile(r'invalid '),
    re.compile(r'no observations'),
]]
ERROR_PATTERNS = [
    re.compile(r'r\(\d+\)'),
    re.compile(r'variable .* not found'),
    re.compile(r'invalid '),
    re.compile(r'no observations'),
    re.compile(r'{err}'),
]


def fast_scan_log(filepath: str, chunk_size: int = 4096, max_lines: int = 20) -> str:
    """Scan backwards from end of file, return last N lines containing error patterns."""
    file_size = os.path.getsize(filepath)
    if file_size == 0:
        return ""

    matched_lines = []
    position = file_size
    partial = ""

    with open(filepath, 'rb') as f:
        while position > 0 and len(matched_lines) < max_lines:
            read_size = min(chunk_size, position)
            position -= read_size
            f.seek(position)
            chunk_bytes = f.read(read_size)

            # Quick pre-filter: if no error bytes in chunk and no partial, skip
            has_error_bytes = any(bp in chunk_bytes for bp in ERROR_BYTE_PATTERNS)
            if not has_error_bytes and not partial:
                continue

            chunk = chunk_bytes.decode('utf-8', errors='replace')
            combined = chunk + partial
            lines = combined.splitlines()
            partial = lines[0] if lines else ""
            current_lines = lines[1:] if lines else []

            for line in reversed(current_lines):
                if any(p.search(line) for p in ERROR_PATTERNS):
                    matched_lines.append(line)
                    if len(matched_lines) >= max_lines:
                        break

    if len(matched_lines) < max_lines and partial:
        if any(p.search(partial) for p in ERROR_PATTERNS):
            matched_lines.append(partial)

    return '\n'.join(reversed(matched_lines))


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <logfile>")
        sys.exit(1)

    filepath = sys.argv[1]
    file_size = os.path.getsize(filepath)
    print(f"File: {filepath}")
    print(f"Size: {file_size:,} bytes ({file_size / 1024 / 1024:.2f} MB)")
    print()

    # Benchmark backward scan
    times = []
    for _ in range(10):
        start = time.perf_counter()
        result = fast_scan_log(filepath)
        elapsed = time.perf_counter() - start
        times.append(elapsed)
    avg_ms = sum(times) / len(times) * 1000
    print(f"Backward scan (avg of 10): {avg_ms:.3f} ms (min: {min(times)*1000:.3f} ms)")
    print(f"Result length: {len(result)} chars, ~{len(result)//4} tokens")
    if result:
        print("Matched content:")
        print(result[:500])
    else:
        print("No errors found.")

#!/usr/bin/env python3
"""Benchmark backward error scan on a large Stata log file."""
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


def fast_scan_log(filepath: str, chunk_size: int = 8192, max_lines: int = 20) -> str:
    """Scan backwards from end of file, return last N lines containing error patterns."""
    file_size = os.path.getsize(filepath)
    if file_size == 0:
        return ""

    matched_lines = []
    position = file_size
    partial = ""

    while position > 0 and len(matched_lines) < max_lines:
        read_size = min(chunk_size, position)
        position -= read_size

        with open(filepath, 'rb') as f:
            f.seek(position)
            chunk = f.read(read_size).decode('utf-8', errors='replace')

        # Prepend because we're reading backwards
        combined = chunk + partial
        lines = combined.splitlines()
        partial = lines[0] if lines else ""
        current_lines = lines[1:] if lines else []

        for line in reversed(current_lines):
            if any(p.search(line) for p in ERROR_PATTERNS):
                matched_lines.append(line)
                if len(matched_lines) >= max_lines:
                    break

    # Handle remaining partial at start of file
    if len(matched_lines) < max_lines and partial:
        if any(p.search(partial) for p in ERROR_PATTERNS):
            matched_lines.append(partial)

    return '\n'.join(reversed(matched_lines))


def scan_full_file(filepath: str) -> str:
    """Naive forward scan for comparison."""
    matched = []
    with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
        for line in f:
            if any(p.search(line) for p in ERROR_PATTERNS):
                matched.append(line.rstrip('\n'))
    return '\n'.join(matched[-20:])


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
    start = time.perf_counter()
    result = fast_scan_log(filepath)
    elapsed = time.perf_counter() - start
    print(f"Backward scan: {elapsed*1000:.3f} ms")
    print(f"Result length: {len(result)} chars, ~{len(result)//4} tokens")
    if result:
        print("Matched content:")
        print(result[:500])
    else:
        print("No errors found.")
    print()

    # Benchmark forward scan for comparison
    start = time.perf_counter()
    result_fwd = scan_full_file(filepath)
    elapsed_fwd = time.perf_counter() - start
    print(f"Forward scan: {elapsed_fwd*1000:.3f} ms")
    print(f"Result length: {len(result_fwd)} chars, ~{len(result_fwd)//4} tokens")

#!/usr/bin/env python3
"""Benchmark backward error scan using mmap for speed."""
import mmap
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


def fast_scan_log_mmap(filepath: str, max_lines: int = 20) -> str:
    """Scan backwards using mmap for zero-copy access."""
    file_size = os.path.getsize(filepath)
    if file_size == 0:
        return ""

    matched = []
    with open(filepath, 'rb') as f:
        with mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as mm:
            # Find newline positions from the end
            pos = file_size
            line_count = 0
            while pos > 0 and len(matched) < max_lines:
                # Find previous newline
                start = mm.rfind(b'\n', 0, pos)
                if start == -1:
                    line = mm[0:pos].decode('utf-8', errors='replace')
                    pos = 0
                else:
                    line = mm[start+1:pos].decode('utf-8', errors='replace')
                    pos = start
                line_count += 1
                if any(p.search(line) for p in ERROR_PATTERNS):
                    matched.append(line)
    return '\n'.join(reversed(matched))


def fast_scan_log_chunks(filepath: str, chunk_size: int = 8192, max_lines: int = 20) -> str:
    """Chunked backward scan without mmap."""
    file_size = os.path.getsize(filepath)
    if file_size == 0:
        return ""

    matched = []
    partial = b""
    pos = file_size

    with open(filepath, 'rb') as f:
        while pos > 0 and len(matched) < max_lines:
            read_size = min(chunk_size, pos)
            pos -= read_size
            f.seek(pos)
            chunk = f.read(read_size)
            combined = chunk + partial
            # Split from the right, handling no-newline case
            nl = combined.rfind(b'\n')
            if nl == -1:
                partial = combined
                continue
            partial = combined[:nl+1]
            lines = combined[nl+1:].split(b'\n')
            for line in reversed(lines):
                if not line:
                    continue
                s = line.decode('utf-8', errors='replace')
                if any(p.search(s) for p in ERROR_PATTERNS):
                    matched.append(s)
                    if len(matched) >= max_lines:
                        break

    if partial and len(matched) < max_lines:
        s = partial.decode('utf-8', errors='replace')
        if any(p.search(s) for p in ERROR_PATTERNS):
            matched.append(s)

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

    for name, func in [("mmap", fast_scan_log_mmap), ("chunks", fast_scan_log_chunks)]:
        times = []
        for _ in range(10):
            start = time.perf_counter()
            result = func(filepath)
            elapsed = time.perf_counter() - start
            times.append(elapsed)
        avg_ms = sum(times) / len(times) * 1000
        print(f"{name} backward scan (avg of 10): {avg_ms:.3f} ms (min: {min(times)*1000:.3f} ms)")
        print(f"Result length: {len(result)} chars, ~{len(result)//4} tokens")
        if result:
            print("Matched content:")
            print(result[:500])
        else:
            print("No errors found.")
        print()

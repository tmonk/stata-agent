"""Benchmarks: Log operations and log management.

Exercises: log tail, log search, log errors, log rotator,
truncation functions, tail_file, search_in_log, paginated_read.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

from stata_agent.log_manager import (
    LogRotator,
    tail_file,
    search_in_log,
    paginated_read,
    truncate_for_agent,
    truncate_for_error,
)
from stata_agent.error_extractor import ErrorExtractor


class TestLogTailBenchmarks:
    """Benchmark tail_file on various log sizes."""

    @pytest.mark.benchmark(min_rounds=20, warmup=True)
    def test_tail_small(self, benchmark):
        """Tail 50 lines from a small log (<100 lines)."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False) as f:
            for i in range(80):
                f.write(f"line {i}: some sample log content for testing\n")
            path = f.name

        try:
            result = benchmark(lambda: tail_file(path, lines=50))
            assert len(result.splitlines()) <= 50
        finally:
            os.unlink(path)

    @pytest.mark.benchmark(min_rounds=20, warmup=True)
    def test_tail_large(self, large_log_path, benchmark):
        """Tail 50 lines from a ~5MB log file."""
        result = benchmark(lambda: tail_file(large_log_path, lines=50))
        assert len(result.splitlines()) <= 50

    @pytest.mark.benchmark(min_rounds=10, warmup=True)
    def test_tail_various_sizes(self, large_log_path, benchmark):
        """Tail different line counts from a large log."""
        def _tail_10():
            return tail_file(large_log_path, lines=10)
        result = benchmark(_tail_10)
        assert len(result.splitlines()) <= 10

    @pytest.mark.benchmark(min_rounds=10, warmup=True)
    def test_tail_various_sizes_50(self, large_log_path, benchmark):
        """Tail 50 lines from a large log."""
        def _tail_50():
            return tail_file(large_log_path, lines=50)
        result = benchmark(_tail_50)
        assert len(result.splitlines()) <= 50

    @pytest.mark.benchmark(min_rounds=10, warmup=True)
    def test_tail_various_sizes_200(self, large_log_path, benchmark):
        """Tail 200 lines from a large log."""
        def _tail_200():
            return tail_file(large_log_path, lines=200)
        result = benchmark(_tail_200)
        assert len(result.splitlines()) <= 200

    @pytest.mark.benchmark(min_rounds=10, warmup=True)
    def test_tail_nonexistent_file(self, benchmark):
        """Tail from a nonexistent file (error path)."""
        result = benchmark(lambda: tail_file("/nonexistent/path.log", lines=50))
        assert result == ""


class TestLogSearchBenchmarks:
    """Benchmark search_in_log."""

    @pytest.mark.benchmark(min_rounds=10, warmup=True)
    def test_search_simple_pattern(self, large_log_path, benchmark):
        """Search for a simple regex pattern in a large log."""
        result = benchmark(lambda: search_in_log(large_log_path, r"regress", offset=0))
        assert "matches" in result

    @pytest.mark.benchmark(min_rounds=10, warmup=True)
    def test_search_negation_pattern(self, large_log_path, benchmark):
        """Search with no matches in a large log."""
        result = benchmark(lambda: search_in_log(large_log_path, r"XYZZYX_NOT_FOUND", offset=0))
        assert result["matches"] == []

    @pytest.mark.benchmark(min_rounds=5, warmup=True)
    def test_search_with_offset(self, large_log_path, benchmark):
        """Search starting from a mid-file offset."""
        file_size = os.path.getsize(large_log_path)
        mid = file_size // 2
        result = benchmark(lambda: search_in_log(large_log_path, r"regress", offset=mid))
        assert "matches" in result

    @pytest.mark.benchmark(min_rounds=5, warmup=True)
    def test_search_max_bytes_variants(self, large_log_path, benchmark):
        """Search with small max_bytes (tests pagination pattern)."""
        result = benchmark(lambda: search_in_log(large_log_path, r"regress", offset=0, max_bytes=4096))
        assert "matches" in result


class TestLogPaginatedReadBenchmarks:
    """Benchmark paginated_read."""

    @pytest.mark.benchmark(min_rounds=10, warmup=True)
    def test_paginated_read_large(self, large_log_path, benchmark):
        """Read a chunk from a large log."""
        result = benchmark(lambda: paginated_read(large_log_path, offset=0, max_bytes=65536))
        assert "data" in result
        assert len(result["data"]) > 0

    @pytest.mark.benchmark(min_rounds=10, warmup=True)
    def test_paginated_read_mid_offset(self, large_log_path, benchmark):
        """Read from mid-file offset."""
        file_size = os.path.getsize(large_log_path)
        mid = file_size // 2
        result = benchmark(lambda: paginated_read(large_log_path, offset=mid, max_bytes=65536))
        assert "data" in result


class TestLogTruncationBenchmarks:
    """Benchmark truncation functions."""

    @pytest.mark.benchmark(min_rounds=20, warmup=True)
    def test_truncate_for_agent_small(self, benchmark):
        """Truncate text smaller than limit (fast path)."""
        text = "Hello, world!\n" * 10
        result = benchmark(lambda: truncate_for_agent(text, max_chars=4000))
        assert result[1] is False

    @pytest.mark.benchmark(min_rounds=20, warmup=True)
    def test_truncate_for_agent_large(self, benchmark):
        """Truncate text much larger than limit."""
        text = "This is a line of output in the Stata log.\n" * 10_000
        result = benchmark(lambda: truncate_for_agent(text, max_chars=1000))
        assert result[1] is True

    @pytest.mark.benchmark(min_rounds=20, warmup=True)
    def test_truncate_for_error(self, benchmark):
        """Truncate error context text."""
        text = "x" * 10_000
        result = benchmark(lambda: truncate_for_error(text, max_chars=256))
        assert len(result) <= 256 + 15  # allow for "[truncated]" suffix


class TestLogRotatorBenchmarks:
    """Benchmark LogRotator operations."""

    @pytest.mark.benchmark(min_rounds=20, warmup=True)
    def test_rotate_if_needed_no_rotation(self, benchmark):
        """Rotate check when no rotation is needed (fast path)."""
        rotator = LogRotator("bench-test", max_commands_per_log=99999, max_log_bytes=999_999_999)
        rotator.command_count = 5

        def _check():
            return rotator.rotate_if_needed()

        assert benchmark(_check) is False

    @pytest.mark.benchmark(min_rounds=10, warmup=True)
    def test_rotate_if_needed_by_count(self, benchmark):
        """Rotate when command count exceeds max."""
        import tempfile

        def _rotate():
            # Create fresh rotator for each invocation
            with tempfile.TemporaryDirectory() as tmpdir:
                r = LogRotator("bench-test", log_dir=Path(tmpdir), max_commands_per_log=1, max_log_bytes=999_999_999)
                r.current_path = Path(tmpdir) / "test.log"
                r.current_path.write_text("some content\n")
                r.command_count = 2
                return r.rotate_if_needed()

        result = benchmark(_rotate)
        assert result is True

    @pytest.mark.benchmark(min_rounds=20, warmup=True)
    def test_rotator_new_path(self, benchmark):
        """Benchmark generating a new log path."""
        def _make_rotator_and_path():
            r = LogRotator("bench-test")
            return r._new_path()

        path = benchmark(_make_rotator_and_path)
        assert str(path).endswith(".log")


class TestErrorExtractionBenchmarks:
    """Benchmark ErrorExtractor operations."""

    extractor = ErrorExtractor()

    @pytest.mark.benchmark(min_rounds=20, warmup=True)
    def test_extract_no_error(self, benchmark):
        """Extract from clean log text (fast path - no error found)."""
        text = ". display 1+1\n2\n. exit\n"
        result = benchmark(lambda: self.extractor.extract(text))
        assert result is None

    @pytest.mark.benchmark(min_rounds=20, warmup=True)
    def test_extract_marker_error(self, benchmark):
        """Extract using structured [AGENT-ERROR] markers (Phase 1)."""
        text = (
            "some output\n"
            "more output\n"
            "[AGENT-ERROR] rc=111\n"
            "[AGENT-MSG] variable not found\n"
            "r(111);\n"
        )
        result = benchmark(lambda: self.extractor.extract(text))
        assert result is not None
        assert result.rc == 111

    @pytest.mark.benchmark(min_rounds=20, warmup=True)
    def test_extract_fallback_r_code(self, benchmark):
        """Extract using fallback r(NNN); pattern (Phase 2)."""
        text = ". regress y z\nvariable y not found\nr(111);\n"
        result = benchmark(lambda: self.extractor.extract(text))
        assert result is not None
        assert result.rc == 111
        assert result.source == "r_code"

    @pytest.mark.benchmark(min_rounds=20, warmup=True)
    def test_extract_fallback_assertion(self, benchmark):
        """Extract assertion failure via Phase 2."""
        text = ". assert 1==0\nassertion is false\nr(9);\n"
        result = benchmark(lambda: self.extractor.extract(text))
        assert result is not None
        assert result.rc == 9
        assert result.source in ("assertion", "r_code")

    @pytest.mark.benchmark(min_rounds=10, warmup=True)
    def test_extract_deep_from_large_log(self, large_log_with_error_path, benchmark):
        """Deep backward scan on a large log with error at end."""
        result = benchmark(lambda: self.extractor.extract_deep(large_log_with_error_path))
        assert result is not None
        assert result.rc == 111

    @pytest.mark.benchmark(min_rounds=10, warmup=True)
    def test_extract_from_tail_fast(self, large_log_with_error_path, benchmark):
        """Fast tail extraction from a large log."""
        result = benchmark(lambda: self.extractor.extract_from_tail(large_log_with_error_path))
        assert result is not None
        assert result.rc == 111

    @pytest.mark.benchmark(min_rounds=5, warmup=True)
    def test_extract_deep_clean_log(self, large_log_path, benchmark):
        """Deep scan of a clean log with no errors."""
        result = benchmark(lambda: self.extractor.extract_deep(large_log_path))
        assert result is None

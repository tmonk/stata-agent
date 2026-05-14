"""Benchmarks: statest test runner, session pool, and models.

Exercises: test discovery (glob operations), model serialization,
session pool acquire/release.
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
from pathlib import Path

import pytest

from stata_agent.statest.models import (
    TestResult,
    AssertionFailure,
    TestSuiteSummary,
)
from stata_agent.statest.runner import discover_tests
from stata_agent.statest.junit import write_junit_xml


class TestStatestModelsBenchmarks:
    """Benchmark statest model creation and serialization."""

    @pytest.mark.benchmark(min_rounds=100, warmup=True)
    def test_create_test_result(self, benchmark):
        """Create a TestResult dataclass."""
        result = benchmark(lambda: TestResult(
            test_path="/path/to/test_foo.do",
            success=True,
            rc=0,
            duration_seconds=1.234,
        ))
        assert result.success

    @pytest.mark.benchmark(min_rounds=100, warmup=True)
    def test_create_assertion_failure(self, benchmark):
        """Create an AssertionFailure dataclass."""
        result = benchmark(lambda: AssertionFailure(
            test="test_foo.do",
            assertion_index=1,
            command="st_assert_scalar",
            variable="",
            expected="5000.0",
            actual="6165.257",
            tolerance=0.0,
            rc=9,
        ))
        assert result.rc == 9

    @pytest.mark.benchmark(min_rounds=100, warmup=True)
    def test_model_to_dict(self, benchmark):
        """Serialize TestResult to dict."""
        tr = TestResult(
            test_path="/path/to/test_foo.do",
            success=True,
            rc=0,
            duration_seconds=1.234,
        )

        def _to_dict():
            return tr.model_dump()

        d = benchmark(_to_dict)
        assert d["success"]

    @pytest.mark.benchmark(min_rounds=100, warmup=True)
    def test_model_to_json(self, benchmark):
        """Serialize TestResult to JSON string."""
        tr = TestResult(
            test_path="/path/to/test_foo.do",
            success=True,
            rc=0,
            duration_seconds=1.234,
        )

        def _to_json():
            return tr.model_dump_json()

        s = benchmark(_to_json)
        assert '"success":true' in s

    @pytest.mark.benchmark(min_rounds=50, warmup=True)
    def test_create_summary(self, benchmark):
        """Create TestSuiteSummary with multiple results."""
        results = [
            TestResult(test_path=f"/path/test_{i}.do", success=i % 2 == 0, rc=0 if i % 2 == 0 else 9, duration_seconds=0.5)
            for i in range(50)
        ]

        def _create():
            return TestSuiteSummary(
                path="/path",
                total_tests=len(results),
                passed=sum(1 for r in results if r.success),
                failed=sum(1 for r in results if not r.success),
                results=results,
                summary_text=f"Ran {len(results)} tests",
            )

        s = benchmark(_create)
        assert s.total_tests == 50


class TestTestDiscoveryBenchmarks:
    """Benchmark test file discovery."""

    @pytest.mark.benchmark(min_rounds=10, warmup=True)
    def test_discover_tests_in_project(self, benchmark):
        """Discover test files in the project's tests directory."""
        test_dir = str(Path(__file__).resolve().parent.parent / "statest")

        def _discover():
            return discover_tests(test_dir)

        files = benchmark(_discover)
        assert isinstance(files, list)
        assert len(files) > 0

    @pytest.mark.benchmark(min_rounds=50, warmup=True)
    def test_discover_empty_dir(self, benchmark):
        """Discover tests in a directory with no test files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = benchmark(lambda: discover_tests(tmpdir))
            assert result == []


class TestJUnitWriterBenchmarks:
    """Benchmark JUnit XML writing."""

    @pytest.mark.benchmark(min_rounds=20, warmup=True)
    def test_write_junit_xml(self, benchmark):
        """Write JUnit XML for a test suite with many results."""
        results = [
            TestResult(
                test_path=f"/path/test_{i}.do",
                success=i % 2 == 0,
                rc=0 if i % 2 == 0 else 9,
                duration_seconds=0.5 + (i * 0.01),
                failure=AssertionFailure(
                    test=f"test_{i}.do",
                    assertion_index=1,
                    command="st_assert_scalar",
                    variable="",
                    expected="5000.0",
                    actual="6165.257",
                    tolerance=0.0,
                    rc=9,
                ) if i % 2 != 0 else None,
            )
            for i in range(20)
        ]
        summary = TestSuiteSummary(
            path="/path",
            total_tests=20,
            passed=10,
            failed=10,
            results=results,
            summary_text="Ran 20 tests",
        )

        with tempfile.NamedTemporaryFile(suffix=".xml", delete=False, mode="w") as f:
            tmp_path = f.name

        try:
            benchmark(lambda: write_junit_xml(summary, tmp_path))
            # Verify it wrote something
            size = os.path.getsize(tmp_path)
            assert size > 0
        finally:
            os.unlink(tmp_path)

"""Benchmarks: Linter operations.

Exercises: lint_text on various do-file patterns, including
large files, files with errors, and clean files.
"""

from __future__ import annotations

import os
import tempfile

import pytest

from stata_agent.linter import lint_text, lint_file, format_lint_results


class TestLinterBenchmarks:
    """Benchmark the do-file linter."""

    @pytest.mark.benchmark(min_rounds=50, warmup=True)
    def test_lint_clean_short(self, benchmark):
        """Lint a short clean do-file."""
        code = """* clean do-file
version 18
clear all
set more off
sysuse auto, clear
describe
summarize price mpg
exit
"""
        result = benchmark(lambda: lint_text(code))
        # Should have no errors
        errors = [i for i in result if i.severity == "error"]
        assert len(errors) == 0

    @pytest.mark.benchmark(min_rounds=50, warmup=True)
    def test_lint_with_errors(self, benchmark):
        """Lint a do-file with common issues."""
        code = """version 18
forvalues i = 1/5 {
    display `i'
    foreach var in price mpg {
        summarize `var'
}
"""
        result = benchmark(lambda: lint_text(code))
        # Should find unclosed brace
        errors = [i for i in result if i.severity == "error"]
        assert any("Unclosed" in e.message for e in errors)

    @pytest.mark.benchmark(min_rounds=10, warmup=True)
    def test_lint_large_file(self, large_dofile_path, benchmark):
        """Lint a large do-file (~2000 lines)."""
        result = benchmark(lambda: lint_file(large_dofile_path))
        errors = [i for i in result if i.severity == "error"]
        assert len(errors) == 0

    @pytest.mark.benchmark(min_rounds=50, warmup=True)
    def test_lint_mata_block(self, benchmark):
        """Lint a do-file with Mata blocks."""
        code = """version 18
clear all
mata:
    real matrix A
    A = J(3,3,1)
    A[1,1] = 42
    A'
end
display "back to Stata"
"""
        result = benchmark(lambda: lint_text(code))
        errors = [i for i in result if i.severity == "error"]
        assert len(errors) == 0, f"Unexpected errors: {[e.message for e in errors]}"

    @pytest.mark.benchmark(min_rounds=50, warmup=True)
    def test_lint_mata_unclosed(self, benchmark):
        """Lint a do-file with unclosed Mata block."""
        code = """version 18
mata:
    x = 1+1
display "outside mata"
"""
        result = benchmark(lambda: lint_text(code))
        errors = [i for i in result if i.severity == "error"]
        assert any("Mata" in e.message for e in errors)

    @pytest.mark.benchmark(min_rounds=10, warmup=True)
    def test_lint_empty_file(self, benchmark):
        """Lint an empty do-file."""
        result = benchmark(lambda: lint_text(""))
        info = [i for i in result if i.severity == "info"]
        assert any("No issues" in e.message for e in info)

    @pytest.mark.benchmark(min_rounds=20, warmup=True)
    def test_format_lint_results(self, benchmark):
        """Benchmark formatting lint results."""
        issues = lint_text("""version 18\nforvalues i = 1/5 {\n    display `i'\n""")
        result = benchmark(lambda: format_lint_results(issues))
        assert len(result) > 0

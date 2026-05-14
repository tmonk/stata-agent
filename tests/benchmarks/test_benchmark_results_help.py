"""Benchmarks: Results and help system flows.

Exercises: get_results (r/e/s-class), help system on a real Stata instance.
"""

from __future__ import annotations

import pytest


@pytest.mark.requires_stata
class TestResultsBenchmarks:
    """Benchmark stored-results and help flows."""

    # --- Results ---

    @pytest.mark.benchmark(min_rounds=5, warmup=True)
    def test_get_results_r_class(self, stata_client, benchmark):
        """Benchmark retrieving r() results after summarize."""
        stata_client.run("sysuse auto, clear", echo=False)
        stata_client.run("summarize price mpg", echo=False)

        def _get():
            return stata_client.get_results("r")

        result = benchmark(_get)
        assert "stored_results" in result

    @pytest.mark.benchmark(min_rounds=5, warmup=True)
    def test_get_results_e_class(self, stata_client, benchmark):
        """Benchmark retrieving e() results after regress."""
        stata_client.run("sysuse auto, clear", echo=False)
        stata_client.run("regress price mpg weight", echo=False)

        def _get():
            return stata_client.get_results("e")

        result = benchmark(_get)
        assert "stored_results" in result

    @pytest.mark.benchmark(min_rounds=5, warmup=True)
    def test_get_results_s_class(self, stata_client, benchmark):
        """Benchmark retrieving s() results."""
        stata_client.run("sysuse auto, clear", echo=False)

        def _get():
            return stata_client.get_results("s")

        result = benchmark(_get)
        assert "stored_results" in result



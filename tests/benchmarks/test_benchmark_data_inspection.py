"""Benchmarks: Data inspection flows.

Exercises: describe, summary, codebook, list, get (export) on a real
Stata instance with the auto dataset loaded.
"""

from __future__ import annotations

import os
import tempfile

import pytest


@pytest.mark.requires_stata
class TestDataInspectionBenchmarks:
    """Benchmark data inspection operations on real Stata."""

    @pytest.mark.benchmark(min_rounds=5, warmup=True)
    def test_inspect_describe(self, stata_client_with_auto, benchmark):
        """Benchmark describe command."""

        def _describe():
            return stata_client_with_auto.inspect_describe()

        result = benchmark(_describe)
        assert "variables" in result

    @pytest.mark.benchmark(min_rounds=5, warmup=True)
    def test_inspect_describe_with_varlist(self, stata_client_with_auto, benchmark):
        """Benchmark describe with specific variables."""

        def _describe():
            return stata_client_with_auto.inspect_describe(
                varlist="price mpg weight"
            )

        result = benchmark(_describe)
        assert "variables" in result

    @pytest.mark.benchmark(min_rounds=5, warmup=True)
    def test_inspect_summary(self, stata_client_with_auto, benchmark):
        """Benchmark summarize command."""

        def _summary():
            return stata_client_with_auto.inspect_summary(
                varlist="price mpg weight length"
            )

        result = benchmark(_summary)
        assert "text" in result

    @pytest.mark.benchmark(min_rounds=5, warmup=True)
    def test_inspect_codebook(self, stata_client_with_auto, benchmark):
        """Benchmark codebook command."""

        def _codebook():
            return stata_client_with_auto.inspect_codebook(
                varlist="price mpg"
            )

        result = benchmark(_codebook)
        assert "text" in result

    @pytest.mark.benchmark(min_rounds=5, warmup=True)
    def test_inspect_list(self, stata_client_with_auto, benchmark):
        """Benchmark list command."""

        def _list():
            return stata_client_with_auto.inspect_list(
                varlist="price mpg weight",
                from_row=1,
                count=10,
            )

        result = benchmark(_list)
        assert "text" in result

    @pytest.mark.benchmark(min_rounds=5, warmup=True)
    def test_inspect_get_csv(self, stata_client_with_auto, benchmark):
        """Benchmark export data as CSV."""
        tmp = tempfile.NamedTemporaryFile(suffix=".csv", delete=False)
        tmp.close()
        os.unlink(tmp.name)
        out_path = tmp.name

        def _get():
            return stata_client_with_auto.inspect_get(
                format="csv", out_path=out_path,
                varlist="price mpg weight",
            )

        try:
            result = benchmark(_get)
            assert "path" in result
        finally:
            if os.path.exists(out_path):
                os.unlink(out_path)

    @pytest.mark.benchmark(min_rounds=5, warmup=True)
    def test_inspect_get_json(self, stata_client_with_auto, benchmark):
        """Benchmark export data as JSON."""
        # Check if jsonio is available in this Stata installation
        stdout, rc = stata_client_with_auto._stata_run('capture which jsonio', echo=False)
        stdout2, rc2 = stata_client_with_auto._stata_run('display "rc=" _rc', echo=False)
        if "rc=0" not in stdout2:
            pytest.skip("jsonio not installed in this Stata")

        tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        tmp.close()
        os.unlink(tmp.name)
        out_path = tmp.name

        def _get():
            return stata_client_with_auto.inspect_get(
                format="json", out_path=out_path,
                varlist="price mpg",
            )

        try:
            result = benchmark(_get)
            assert "path" in result
        finally:
            if os.path.exists(out_path):
                os.unlink(out_path)

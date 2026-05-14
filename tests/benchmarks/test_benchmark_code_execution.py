"""Benchmarks: Code execution flow (run and run-file).

Exercises the full run path on a real Stata instance via StataClient.
Stata must be licensed; tests are auto-skipped otherwise.
"""

from __future__ import annotations

import os
import tempfile

import pytest


@pytest.mark.requires_stata
class TestCodeExecutionBenchmarks:
    """Benchmark code execution via real Stata."""

    @pytest.mark.benchmark(min_rounds=10, warmup=True)
    def test_run_simple_code(self, stata_client, benchmark):
        """Benchmark executing a simple display command."""

        def _run():
            return stata_client.run("display 1+1", echo=True, max_output_tokens=1000)

        result = benchmark(_run)
        assert result.ok is True

    @pytest.mark.benchmark(min_rounds=10, warmup=True)
    def test_run_no_echo(self, stata_client, benchmark):
        """Benchmark run with echo=False."""

        def _run():
            return stata_client.run("display 2+2", echo=False, max_output_tokens=1000)

        result = benchmark(_run)
        assert result.ok is True

    @pytest.mark.benchmark(min_rounds=5, warmup=True)
    def test_run_multiline_code(self, stata_client, benchmark):
        """Benchmark multiline code block executed via temp do-file."""
        code = (
            'sysuse auto, clear\n'
            'regress price mpg weight\n'
            'predict price_pred\n'
            'summarize price_pred\n'
        )

        def _run():
            return stata_client.run(code, echo=True, max_output_tokens=1000)

        result = benchmark(_run)
        assert result.ok is True

    @pytest.mark.benchmark(min_rounds=5, warmup=True)
    def test_run_with_output_truncation(self, stata_client, benchmark):
        """Benchmark run with small max_output_tokens (triggers truncation)."""

        def _run():
            return stata_client.run(
                'sysuse auto, clear\nregress price mpg weight\n',
                echo=True, max_output_tokens=50,
            )

        result = benchmark(_run)
        assert result.truncated is True

    @pytest.mark.benchmark(min_rounds=5, warmup=True)
    def test_run_file(self, stata_client, benchmark):
        """Benchmark do-file execution via run_file."""
        tmp = tempfile.NamedTemporaryFile(
            suffix=".do", mode="w", delete=False, encoding="utf-8"
        )
        tmp.write('display "hello from file"\nsysuse auto, clear\ndescribe\n')
        tmp.close()

        def _run():
            return stata_client.run_file(tmp.name, echo=False)

        try:
            result = benchmark(_run)
            assert result.ok is True
        finally:
            os.unlink(tmp.name)

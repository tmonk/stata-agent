"""Benchmarks: Graph operation flows.

Exercises: graph listing, graph tracking (bundled), graph export on a real
Stata instance.  The auto dataset is loaded and a graph is created for testing.
"""

from __future__ import annotations

import os
import tempfile

import pytest


@pytest.mark.requires_stata
class TestGraphOperationBenchmarks:
    """Benchmark graph operations on real Stata."""

    @pytest.fixture(scope="class")
    def stata_with_graph(self, stata_client):
        """Load data and create a graph for benchmark tests."""
        stata_client.run("sysuse auto, clear", echo=False, track_graphs=False)
        stata_client.run("scatter price mpg, name(testgraph)", echo=False, track_graphs=False)
        return stata_client

    # ---------------------------------------------------------------
    # Graph listing (standalone snapshot_graphs query)
    # ---------------------------------------------------------------

    @pytest.mark.benchmark(min_rounds=5, warmup=True)
    def test_graph_list(self, stata_with_graph, benchmark):
        """Benchmark listing graph names via snapshot_graphs()."""

        def _list():
            return stata_with_graph.snapshot_graphs()

        result = benchmark(_list)
        assert "testgraph" in result

    # ---------------------------------------------------------------
    # run() graph tracking — zero-cost default
    # ---------------------------------------------------------------

    @pytest.mark.benchmark(min_rounds=10, warmup=True)
    def test_run_track_graphs_false(self, stata_with_graph, benchmark):
        """Benchmark run() with track_graphs=False (zero graph overhead)."""

        def _run():
            return stata_with_graph.run(
                "display 1+1", echo=False, track_graphs=False,
                max_output_tokens=1000,
            )

        result = benchmark(_run)
        assert result.ok is True

    # ---------------------------------------------------------------
    # run() graph tracking — bundled query
    # ---------------------------------------------------------------

    @pytest.mark.benchmark(min_rounds=10, warmup=True)
    def test_run_track_graphs_true(self, stata_with_graph, benchmark):
        """Benchmark run() with track_graphs=True (bundled graph query)."""

        def _run():
            return stata_with_graph.run(
                "display 1+1", echo=False, track_graphs=True,
                max_output_tokens=1000,
            )

        result = benchmark(_run)
        assert result.ok is True

    # ---------------------------------------------------------------
    # execute() graph tracking — direct bundled call
    # ---------------------------------------------------------------

    @pytest.mark.benchmark(min_rounds=10, warmup=True)
    def test_execute_track_graphs_true(self, stata_with_graph, benchmark):
        """Benchmark pystata_x execute() with track_graphs=True."""
        from pystata_x._core import execute

        def _exec():
            return execute("display 1+1", echo=False, capture=True,
                           track_graphs=True)

        result = benchmark(_exec)
        assert result.rc == 0

    @pytest.mark.benchmark(min_rounds=5, warmup=True)
    def test_graph_export(self, stata_with_graph, benchmark):
        """Benchmark exporting a graph to PDF."""
        tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
        tmp.close()
        os.unlink(tmp.name)
        out_path = tmp.name

        def _export():
            return stata_with_graph.export_graph(
                name="testgraph", fmt="pdf", out_path=out_path,
            )

        try:
            result = benchmark(_export)
            assert result.get("size_bytes", 0) > 0
        finally:
            if os.path.exists(out_path):
                os.unlink(out_path)

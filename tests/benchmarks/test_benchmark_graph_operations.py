"""Benchmarks: Graph operation flows.

Exercises: graph listing, graph export on a real Stata instance.
The auto dataset is loaded and a graph is created for testing.
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
        stata_client.run("sysuse auto, clear", echo=False)
        stata_client.run("scatter price mpg, name(testgraph)", echo=False)
        return stata_client

    @pytest.mark.benchmark(min_rounds=5, warmup=True)
    def test_graph_list(self, stata_with_graph, benchmark):
        """Benchmark listing graph names."""

        def _list():
            return stata_with_graph.snapshot_graphs()

        result = benchmark(_list)
        assert "testgraph" in result

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

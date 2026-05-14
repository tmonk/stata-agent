"""Benchmarks: Helper utilities and pure functions.

Exercises: graph_handler helpers, model creation, discovery, RPC client helpers.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path

import pytest

from stata_agent.graph_handler import (
    snapshot_graphs_from_run_result,
    format_graph_summary,
    make_export_name,
)
from stata_agent.discovery import (
    find_stata_candidates,
    _parse_edition_from_binary,
    clear_cache,
)
from stata_agent.log_manager import LogRotator



class TestGraphHelpersBenchmarks:
    """Benchmark graph helper functions."""

    @pytest.mark.benchmark(min_rounds=50, warmup=True)
    def test_snapshot_graphs_from_result(self, benchmark):
        """Parse graph names from a run result."""
        result = {
            "graphs": {
                "current": ["Graph", "Graph1", "my_scatter", "hist_price"],
            }
        }

        def _parse():
            return snapshot_graphs_from_run_result(result)

        names = benchmark(_parse)
        assert names == {"Graph", "Graph1", "my_scatter", "hist_price"}

    @pytest.mark.benchmark(min_rounds=50, warmup=True)
    def test_snapshot_graphs_empty(self, benchmark):
        """Parse empty graph result."""
        result = {"graphs": {"current": []}}

        def _parse():
            return snapshot_graphs_from_run_result(result)

        names = benchmark(_parse)
        assert names == set()

    @pytest.mark.benchmark(min_rounds=50, warmup=True)
    def test_format_graph_summary(self, benchmark):
        """Format graph delta into human-readable string."""
        delta = {
            "created": ["graph1", "graph2"],
            "dropped": ["old_graph"],
            "current": ["graph1", "graph2"],
        }
        result = benchmark(lambda: format_graph_summary(delta))
        assert "Created" in result
        assert "Dropped" in result
        assert "Current" in result

    @pytest.mark.benchmark(min_rounds=50, warmup=True)
    def test_make_export_name_named(self, benchmark):
        """Generate export filename for a named graph."""
        result = benchmark(lambda: make_export_name("my_scatter"))
        assert result == "my_scatter"

    @pytest.mark.benchmark(min_rounds=50, warmup=True)
    def test_make_export_name_unnamed(self, benchmark):
        """Generate export filename for the default 'Graph'."""
        # Reset counter
        from stata_agent.graph_handler import _unnamed_counter
        _unnamed_counter = 0

        # Benchmark multiple calls
        results = []
        for _ in range(4):
            results.append(make_export_name("Graph"))
        assert results[0] == "_unnamed1"
        assert results[3] == "_unnamed4"


class TestDiscoveryBenchmarks:
    """Benchmark Stata discovery functions."""

    @pytest.mark.benchmark(min_rounds=50, warmup=True)
    def test_parse_edition_se(self, benchmark):
        """Parse Stata edition from binary path (SE)."""
        result = benchmark(lambda: _parse_edition_from_binary("/usr/local/bin/stata-se"))
        assert result == "SE"

    @pytest.mark.benchmark(min_rounds=50, warmup=True)
    def test_parse_edition_mp(self, benchmark):
        """Parse Stata edition from binary path (MP)."""
        result = benchmark(lambda: _parse_edition_from_binary("/usr/local/bin/stata-mp"))
        assert result == "MP"

    @pytest.mark.benchmark(min_rounds=50, warmup=True)
    def test_parse_edition_be(self, benchmark):
        """Parse Stata edition from binary path (BE)."""
        result = benchmark(lambda: _parse_edition_from_binary("/usr/local/bin/stata-be"))
        assert result == "BE"

    @pytest.mark.benchmark(min_rounds=10, warmup=True)
    def test_find_candidates(self, benchmark):
        """Enumerate Stata candidate paths (no verification)."""
        clear_cache()
        result = benchmark(find_stata_candidates)
        assert isinstance(result, list)

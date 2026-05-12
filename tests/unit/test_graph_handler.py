"""Unit tests for graph_handler."""

from __future__ import annotations

from stata_agent.graph_handler import (
    compute_graph_delta,
    format_graph_summary,
    make_export_name,
)


class TestGraphDelta:
    def test_no_change(self):
        delta = compute_graph_delta({"g1", "g2"}, {"g1", "g2"})
        assert delta["created"] == []
        assert delta["dropped"] == []
        assert delta["current"] == ["g1", "g2"]

    def test_created(self):
        delta = compute_graph_delta({"g1"}, {"g1", "g2"})
        assert delta["created"] == ["g2"]
        assert delta["dropped"] == []

    def test_dropped(self):
        delta = compute_graph_delta({"g1", "g2"}, {"g1"})
        assert delta["created"] == []
        assert delta["dropped"] == ["g2"]

    def test_both(self):
        delta = compute_graph_delta({"g1"}, {"g2"})
        assert delta["created"] == ["g2"]
        assert delta["dropped"] == ["g1"]

    def test_empty_before(self):
        delta = compute_graph_delta(set(), {"g1"})
        assert delta["created"] == ["g1"]

    def test_empty_after(self):
        delta = compute_graph_delta({"g1"}, set())
        assert delta["dropped"] == ["g1"]


class TestFormatGraphSummary:
    def test_empty(self):
        s = format_graph_summary({"created": [], "dropped": [], "current": []})
        assert "No graphs" in s

    def test_created_only(self):
        s = format_graph_summary({"created": ["g1"], "dropped": [], "current": ["g1"]})
        assert "Created: g1" in s

    def test_mixed(self):
        s = format_graph_summary({
            "created": ["g2"], "dropped": ["g1"], "current": ["g2"],
        })
        assert "Created: g2" in s
        assert "Dropped: g1" in s


class TestMakeExportName:
    def test_named_graph(self):
        assert make_export_name("g1") == "g1"

    def test_unnamed_graph(self):
        name = make_export_name("Graph")
        assert name.startswith("_unnamed")

    def test_multiple_unnamed(self):
        n1 = make_export_name("Graph")
        n2 = make_export_name("Graph")
        assert n1 != n2

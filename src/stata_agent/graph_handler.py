"""Graph delta detection — post-run snapshot comparison.

Replaces the ~1,010 LOC of streaming graph cache with ~40 LOC of
pre/post delta logic.
"""

from __future__ import annotations


def snapshot_graphs_from_run_result(result: dict) -> set[str]:
    """Extract current graph names from a run result."""
    graphs = result.get("graphs", {})
    return set(graphs.get("current", []))


def compute_graph_delta(before: set[str], after: set[str]) -> dict:
    """Compare pre- and post-execution graph snapshots.

    Args:
        before: Set of graph names before execution.
        after: Set of graph names after execution.

    Returns:
        Dict with created, dropped, current lists.
    """
    return {
        "created": sorted(after - before),
        "dropped": sorted(before - after),
        "current": sorted(after),
    }


def format_graph_summary(delta: dict) -> str:
    """Format a graph delta dict into a human-readable summary."""
    parts = []
    created = delta.get("created", [])
    dropped = delta.get("dropped", [])
    current = delta.get("current", [])

    if created:
        parts.append(f"Created: {', '.join(created)}")
    if dropped:
        parts.append(f"Dropped: {', '.join(dropped)}")
    if current:
        parts.append(f"Current: {', '.join(current)}")

    return "; ".join(parts) if parts else "No graphs in memory"


_unnamed_counter = 0


def make_export_name(graph_name: str) -> str:
    """Convert a graph name to a safe filename, handling unnamed graphs."""
    global _unnamed_counter
    if graph_name == "Graph":
        _unnamed_counter += 1
        return f"_unnamed{_unnamed_counter}"
    return graph_name

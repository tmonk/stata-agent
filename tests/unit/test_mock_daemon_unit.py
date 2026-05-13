"""Unit tests for mock_backend.py."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from stata_agent.mock_backend import (
    MockDaemon,
    _get_state,
    _load_canned_responses,
    _route_command,
    _session_state,
)


@pytest.fixture(autouse=True)
def _clear_session_state() -> None:
    """Reset global session state before each test."""
    _session_state.clear()


# ---------------------------------------------------------------------------
# _load_canned_responses
# ---------------------------------------------------------------------------


class TestLoadCannedResponses:
    """Tests for the _load_canned_responses helper."""

    def test_load_canned_responses_returns_dict(self) -> None:
        result = _load_canned_responses()
        assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# _route_command
# ---------------------------------------------------------------------------


class TestRouteCommand:
    """Tests for the _route_command helper."""

    def test_route_command_display_returns_ok(self) -> None:
        result = _route_command("display 1+1")
        assert result["ok"] is True
        assert result["rc"] == 0

    def test_route_command_sysuse_auto_populates_state(self) -> None:
        _route_command("sysuse auto")
        state = _get_state()
        assert len(state["dataset"].get("variables", [])) > 0
        assert state["dataset"]["name"] == "auto"


# ---------------------------------------------------------------------------
# MockDaemon.dispatch
# ---------------------------------------------------------------------------


class TestMockDaemon:
    """Unit tests for MockDaemon.dispatch()."""

    def _dispatch(self, daemon: MockDaemon, method: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
        return asyncio.run(daemon.dispatch(method, args or {}))

    # -- health -----------------------------------------------------------

    def test_mock_dispatch_health(self) -> None:
        daemon = MockDaemon()
        result = self._dispatch(daemon, "health")
        assert result["status"] == "running"
        assert "pid" in result

    # -- inspect_describe (empty state) -----------------------------------

    def test_mock_dispatch_inspect_describe_empty_state(self) -> None:
        daemon = MockDaemon()
        result = self._dispatch(daemon, "inspect_describe")
        assert result["variables"] == []
        assert result["var_count"] == 0
        assert result["obs_count"] == 0

    # -- run sysuse auto -> inspect_describe ------------------------------

    def test_mock_dispatch_run_sysuse_populates_state(self) -> None:
        daemon = MockDaemon()
        self._dispatch(daemon, "run", {"code": "sysuse auto"})
        result = self._dispatch(daemon, "inspect_describe")
        assert result["var_count"] > 0
        assert result["dataset"]["name"] == "auto"

    # -- graph_list (empty) -----------------------------------------------

    def test_mock_dispatch_graph_list_empty(self) -> None:
        daemon = MockDaemon()
        result = self._dispatch(daemon, "graph_list")
        assert result["graph_names"] == []

    # -- unknown method ---------------------------------------------------

    def test_mock_dispatch_unknown_method_raises(self) -> None:
        daemon = MockDaemon()
        with pytest.raises(ValueError, match="Unknown method"):
            self._dispatch(daemon, "nonexistent_method")

    # -- break ------------------------------------------------------------

    def test_mock_dispatch_break_returns_acknowledged(self) -> None:
        daemon = MockDaemon()
        result = self._dispatch(daemon, "break")
        assert result["acknowledged"] is True

    # -- task_status ------------------------------------------------------

    def test_mock_dispatch_task_status(self) -> None:
        daemon = MockDaemon()
        result = self._dispatch(daemon, "task_status")
        assert result["status"] == "completed"

    # -- stop -------------------------------------------------------------

    def test_mock_dispatch_stop(self) -> None:
        daemon = MockDaemon()
        result = self._dispatch(daemon, "stop")
        assert result["acknowledged"] is True
        assert daemon._shutdown_event.is_set()

"""Extended unit tests for mock_backend.py covering gaps in existing tests.

Tests _sanitise_out_path, _route_command edge cases, and additional
MockDaemon.dispatch methods beyond what test_mock_daemon_unit.py covers.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from stata_agent.mock_backend import (
    MockDaemon,
    _get_state,
    _load_canned_responses,
    _route_command,
    _sanitise_out_path,
    _session_state,
)


@pytest.fixture(autouse=True)
def _clear_session_state() -> None:
    """Reset global session state before each test."""
    _session_state.clear()


# ---------------------------------------------------------------------------
# _sanitise_out_path
# ---------------------------------------------------------------------------


class TestSanitiseOutPath:
    """Tests for the _sanitise_out_path helper."""

    def test_empty_path_uses_fallback(self) -> None:
        result = _sanitise_out_path("", "test_session")
        assert result.startswith("/tmp/stata-agent-mock/exports/")
        assert "test_session" in result

    def test_normal_path_extracts_basename(self) -> None:
        result = _sanitise_out_path("/some/arbitrary/path/data.csv", "sess")
        assert result.startswith("/tmp/stata-agent-mock/exports/")
        assert result.endswith("data.csv")

    def test_special_chars_replaced_with_underscores(self) -> None:
        result = _sanitise_out_path("bad!name@file.csv", "s")
        assert result.endswith("bad_name_file.csv")

    def test_path_traversal_attempt_stripped(self) -> None:
        result = _sanitise_out_path("../../etc/passwd", "s")
        assert "/etc/" not in result
        assert result.endswith("passwd")
        # The result should be under the safe dir
        assert result.startswith("/tmp/stata-agent-mock/exports/")

    def test_session_name_in_fallback(self) -> None:
        result = _sanitise_out_path("", "my_custom_session")
        assert "my_custom_session" in result
        assert result.endswith(".csv")


# ---------------------------------------------------------------------------
# _route_command — extended edge cases
# ---------------------------------------------------------------------------


class TestRouteCommandExtended:
    """Extended tests for _route_command beyond the basic ones."""

    def test_display_expression(self) -> None:
        result = _route_command("display 2+2")
        assert result["ok"] is True

    def test_di_shortcut(self) -> None:
        result = _route_command("di 3+3")
        assert result["ok"] is True

    def test_generate_command(self) -> None:
        result = _route_command("generate x = 1")
        assert result["ok"] is True

    def test_gen_shortcut(self) -> None:
        result = _route_command("gen y = 2")
        assert result["ok"] is True

    def test_set_more_off(self) -> None:
        result = _route_command("set more off")
        assert result["ok"] is True
        assert result["stdout"] == ""

    def test_set_seed(self) -> None:
        result = _route_command("set seed 12345")
        assert result["ok"] is True

    def test_log_using(self) -> None:
        result = _route_command('log using test.log, replace text')
        assert result["ok"] is True

    def test_log_close(self) -> None:
        result = _route_command("log close")
        assert result["ok"] is True

    def test_graph_dir_empty(self) -> None:
        result = _route_command("graph dir")
        assert result["ok"] is True
        assert result["stdout"] == ""

    def test_graph_export(self) -> None:
        result = _route_command("graph export mygraph.png, replace")
        assert result["ok"] is True

    def test_unknown_command_accepts(self) -> None:
        result = _route_command("some random unknown command")
        assert result["ok"] is True
        assert "some random unknown command" in result["stdout"]

    def test_error_rc_111(self) -> None:
        result = _route_command("error 111")
        assert result["ok"] is False
        assert result["rc"] == 111
        assert "r(111)" in result["stdout"]

    def test_capture_error_111(self) -> None:
        result = _route_command("capture error 111")
        assert result["ok"] is True
        assert result["rc"] == 0

    def test_normalization_whitespace(self) -> None:
        """Extra whitespace is normalized before matching."""
        result = _route_command("  display   1+1  ")
        assert result["ok"] is True
        assert "2" in result["stdout"]

    def test_state_tracks_after_sysuse(self) -> None:
        _route_command("sysuse auto", session="sess1")
        state = _get_state("sess1")
        assert state["dataset"]["name"] == "auto"
        assert len(state["dataset"]["variables"]) == 12

    def test_canned_prefix_match(self) -> None:
        """Commands that start with a canned key should match."""
        result = _route_command("sysuse auto, clear")
        assert result["ok"] is True
        assert "1978 automobile data" in result["stdout"]

    def test_state_isolation(self) -> None:
        """Different sessions have independent state."""
        _route_command("sysuse auto", session="s1")
        _route_command("sysuse auto", session="s2")
        state_s1 = _get_state("s1")
        state_s2 = _get_state("s2")
        assert state_s1 is not state_s2
        assert state_s1["dataset"]["name"] == "auto"
        assert state_s2["dataset"]["name"] == "auto"

    def test_log_path_includes_session(self) -> None:
        result = _route_command("display 1+1", session="my_session")
        assert "my_session" in result["log_path"]


# ---------------------------------------------------------------------------
# MockDaemon.dispatch — extended coverage
# ---------------------------------------------------------------------------


class TestMockDaemonExtended:
    """Extended unit tests for MockDaemon.dispatch() methods."""

    def _dispatch(self, daemon: MockDaemon, method: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
        return asyncio.run(daemon.dispatch(method, args or {}))

    # -- run_file failure patterns ----------------------------------------

    def test_run_file_assert_scalar_fail(self) -> None:
        """run_file with a filename containing fail_assert_scalar_fail returns failure."""
        daemon = MockDaemon()
        result = self._dispatch(daemon, "run_file", {"path": "/tmp/fail_assert_scalar_fail.do"})
        assert result["ok"] is False
        assert result["rc"] == 9

    def test_run_file_assert_macro_fail(self) -> None:
        daemon = MockDaemon()
        result = self._dispatch(daemon, "run_file", {"path": "/tmp/fail_assert_macro_fail.do"})
        assert result["ok"] is False

    def test_run_file_assert_matrix_fail(self) -> None:
        daemon = MockDaemon()
        result = self._dispatch(daemon, "run_file", {"path": "/tmp/fail_assert_matrix_fail.do"})
        assert result["ok"] is False

    def test_run_file_assert_rc_fail(self) -> None:
        daemon = MockDaemon()
        result = self._dispatch(daemon, "run_file", {"path": "/tmp/fail_assert_rc_fail.do"})
        assert result["ok"] is False

    def test_run_file_failure_capture(self) -> None:
        daemon = MockDaemon()
        result = self._dispatch(daemon, "run_file", {"path": "/tmp/fail_failure_capture.do"})
        assert result["ok"] is False

    def test_run_file_teardown_on_fail(self) -> None:
        daemon = MockDaemon()
        result = self._dispatch(daemon, "run_file", {"path": "/tmp/fail_teardown_runs_on_fail.do"})
        assert result["ok"] is False

    def test_run_file_normal_passthrough(self) -> None:
        """A normal file path (no failure pattern) returns ok."""
        daemon = MockDaemon()
        result = self._dispatch(daemon, "run_file", {"path": "/tmp/some_test.do"})
        assert result["ok"] is True

    # -- results with statest scalars -------------------------------------

    def test_results_with_statest_scalars(self) -> None:
        """After a failing run_file, results() should include statest scalars."""
        daemon = MockDaemon()
        self._dispatch(daemon, "run_file", {"path": "/tmp/fail_assert_scalar_fail.do"})
        result = self._dispatch(daemon, "results", {"class": "r"})
        stored = result.get("stored_results", {})
        scalars = stored.get("scalars", {})
        assert scalars.get("statest_assertion_index") == 1.0

    def test_results_empty_without_run_file(self) -> None:
        """results() returns empty when no statest scalars are stored."""
        daemon = MockDaemon()
        result = self._dispatch(daemon, "results", {"class": "r"})
        assert result.get("stored_results", {}) == {}

    # -- inspect_codebook -------------------------------------------------

    def test_inspect_codebook(self) -> None:
        daemon = MockDaemon()
        result = self._dispatch(daemon, "inspect_codebook", {"varlist": "price"})
        assert "text" in result

    # -- inspect_get with path sanitization --------------------------------

    def test_inspect_get_empty_out_path(self) -> None:
        daemon = MockDaemon()
        result = self._dispatch(daemon, "inspect_get", {"format": "csv"})
        assert "path" in result
        # Should fall under the safe temp directory
        assert result["path"].startswith("/tmp/stata-agent-mock/")

    def test_inspect_get_sanitises_path(self) -> None:
        """out_path with special chars is sanitised."""
        daemon = MockDaemon()
        result = self._dispatch(daemon, "inspect_get", {
            "format": "csv", "out_path": "../../../evil.sh",
        })
        assert "evil.sh" in result["path"]
        # Should not escape the safe dir
        assert result["path"].startswith("/tmp/stata-agent-mock/")

    def test_inspect_get_size_bytes(self) -> None:
        daemon = MockDaemon()
        result = self._dispatch(daemon, "inspect_get", {"format": "csv"})
        assert result.get("size_bytes", 0) > 0

    # -- graph_export without out_path ------------------------------------

    def test_graph_export_no_out_path(self) -> None:
        daemon = MockDaemon()
        result = self._dispatch(daemon, "graph_export", {
            "name": "mygraph", "format": "png",
        })
        assert "file_path" in result
        assert "mygraph" in result["file_path"]

    # -- run background ---------------------------------------------------

    def test_run_background(self) -> None:
        daemon = MockDaemon()
        result = self._dispatch(daemon, "run", {
            "code": "display 1+1", "background": True,
        })
        assert "task_id" in result
        assert result["status"] == "running"

    # -- break returns acknowledged ---------------------------------------

    def test_break_with_session_state(self) -> None:
        daemon = MockDaemon()
        self._dispatch(daemon, "run", {"code": "sysuse auto"})
        result = self._dispatch(daemon, "break", {})
        assert result["acknowledged"] is True
        assert "worker_restarted" in result

    # -- health -----------------------------------------------------------

    def test_health_after_sysuse(self) -> None:
        daemon = MockDaemon()
        self._dispatch(daemon, "run", {"code": "sysuse auto"})
        result = self._dispatch(daemon, "health", {})
        assert result["status"] == "ok"
        assert result["session_name"] == daemon.session_name

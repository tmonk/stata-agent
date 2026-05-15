"""Unit tests for worker.py — no real Stata needed.

Tests the _dispatch routing function and _result_to_dict helper.
_worker_main is tested indirectly via integration tests.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from stata_agent.models import RunResult
from stata_agent.worker import _dispatch, _result_to_dict


# ---------------------------------------------------------------------------
# _result_to_dict
# ---------------------------------------------------------------------------


class TestResultToDict:
    """Tests for the _result_to_dict helper."""

    def test_basic_run_result(self) -> None:
        r = RunResult(ok=True, rc=0, stdout=". display 1+1\n2\n", log_path="/tmp/test.log")
        d = _result_to_dict(r)
        assert d["ok"] is True
        assert d["rc"] == 0
        assert d["stdout"] == ". display 1+1\n2\n"
        assert d["log_path"] == "/tmp/test.log"
        assert d["graphs"] is None
        assert d["truncated"] is False

    def test_error_result(self) -> None:
        r = RunResult(ok=False, rc=111, stdout=". error 111\nr(111);\n", log_path="/tmp/test.log")
        d = _result_to_dict(r)
        assert d["ok"] is False
        assert d["rc"] == 111

    def test_with_graph_delta(self) -> None:
        from stata_agent.models import GraphDelta
        graphs = GraphDelta(created=["graph1"], current=["graph1"])
        r = RunResult(ok=True, rc=0, stdout="", graphs=graphs)
        d = _result_to_dict(r)
        assert d["graphs"] is graphs
        assert d["graphs"].created == ["graph1"]

    def test_truncated_output(self) -> None:
        r = RunResult(ok=True, rc=0, stdout="lots of output", truncated=True)
        d = _result_to_dict(r)
        assert d["truncated"] is True


# ---------------------------------------------------------------------------
# _dispatch — method routing
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_stata() -> MagicMock:
    """Create a mock StataClient with all inspect methods returning dicts."""
    stata = MagicMock()
    stata.run.return_value = RunResult(ok=True, rc=0, stdout="hello")
    stata.run_file.return_value = RunResult(ok=True, rc=0, stdout="file ran")
    stata.inspect_describe.return_value = {"text": "", "variables": [], "obs_count": 0}
    stata.inspect_summary.return_value = {"text": ""}
    stata.inspect_codebook.return_value = {"text": ""}
    stata.inspect_list.return_value = {"text": "", "rows": [], "total_obs": 0}
    stata.inspect_get.return_value = {"path": "/tmp/export.csv", "size_bytes": 100}
    stata.get_results.return_value = {"stored_results": {}}
    stata.snapshot_graphs.return_value = []
    stata.export_graph.return_value = {"file_path": "/tmp/g.pdf", "size_bytes": 0}
    stata.read_log_tail.return_value = "log line 1\nlog line 2\n"
    stata.get_log_errors.return_value = {"rc": None, "message": "", "context": ""}
    stata.session_name = "test_session"
    return stata


class TestDispatch:
    """Tests for the _dispatch routing function."""

    def test_run(self, mock_stata: MagicMock) -> None:
        result = _dispatch(mock_stata, "run", {"code": "display 1+1", "echo": False})
        assert result["ok"] is True
        mock_stata.run.assert_called_once_with(
            "display 1+1",
            echo=False,
            max_output_tokens=1000,
            strict=False,
            pre_allocated_log=None,
            track_graphs=False,
        )

    def test_run_with_all_options(self, mock_stata: MagicMock) -> None:
        _dispatch(mock_stata, "run", {
            "code": "sysuse auto",
            "echo": True,
            "max_output_tokens": 500,
            "strict": True,
            "pre_allocated_log": "/tmp/prealloc.log",
            "track_graphs": True,
        })
        mock_stata.run.assert_called_once_with(
            "sysuse auto",
            echo=True,
            max_output_tokens=500,
            strict=True,
            pre_allocated_log="/tmp/prealloc.log",
            track_graphs=True,
        )

    def test_run_file(self, mock_stata: MagicMock) -> None:
        result = _dispatch(mock_stata, "run_file", {"path": "/tmp/test.do"})
        assert result["ok"] is True
        mock_stata.run_file.assert_called_once_with(
            "/tmp/test.do",
            echo=True,
            strict=False,
            track_graphs=False,
        )

    def test_run_file_with_options(self, mock_stata: MagicMock) -> None:
        _dispatch(mock_stata, "run_file", {
            "path": "/tmp/test.do",
            "echo": False,
            "strict": True,
            "track_graphs": True,
        })
        mock_stata.run_file.assert_called_once_with(
            "/tmp/test.do",
            echo=False,
            strict=True,
            track_graphs=True,
        )

    def test_inspect_describe(self, mock_stata: MagicMock) -> None:
        result = _dispatch(mock_stata, "inspect_describe", {"varlist": "price mpg"})
        assert isinstance(result, dict)
        mock_stata.inspect_describe.assert_called_once_with(
            varlist="price mpg", fullnames=False,
        )

    def test_inspect_describe_fullnames(self, mock_stata: MagicMock) -> None:
        _dispatch(mock_stata, "inspect_describe", {"varlist": "price", "fullnames": True})
        mock_stata.inspect_describe.assert_called_once_with(
            varlist="price", fullnames=True,
        )

    def test_inspect_summary(self, mock_stata: MagicMock) -> None:
        result = _dispatch(mock_stata, "inspect_summary", {"varlist": "price mpg"})
        assert isinstance(result, dict)
        mock_stata.inspect_summary.assert_called_once_with(varlist="price mpg")

    def test_inspect_codebook(self, mock_stata: MagicMock) -> None:
        result = _dispatch(mock_stata, "inspect_codebook", {"varlist": "foreign"})
        assert isinstance(result, dict)
        mock_stata.inspect_codebook.assert_called_once_with(varlist="foreign")

    def test_inspect_list(self, mock_stata: MagicMock) -> None:
        result = _dispatch(mock_stata, "inspect_list", {
            "varlist": "price mpg", "from": 0, "count": 10,
        })
        assert isinstance(result, dict)
        mock_stata.inspect_list.assert_called_once_with(
            varlist="price mpg", from_row=0, count=10,
        )

    def test_inspect_get(self, mock_stata: MagicMock) -> None:
        result = _dispatch(mock_stata, "inspect_get", {
            "format": "csv", "out_path": "/tmp/export.csv",
        })
        assert isinstance(result, dict)
        mock_stata.inspect_get.assert_called_once_with(
            format="csv", out_path="/tmp/export.csv",
            varlist=None, obs_range=None,
        )

    def test_results(self, mock_stata: MagicMock) -> None:
        result = _dispatch(mock_stata, "results", {"class": "e"})
        assert isinstance(result, dict)
        mock_stata.get_results.assert_called_once_with(result_class="e")

    def test_graph_list(self, mock_stata: MagicMock) -> None:
        mock_stata.snapshot_graphs.return_value = ["graph1", "graph2"]
        result = _dispatch(mock_stata, "graph_list", {})
        assert result["graph_names"] == ["graph1", "graph2"]

    def test_graph_export(self, mock_stata: MagicMock) -> None:
        result = _dispatch(mock_stata, "graph_export", {
            "name": "mygraph", "format": "png", "out_path": "/tmp/g.png",
        })
        assert isinstance(result, dict)
        mock_stata.export_graph.assert_called_once_with(
            name="mygraph", fmt="png", out_path="/tmp/g.png",
        )

    def test_log_tail(self, mock_stata: MagicMock) -> None:
        result = _dispatch(mock_stata, "log_tail", {"lines": 20, "bytes": 1024})
        assert result["text"] == "log line 1\nlog line 2\n"
        mock_stata.read_log_tail.assert_called_once_with(lines=20, bytes=1024)

    def test_log_errors(self, mock_stata: MagicMock) -> None:
        result = _dispatch(mock_stata, "log_errors", {"context_lines": 30})
        assert isinstance(result, dict)
        mock_stata.get_log_errors.assert_called_once_with(context_lines=30)

    def test_health(self, mock_stata: MagicMock) -> None:
        result = _dispatch(mock_stata, "health", {})
        assert result["status"] == "ok"
        assert result["pid"] > 0
        assert result["session"] == "test_session"

    def test_unknown_method_raises(self, mock_stata: MagicMock) -> None:
        with pytest.raises(ValueError, match="Unknown method: nonexistent"):
            _dispatch(mock_stata, "nonexistent", {})

    def test_run_error_raised_as_exception(self, mock_stata: MagicMock) -> None:
        mock_stata.run.side_effect = RuntimeError("Stata crashed")
        with pytest.raises(RuntimeError, match="Stata crashed"):
            _dispatch(mock_stata, "run", {"code": "crash"})

    def test_run_file_error(self, mock_stata: MagicMock) -> None:
        mock_stata.run_file.side_effect = RuntimeError("File not found")
        with pytest.raises(RuntimeError, match="File not found"):
            _dispatch(mock_stata, "run_file", {"path": "nonexistent.do"})

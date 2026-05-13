"""Integration tests for the stata-agent mock daemon.

These tests start a mock daemon in-process and exercise the full
RPC protocol end-to-end.
"""

from __future__ import annotations

import asyncio
import os
import threading
import time
from pathlib import Path

import pytest

from stata_agent.rpc_client import RpcClient, RpcError


@pytest.fixture(scope="module")
def mock_daemon():
    """Start a mock daemon and return an RPC client."""
    os.environ["STATA_AGENT_MOCK"] = "1"

    from stata_agent.mock_backend import MockDaemon

    daemon = MockDaemon(session_name="integration_test")

    def _start():
        asyncio.run(daemon.start())

    t = threading.Thread(target=_start, daemon=True)
    t.start()

    # Wait for socket to appear (up to 10 seconds)
    sock_path = Path.home() / ".cache" / "stata-agent" / "sessions" / "integration_test.sock"
    for _ in range(100):
        if sock_path.exists():
            break
        time.sleep(0.1)

    if not sock_path.exists():
        pytest.fail("Mock daemon failed to start within 10 seconds")

    time.sleep(0.3)
    client = RpcClient(session="integration_test")

    yield client

    # Clean up
    try:
        client.call("stop", {})
    except Exception:
        pass
    sock_path.unlink(missing_ok=True)
    meta_path = Path.home() / ".cache" / "stata-agent" / "sessions" / "integration_test.json"
    meta_path.unlink(missing_ok=True)


class TestHealth:
    def test_daemon_health(self, mock_daemon: RpcClient):
        result = mock_daemon.call("health", {})
        assert result.get("status") == "running"
        assert result.get("pid", 0) > 0
        assert result.get("session_name") == "integration_test"


class TestRun:
    def test_display_1plus1(self, mock_daemon: RpcClient):
        result = mock_daemon.call("run", {"code": "display 1+1", "echo": False})
        assert result.get("ok") is True
        assert result.get("rc") == 0
        stdout = result.get("stdout", "")
        assert "2" in stdout

    def test_sysuse_auto(self, mock_daemon: RpcClient):
        result = mock_daemon.call("run", {"code": "sysuse auto", "echo": False})
        assert result.get("ok") is True
        stdout = result.get("stdout", "")
        assert "1978 automobile data" in stdout

    def test_reg_price_mpg(self, mock_daemon: RpcClient):
        mock_daemon.call("run", {"code": "sysuse auto", "echo": False})
        result = mock_daemon.call("run", {"code": "reg price mpg", "echo": False})
        assert result.get("ok") is True
        assert result.get("rc") == 0
        assert result.get("log_path") is not None

    def test_background_run(self, mock_daemon: RpcClient):
        result = mock_daemon.call("run", {
            "code": "display 1+1",
            "echo": False,
            "background": True,
        })
        assert "task_id" in result
        assert result.get("status") == "running"

    def test_error_response(self, mock_daemon: RpcClient):
        result = mock_daemon.call("run", {"code": "error 111", "echo": False})
        assert result.get("rc") == 111


class TestGraph:
    def test_graph_list_empty(self, mock_daemon: RpcClient):
        result = mock_daemon.call("graph_list", {})
        assert "graph_names" in result
        assert result["graph_names"] == []

    def test_graph_export(self, mock_daemon: RpcClient):
        result = mock_daemon.call("graph_export", {
            "name": "test_graph",
            "format": "pdf",
            "out_path": "/tmp/test_graph.pdf",
        })
        assert "file_path" in result
        assert "size_bytes" in result


class TestInspect:
    def test_describe(self, mock_daemon: RpcClient):
        mock_daemon.call("run", {"code": "sysuse auto", "echo": False})
        result = mock_daemon.call("inspect_describe", {})
        assert result.get("var_count", 0) > 0
        assert len(result.get("variables", [])) > 0

    def test_summary(self, mock_daemon: RpcClient):
        result = mock_daemon.call("inspect_summary", {"varlist": ""})
        assert "text" in result

    def test_list_data(self, mock_daemon: RpcClient):
        result = mock_daemon.call("inspect_list", {})
        assert "text" in result

    def test_get_data(self, mock_daemon: RpcClient):
        result = mock_daemon.call("inspect_get", {
            "format": "csv",
            "out_path": "/tmp/test_export.csv",
        })
        assert result.get("path") is not None
        assert "size_bytes" in result


class TestResults:
    def test_results(self, mock_daemon: RpcClient):
        result = mock_daemon.call("results", {"class": "r"})
        assert "stored_results" in result


class TestLog:
    def test_log_tail(self, mock_daemon: RpcClient):
        result = mock_daemon.call("log_tail", {"lines": 10})
        assert "text" in result

    def test_log_search(self, mock_daemon: RpcClient):
        result = mock_daemon.call("log_search", {
            "pattern": "error",
            "max_bytes": 65536,
        })
        assert "matches" in result

    def test_log_errors(self, mock_daemon: RpcClient):
        result = mock_daemon.call("log_errors", {"context_lines": 10})
        assert "rc" in result

    def test_log_path(self, mock_daemon: RpcClient):
        result = mock_daemon.call("log_path", {})
        assert "log_path" in result


class TestBreak:
    def test_break(self, mock_daemon: RpcClient):
        result = mock_daemon.call("break", {})
        assert result.get("acknowledged") is True

    def test_break_restarts_worker(self, mock_daemon: RpcClient):
        mock_daemon.call("run", {"code": "display 1+1", "echo": False})
        mock_daemon.call("break", {})
        result = mock_daemon.call("run", {"code": "display 2+2", "echo": False})
        assert result.get("ok") is True


class TestTask:
    def test_task_status(self, mock_daemon: RpcClient):
        result = mock_daemon.call("task_status", {"task_id": "test_task_1"})
        assert "status" in result

    def test_task_cancel(self, mock_daemon: RpcClient):
        result = mock_daemon.call("task_cancel", {"task_id": "test_task_1"})
        assert result.get("cancelled") is True

    def test_task_list(self, mock_daemon: RpcClient):
        result = mock_daemon.call("task_list", {})
        assert "tasks" in result


class TestHelp:
    def test_help(self, mock_daemon: RpcClient):
        result = mock_daemon.call("help", {"topic": "regress"})
        assert "text" in result
        assert "regress" in result["text"]


class TestRunFile:
    def test_run_file(self, mock_daemon: RpcClient):
        result = mock_daemon.call("run_file", {"path": "/tmp/test.do"})
        assert "ok" in result

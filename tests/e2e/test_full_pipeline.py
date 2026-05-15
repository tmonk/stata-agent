"""End-to-end tests: full pipeline with real Stata.

These tests exercise the complete data flow:
  StataClient (direct) → Stata daemon (as subprocess) → RPC → results

Requires a licensed Stata installation. Skipped automatically when
Stata is not available or STATA_AGENT_MOCK=1 is set.
"""

from __future__ import annotations

import asyncio
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest

from stata_agent.rpc_client import RpcClient


# ---------------------------------------------------------------------------
# Fixture: StataClient (direct, no daemon) for basic Stata operations
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def stata_client():
    """Create a StataClient with real Stata, yield it, then close."""
    import sys

    root = os.environ.get("STATA_PATH", "/Applications/StataNow")
    edition = "se"

    from pystata_x.stata_setup import config as px_setup_config
    px_setup_config(root, edition, splash=False)

    from stata_agent.stata_client import StataClient

    client = StataClient()
    client.init()
    yield client
    client.close()


# ---------------------------------------------------------------------------
# Fixture: Real daemon subprocess (Unix domain socket / TCP)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def daemon_rpc_client():
    """Start a real Stata daemon as a subprocess and return an RPC client.

    Falls back to mock daemon if STATA_AGENT_MOCK=1 is set externally.
    """
    session_name = "e2e_test"
    cache_dir = Path.home() / ".cache" / "stata-agent" / "sessions"
    cache_dir.mkdir(parents=True, exist_ok=True)

    import sys as _sys

    proc = subprocess.Popen(
        [_sys.executable, "-m", "stata_agent", "daemon", "start",
         "--session", session_name],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env={**os.environ, "STATA_AGENT_MOCK": "0"},
    )

    # Wait for the daemon to write its meta file
    meta_path = cache_dir / f"{session_name}.json"
    for _ in range(200):
        if meta_path.exists():
            break
        time.sleep(0.1)
    else:
        proc.terminate()
        pytest.fail("Daemon did not start within 20 seconds")

    time.sleep(0.5)

    meta = json.loads(meta_path.read_text())
    client = RpcClient(session=session_name)

    yield client

    # Cleanup: stop daemon
    try:
        client.call("stop", {})
    except Exception:
        pass
    proc.terminate()
    proc.wait(timeout=5)
    meta_path.unlink(missing_ok=True)
    sock_path = cache_dir / f"{session_name}.sock"
    sock_path.unlink(missing_ok=True)


# ===========================================================================
# E2E tests — StataClient direct (no daemon overhead)
# ===========================================================================


class TestStataClientDirect:
    """Direct StataClient tests — exercises the core execution pipeline."""

    @pytest.mark.requires_stata
    def test_run_simple_expression(self, stata_client) -> None:
        """run() should return correct output for simple expressions."""
        result = stata_client.run("display 1+1", echo=False)
        assert result.ok is True
        assert result.rc == 0
        assert "2" in result.stdout

    @pytest.mark.requires_stata
    def test_run_dataset_operations(self, stata_client) -> None:
        """Full dataset pipeline: sysuse, describe, summarize, regression."""
        stata_client.run("sysuse auto, clear", echo=False)

        # Describe
        result = stata_client.run("describe", echo=False)
        assert result.ok is True
        assert "74" in result.stdout  # 74 observations
        assert "12" in result.stdout or "variables" in result.stdout

        # Summarize
        result = stata_client.run("summarize price mpg", echo=False)
        assert result.ok is True
        assert "6165.257" in result.stdout  # mean of price

        # Regression
        result = stata_client.run("regress price mpg", echo=False)
        assert result.ok is True
        assert "R-squared" in result.stdout

    @pytest.mark.requires_stata
    def test_run_file_do(self, stata_client) -> None:
        """run_file() should execute a .do file and return results."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".do", delete=False) as f:
            f.write('display "Running do-file"\n')
            f.write('display 1+1\n')
            f.write('display "Done"\n')
            do_path = f.name

        try:
            result = stata_client.run_file(do_path, echo=False)
            assert result.ok is True
            assert result.rc == 0
            assert "Running do-file" in result.stdout
            assert "2" in result.stdout
        finally:
            os.unlink(do_path)

    @pytest.mark.requires_stata
    def test_inspect_describe(self, stata_client) -> None:
        """inspect_describe should return variable metadata."""
        stata_client.run("sysuse auto, clear", echo=False)
        result = stata_client.inspect_describe(varlist=None)
        assert isinstance(result, dict)
        assert len(result.get("variables", [])) > 0

    @pytest.mark.requires_stata
    def test_inspect_summary(self, stata_client) -> None:
        """inspect_summary should return summary statistics."""
        stata_client.run("sysuse auto, clear", echo=False)
        result = stata_client.inspect_summary(varlist="price mpg")
        assert isinstance(result, dict)
        assert "text" in result

    @pytest.mark.requires_stata
    def test_inspect_list(self, stata_client) -> None:
        """inspect_list should return a dict with text field."""
        stata_client.run("sysuse auto, clear", echo=False)
        result = stata_client.inspect_list(varlist="price mpg", count=5)
        assert isinstance(result, dict)
        assert "text" in result

    @pytest.mark.requires_stata
    def test_results_r_class(self, stata_client) -> None:
        """results() should return stored results after a command."""
        stata_client.run("summarize price", echo=False)
        result = stata_client.get_results(result_class="r")
        assert isinstance(result, dict)
        assert "stored_results" in result or "log" in result

    @pytest.mark.requires_stata
    def test_error_handling(self, stata_client) -> None:
        """Error commands should return ok=False with correct rc."""
        result = stata_client.run("error 111", echo=False)
        assert result.ok is False
        assert result.rc == 111
        assert "r(111)" in result.stdout

    @pytest.mark.requires_stata
    def test_log_tail(self, stata_client) -> None:
        """read_log_tail should return recent log output."""
        result = stata_client.read_log_tail(lines=20)
        assert isinstance(result, str)
        assert len(result) > 0


# ===========================================================================
# E2E tests — Daemon pipeline (via CLI subprocess)
# ===========================================================================


class TestDaemonPipeline:
    """Full daemon pipeline: start → RPC → run → results → stop.

    These tests start a real Stata daemon subprocess and exercise the
    entire RPC protocol end-to-end with a real Stata backend.
    """

    @pytest.mark.requires_stata
    def test_daemon_health(self, daemon_rpc_client: RpcClient) -> None:
        """Daemon health endpoint should report ok."""
        result = daemon_rpc_client.call("health", {})
        assert result.get("status") == "ok"
        assert "pid" in result

    @pytest.mark.requires_stata
    def test_daemon_run_foreground(self, daemon_rpc_client: RpcClient) -> None:
        """Run a simple command through the daemon and get results."""
        result = daemon_rpc_client.call("run", {"code": "display 1+1", "echo": False})
        assert result.get("ok") is True
        assert result.get("rc") == 0
        stdout = result.get("stdout", "")
        assert "2" in stdout

    @pytest.mark.requires_stata
    def test_daemon_run_and_inspect(self, daemon_rpc_client: RpcClient) -> None:
        """Run sysuse then inspect through the daemon."""
        daemon_rpc_client.call("run", {"code": "sysuse auto, clear", "echo": False})
        result = daemon_rpc_client.call("inspect_describe", {})
        assert "variables" in result
        assert result.get("var_count", 0) > 0

    @pytest.mark.requires_stata
    def test_daemon_regression(self, daemon_rpc_client: RpcClient) -> None:
        """Full regression pipeline through the daemon."""
        daemon_rpc_client.call("run", {"code": "sysuse auto, clear", "echo": False})
        result = daemon_rpc_client.call("run", {"code": "regress price mpg", "echo": False})
        assert result.get("ok") is True
        assert "R-squared" in result.get("stdout", "")

    @pytest.mark.requires_stata
    def test_daemon_error_handling(self, daemon_rpc_client: RpcClient) -> None:
        """Error commands through the daemon should return error details."""
        result = daemon_rpc_client.call("run", {"code": "error 111", "echo": False})
        assert result.get("rc") == 111
        assert result.get("ok") is False

    @pytest.mark.requires_stata
    def test_daemon_break_and_continue(self, daemon_rpc_client: RpcClient) -> None:
        """Break and continue works through the daemon."""
        daemon_rpc_client.call("run", {"code": "display 1+1", "echo": False})
        daemon_rpc_client.call("break", {})
        result = daemon_rpc_client.call("run", {"code": "display 2+2", "echo": False})
        assert result.get("ok") is True
        assert "4" in result.get("stdout", "")

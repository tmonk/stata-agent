"""Benchmarks: CLI-Daemon lifecycle and RPC communication.

Exercises: daemon start, daemon health check, RPC call overhead,
JSON serialization/deserialization on a **real** daemon + worker stack.

Requires a licensed Stata installation (auto-skipped otherwise).
"""

from __future__ import annotations

import json
import os
import sys
import time
import uuid
from pathlib import Path

import pytest


@pytest.mark.requires_stata
class TestDaemonLifecycleBenchmarks:
    """Benchmark daemon lifecycle and RPC using real daemon + worker."""

    @pytest.fixture(scope="class")
    def real_daemon(self, tmp_path_factory):
        """Start a real Stata daemon + worker for benchmarking.

        This starts the actual production daemon, which spawns a worker
        subprocess that initialises Stata via pystata-x.
        """
        import subprocess
        cache_dir = Path.home() / ".cache" / "stata-agent" / "sessions"
        cache_dir.mkdir(parents=True, exist_ok=True)

        session = f"benchmark-daemon-{uuid.uuid4().hex[:8]}"
        sock_path = cache_dir / f"{session}.sock"

        # Start the real daemon
        proc = subprocess.Popen(
            [sys.executable, "-m", "stata_agent.daemon", "--session", session],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )

        # Wait for socket
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if sock_path.exists():
                break
            time.sleep(0.2)
        else:
            proc.terminate()
            proc.wait(timeout=5)
            pytest.fail("Daemon did not start within 30s")

        time.sleep(2)  # extra settle time for worker init (pystata-x ~2s)

        from stata_agent.rpc_client import RpcClient
        client = RpcClient(session=session)

        yield client, session

        # Cleanup
        try:
            client.call("stop", {"session": session})
        except Exception:
            pass
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()
        sock_path.unlink(missing_ok=True)
        (cache_dir / f"{session}.json").unlink(missing_ok=True)

    @pytest.mark.benchmark(min_rounds=5, warmup=True)
    def test_daemon_health_check(self, real_daemon, benchmark):
        """Benchmark a single RPC health check call."""
        client, session = real_daemon

        def _health():
            return client.call("health", {})

        result = benchmark(_health)
        assert result.get("status") == "ok"

    @pytest.mark.benchmark(min_rounds=5, warmup=True)
    def test_daemon_run_simple(self, real_daemon, benchmark):
        """Benchmark running a simple command through the daemon."""
        client, session = real_daemon

        def _run():
            return client.call("run", {
                "code": "display 1+1",
                "echo": True,
                "max_output_tokens": 1000,
            })

        result = benchmark(_run)
        assert result.get("ok") is True

    @pytest.mark.benchmark(min_rounds=3, warmup=True)
    def test_daemon_run_multiline(self, real_daemon, benchmark):
        """Benchmark multi-line code through the daemon."""
        client, session = real_daemon
        code = (
            'sysuse auto, clear\n'
            'regress price mpg weight\n'
            'predict pred\n'
        )

        def _run():
            return client.call("run", {
                "code": code,
                "echo": False,
                "max_output_tokens": 1000,
            })

        result = benchmark(_run)
        assert result.get("ok") is True

    # --- Pure JSON serialization (no daemon needed) ---

    @pytest.mark.benchmark(min_rounds=10, warmup=True)
    def test_rpc_json_serialization(self, benchmark):
        """Benchmark JSON serialization of a typical RPC request/response."""
        request = {
            "id": uuid.uuid4().hex,
            "method": "run",
            "args": {
                "code": "display 1+1",
                "echo": True,
            },
        }
        response = {
            "id": request["id"],
            "ok": True,
            "result": {
                "ok": True,
                "rc": 0,
                "stdout": ". display 1+1\n2\n",
                "log_path": "/tmp/mock.log",
                "graphs": {"created": [], "dropped": [], "current": []},
                "truncated": False,
            },
        }

        def _serialize():
            req_bytes = json.dumps(request).encode("utf-8")
            resp = json.loads(json.dumps(response))
            return req_bytes, resp

        req_bytes, resp = benchmark(_serialize)
        assert isinstance(req_bytes, bytes)
        assert resp["ok"]

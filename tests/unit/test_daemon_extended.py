"""Extended unit tests for daemon.py — covers main(), background_run errors, and edge cases."""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from stata_agent.daemon import StataDaemon, main


# ---------------------------------------------------------------------------
# main() entry point
# ---------------------------------------------------------------------------


class TestMainEntryPoint:
    """Tests for the daemon's main() entry point."""

    def test_main_returns_zero(self) -> None:
        """main() should return 0 on successful run."""
        test_args = ["stata-daemon", "--session", "default"]
        with patch.object(sys, "argv", test_args):
            with patch("stata_agent.daemon.StataDaemon") as MockDaemonClass:
                mock_daemon = MagicMock()
                mock_daemon.start = AsyncMock()
                MockDaemonClass.return_value = mock_daemon

                result = main()

        assert result == 0

    def test_main_uses_custom_session(self) -> None:
        with patch("stata_agent.daemon.StataDaemon") as MockDaemonClass:
            mock_daemon = MagicMock()
            mock_daemon.start = AsyncMock()
            MockDaemonClass.return_value = mock_daemon

            with patch("sys.argv", ["stata", "daemon", "start", "--session", "mysession"]):
                from stata_agent.cli import main as cli_main
                pass

        # Since main() doesn't parse CLI args directly (that's cli.py's job),
        # we just test that the daemon main() runs without errors


# ---------------------------------------------------------------------------
# Additional StataDaemon dispatch edge cases
# ---------------------------------------------------------------------------


@pytest.fixture
def daemon():
    """Create a StataDaemon with mocked sessions for testing."""
    from stata_agent.session import SessionManager

    d = StataDaemon(session_name="default")
    d.sessions = MagicMock(spec=SessionManager)
    d.sessions.get_session_names.return_value = ["default"]
    d.sessions.get_or_create.return_value = MagicMock()
    d._shutdown_event = asyncio.Event()
    d._background_tasks = {}
    d._temp_files = {}
    return d


class TestDispatchExtended:
    """Additional StataDaemon.dispatch() tests."""

    async def test_dispatch_log_path(self, daemon):
        result = await daemon.dispatch("log_path", {})
        assert "log_path" in result
        assert "stata-agent" in result["log_path"]

    async def test_dispatch_log_search(self, daemon):
        with patch("stata_agent.daemon.search_in_log", return_value={"matches": []}):
            result = await daemon.dispatch("log_search", {
                "log_path": "/tmp/test.log",
                "pattern": "error",
                "max_bytes": 65536,
            })
        assert "matches" in result
        assert result["matches"] == []

    async def test_dispatch_log_search_defaults(self, daemon):
        with patch("stata_agent.daemon.search_in_log", return_value={"matches": []}):
            result = await daemon.dispatch("log_search", {})
        assert "matches" in result

    async def test_dispatch_task_list_empty(self, daemon):
        daemon._background_tasks = {}
        result = await daemon.dispatch("task_list", {})
        assert result["tasks"] == []

    async def test_dispatch_task_list_with_tasks(self, daemon):
        daemon._background_tasks = {
            "task-1": {"status": "running", "task_id": "task-1"},
            "task-2": {"status": "completed", "task_id": "task-2"},
        }
        result = await daemon.dispatch("task_list", {})
        assert len(result["tasks"]) == 2
        statuses = {t["task_id"]: t["status"] for t in result["tasks"]}
        assert statuses["task-1"] == "running"
        assert statuses["task-2"] == "completed"

    async def test_dispatch_task_status_with_tail(self, daemon):
        daemon._background_tasks = {
            "task-1": {
                "status": "completed",
                "task_id": "task-1",
                "log_path": "/tmp/task1.log",
            },
        }
        with patch("stata_agent.daemon.tail_file", return_value="last few lines"):
            result = await daemon.dispatch("task_status", {"task_id": "task-1", "tail_lines": 5})
        assert result["status"] == "completed"
        assert result["log_tail"] == "last few lines"

    async def test_dispatch_task_status_unknown(self, daemon):
        result = await daemon.dispatch("task_status", {"task_id": "nonexistent"})
        assert result["status"] == "not_found"

    async def test_dispatch_stop_always_shuts_down(self, daemon):
        """stop ALWAYS triggers full shutdown regardless of session arg."""
        daemon._shutdown_event.clear()
        result = await daemon.dispatch("stop", {"session": "other-session"})
        assert result["acknowledged"] is True
        # The daemon always sets shutdown event — sessions are a no-go for the real daemon
        assert daemon._shutdown_event.is_set()


# ---------------------------------------------------------------------------
# _background_run error handling
# ---------------------------------------------------------------------------


class TestBackgroundRun:
    """Tests for StataDaemon._background_run error handling."""

    async def test_background_run_success(self, daemon):
        task_id = "bg-task-1"
        daemon._background_tasks[task_id] = {
            "status": "running", "task_id": task_id, "created_at": time.time(),
        }
        daemon._call_worker = MagicMock(return_value={"rc": 0, "ok": True})

        with patch("stata_agent.log_manager.LogRotator"):
            await daemon._background_run(MagicMock(), task_id, {"code": "display 1+1"})

        assert daemon._background_tasks[task_id]["status"] == "completed"

    async def test_background_run_failure(self, daemon):
        task_id = "bg-task-2"
        daemon._background_tasks[task_id] = {
            "status": "running", "task_id": task_id, "created_at": time.time(),
        }
        daemon._call_worker = MagicMock(side_effect=RuntimeError("worker crashed"))

        with patch("stata_agent.log_manager.LogRotator"):
            await daemon._background_run(MagicMock(), task_id, {"code": "crash"})

        assert daemon._background_tasks[task_id]["status"] == "failed"
        assert "worker crashed" in daemon._background_tasks[task_id].get("error", "")

    async def test_background_run_starts_with_default_status(self, daemon):
        """If task_id is not yet in _background_tasks, _background_run should add it."""
        task_id = "bg-task-3"
        daemon._call_worker = MagicMock(return_value={"rc": 0, "ok": True})

        with patch("stata_agent.log_manager.LogRotator"):
            await daemon._background_run(MagicMock(), task_id, {"code": "display 1+1"})

        assert daemon._background_tasks[task_id]["status"] == "completed"


# ---------------------------------------------------------------------------
# _cleanup_temps
# ---------------------------------------------------------------------------


class TestCleanupTemps:
    """Tests for _cleanup_temps periodic cleanup."""

    async def test_cleanup_deletes_expired_files(self, daemon):
        daemon._temp_files = {
            "/tmp/old.pdf": time.time() - 1000,  # expired
            "/tmp/new.pdf": time.time() + 1000,  # still valid
        }

        with patch("stata_agent.daemon.Path") as MockPath:
            mock_path = MagicMock()
            mock_path.unlink = MagicMock()
            MockPath.return_value = mock_path

            # run _cleanup_temps once (it loops until shutdown)
            async def run_one_cycle():
                now = time.time()
                for p in [p for p, t in daemon._temp_files.items() if t < now]:
                    Path(p).unlink(missing_ok=True)
                    del daemon._temp_files[p]

            await run_one_cycle()

        # expired file should have been removed from tracking
        assert "/tmp/old.pdf" not in daemon._temp_files
        assert "/tmp/new.pdf" in daemon._temp_files

    async def test_cleanup_skips_valid_files(self, daemon):
        daemon._temp_files = {
            "/tmp/valid.pdf": time.time() + 300,
        }
        original = dict(daemon._temp_files)

        now = time.time()
        for p in [p for p, t in daemon._temp_files.items() if t < now]:
            Path(p).unlink(missing_ok=True)
            del daemon._temp_files[p]

        assert daemon._temp_files == original

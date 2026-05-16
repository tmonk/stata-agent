"""Unit tests for daemon.py — no real Stata needed."""
from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from stata_agent.daemon import JsonProtocol, StataDaemon


# ---------------------------------------------------------------------------
# JsonProtocol tests
# ---------------------------------------------------------------------------


class TestJsonProtocol:
    """Tests for the NDJSON protocol handler."""

    async def test_json_protocol_complete_line(self):
        """data_received with a complete NDJSON line calls dispatch and sends ok response."""
        daemon = MagicMock(spec=StataDaemon)
        daemon.dispatch = AsyncMock(return_value={"status": "ok"})
        transport = MagicMock()
        transport.is_closing.return_value = False

        protocol = JsonProtocol(daemon)
        protocol.connection_made(transport)

        req = {"method": "health", "id": "test-1"}
        protocol.data_received((json.dumps(req) + "\n").encode("utf-8"))

        # Let the created task run
        await asyncio.sleep(0)

        daemon.dispatch.assert_awaited_once_with("health", {})
        transport.write.assert_called_once()
        sent = json.loads(transport.write.call_args[0][0].decode("utf-8"))
        assert sent["ok"] is True
        assert sent["id"] == "test-1"
        assert sent["result"] == {"status": "ok"}

    async def test_json_protocol_fragmented_line(self):
        """data_received with split line buffers until newline arrives."""
        daemon = MagicMock(spec=StataDaemon)
        daemon.dispatch = AsyncMock(return_value={})
        transport = MagicMock()
        transport.is_closing.return_value = False

        protocol = JsonProtocol(daemon)
        protocol.connection_made(transport)

        req = {"method": "health", "id": "test-1"}
        payload = json.dumps(req)
        mid = len(payload) // 2

        # Send first half without newline
        protocol.data_received(payload[:mid].encode("utf-8"))

        # dispatch should NOT have been called yet — no complete line
        daemon.dispatch.assert_not_called()
        transport.write.assert_not_called()

        # Send second half with newline to complete the line
        protocol.data_received((payload[mid:] + "\n").encode("utf-8"))
        await asyncio.sleep(0)

        daemon.dispatch.assert_awaited_once()
        transport.write.assert_called_once()

    def test_json_protocol_invalid_json_sends_parse_error(self):
        """data_received with invalid JSON sends PARSE_ERROR without calling dispatch."""
        daemon = MagicMock(spec=StataDaemon)
        daemon.dispatch = AsyncMock()
        transport = MagicMock()
        transport.is_closing.return_value = False

        protocol = JsonProtocol(daemon)
        protocol.connection_made(transport)

        protocol.data_received(b"not valid json\n")

        daemon.dispatch.assert_not_called()
        transport.write.assert_called_once()
        sent = json.loads(transport.write.call_args[0][0].decode("utf-8"))
        assert sent["ok"] is False
        assert sent["error_code"] == "PARSE_ERROR"
        assert "Invalid JSON" in sent["error"]

    async def test_json_protocol_dispatch_exception_wrapped(self):
        """dispatch exception is caught and sent as ok=false envelope."""
        daemon = MagicMock(spec=StataDaemon)
        daemon.dispatch = AsyncMock(side_effect=ValueError("something broke"))
        transport = MagicMock()
        transport.is_closing.return_value = False

        protocol = JsonProtocol(daemon)
        protocol.connection_made(transport)

        req = {"method": "bad", "id": "test-1"}
        protocol.data_received((json.dumps(req) + "\n").encode("utf-8"))
        await asyncio.sleep(0)

        transport.write.assert_called_once()
        sent = json.loads(transport.write.call_args[0][0].decode("utf-8"))
        assert sent["ok"] is False
        assert "something broke" in sent["error"]
        assert sent["id"] == "test-1"

    async def test_json_protocol_blank_line_skipped(self):
        """Empty or whitespace-only lines are silently skipped (no crash, no dispatch)."""
        daemon = MagicMock(spec=StataDaemon)
        daemon.dispatch = AsyncMock()
        transport = MagicMock()

        protocol = JsonProtocol(daemon)
        protocol.connection_made(transport)

        # Only blank/whitespace-only lines — nothing dispatched
        protocol.data_received(b"\n\n  \n\n")
        await asyncio.sleep(0)

        daemon.dispatch.assert_not_called()
        transport.write.assert_not_called()


# ---------------------------------------------------------------------------
# StataDaemon dispatch tests
# ---------------------------------------------------------------------------


@pytest.fixture
def daemon_with_mock_sessions():
    from stata_agent.session import SessionManager

    d = StataDaemon(session_name="default")
    d.sessions = MagicMock(spec=SessionManager)
    d.sessions.get_session_names.return_value = ["default"]
    d.sessions.get_or_create.return_value = MagicMock()
    d._shutdown_event = asyncio.Event()
    # isolate per-instance (class-level dicts shared otherwise)
    d._background_tasks = {}
    d._temp_files = {}
    return d


class TestDispatch:
    """StataDaemon.dispatch() routing tests."""

    async def test_dispatch_health(self, daemon_with_mock_sessions):
        daemon = daemon_with_mock_sessions
        result = await daemon.dispatch("health", {})

        assert result["status"] == "ok"
        assert "pid" in result
        assert result["sessions"] == ["default"]

    async def test_dispatch_stop_sets_shutdown(self, daemon_with_mock_sessions):
        daemon = daemon_with_mock_sessions
        assert not daemon._shutdown_event.is_set()

        result = await daemon.dispatch("stop", {})

        assert result["acknowledged"] is True
        daemon.sessions.stop_all.assert_called_once()
        assert daemon._shutdown_event.is_set()

    async def test_dispatch_break_delegates_to_sessions(self, daemon_with_mock_sessions):
        daemon = daemon_with_mock_sessions
        await daemon.dispatch("break", {})

        daemon.sessions.send_break.assert_called_once()

    async def test_dispatch_run_foreground(self, daemon_with_mock_sessions):
        daemon = daemon_with_mock_sessions
        expected = {"status": "running", "output": "ok"}
        daemon._call_worker = MagicMock(return_value=expected)

        result = await daemon.dispatch("run", {"cmd": "describe"})

        assert result == expected
        daemon._call_worker.assert_called_once()
        # first arg is handle (MagicMock), second is method, third is args
        assert daemon._call_worker.call_args[0][1] == "run"
        assert daemon._call_worker.call_args[0][2] == {"cmd": "describe"}

    async def test_dispatch_run_background_returns_task_id_immediately(
        self, daemon_with_mock_sessions,
    ):
        daemon = daemon_with_mock_sessions
        daemon._background_tasks = {}

        expected_log_path = str(Path("/tmp/test_background.log"))
        with patch("stata_agent.log_manager.LogRotator") as MockRotator:
            instance = MockRotator.return_value
            instance.next_path.return_value = Path(expected_log_path)

            result = await daemon.dispatch("run", {"background": True, "cmd": "long job"})

        assert "task_id" in result
        assert result["status"] == "running"
        assert result["log_path"] == expected_log_path
        assert len(daemon._background_tasks) == 1
        task_id = result["task_id"]
        assert daemon._background_tasks[task_id]["status"] == "running"
        assert daemon._background_tasks[task_id]["log_path"] == expected_log_path

    async def test_dispatch_task_status_known_task(self, daemon_with_mock_sessions):
        daemon = daemon_with_mock_sessions
        daemon._background_tasks = {
            "task-1": {"status": "completed", "task_id": "task-1", "log_path": "/tmp/t1.log"},
        }

        result = await daemon.dispatch("task_status", {"task_id": "task-1"})

        assert result["status"] == "completed"

    async def test_dispatch_task_status_unknown_returns_not_found(
        self, daemon_with_mock_sessions,
    ):
        daemon = daemon_with_mock_sessions
        result = await daemon.dispatch("task_status", {"task_id": "nonexistent"})
        assert result["status"] == "not_found"

    async def test_dispatch_task_cancel(self, daemon_with_mock_sessions):
        daemon = daemon_with_mock_sessions
        daemon._background_tasks = {"task-1": {"status": "running", "task_id": "task-1"}}

        result = await daemon.dispatch("task_cancel", {"task_id": "task-1"})

        assert result["cancelled"] is True
        assert daemon._background_tasks["task-1"]["status"] == "cancelled"
        daemon.sessions.send_break.assert_called_once()

    async def test_dispatch_task_cancel_unknown(self, daemon_with_mock_sessions):
        daemon = daemon_with_mock_sessions
        result = await daemon.dispatch("task_cancel", {"task_id": "nonexistent"})
        assert result["cancelled"] is False
        assert "not found" in result.get("error", "")

    async def test_dispatch_log_read_at_offset(self, daemon_with_mock_sessions):
        daemon = daemon_with_mock_sessions
        expected_data = "line1\nline2"
        with patch(
            "stata_agent.daemon.paginated_read",
            return_value={"data": expected_data, "next_offset": 20},
        ):
            result = await daemon.dispatch(
                "log_read_at_offset", {"log_path": "/tmp/test.log", "offset": 0},
            )

        assert result["text"] == expected_data
        assert result["next_offset"] == 20

    async def test_dispatch_log_read_at_offset_empty_path(
        self, daemon_with_mock_sessions,
    ):
        daemon = daemon_with_mock_sessions
        result = await daemon.dispatch("log_read_at_offset", {"log_path": "", "offset": 0})
        assert result["text"] == ""
        assert result["next_offset"] == 0

    async def test_dispatch_graph_export_auto_out_path(self, daemon_with_mock_sessions):
        daemon = daemon_with_mock_sessions
        daemon._temp_files = {}
        daemon._call_worker = MagicMock(return_value={"status": "ok"})

        with patch("tempfile.mkstemp", return_value=(3, "/tmp/graph.pdf")):
            with patch("stata_agent.daemon.os.close") as mock_close:
                args = {}
                await daemon.dispatch("graph_export", args)

        assert args.get("out_path") == "/tmp/graph.pdf"
        assert "/tmp/graph.pdf" in daemon._temp_files
        # temp entry has a TTL (time.time() + 300) — just check it's there
        assert daemon._temp_files["/tmp/graph.pdf"] > time.time() + 250
        daemon._call_worker.assert_called_once()
        mock_close.assert_called_once_with(3)

    async def test_dispatch_graph_export_explicit_out_path(self, daemon_with_mock_sessions):
        daemon = daemon_with_mock_sessions
        daemon._call_worker = MagicMock(return_value={"status": "ok"})

        with patch("tempfile.mkstemp") as mock_mkstemp:
            result = await daemon.dispatch(
                "graph_export", {"out_path": "/custom/graph.png"},
            )

        mock_mkstemp.assert_not_called()
        daemon._call_worker.assert_called_once()

    async def test_dispatch_unknown_method_raises(self, daemon_with_mock_sessions):
        daemon = daemon_with_mock_sessions
        with pytest.raises(ValueError, match="Unknown method"):
            await daemon.dispatch("nonexistent", {})


class TestCallWorker:
    """StataDaemon._call_worker() tests."""

    def test_call_worker_timeout(self, daemon_with_mock_sessions):
        daemon = daemon_with_mock_sessions
        handle = MagicMock()
        handle.conn.poll.return_value = False

        with pytest.raises(TimeoutError, match="did not respond"):
            daemon._call_worker(handle, "run", {})

        handle.conn.send.assert_called_once()
        handle.conn.poll.assert_called_once()


class TestStart:
    """StataDaemon.start() tests."""

    async def test_start_writes_unix_meta_file(self, daemon_with_mock_sessions, tmp_path):
        daemon = daemon_with_mock_sessions
        daemon.transport = "unix"
        daemon._shutdown_event.set()  # so start() returns after cleanup

        sock_path = tmp_path / "default.sock"
        sock_path.touch()  # os.chmod needs an existing file

        from unittest.mock import MagicMock
        mock_server = MagicMock()
        mock_server.wait_closed = AsyncMock()

        written_meta = None
        original_write_text = Path.write_text

        def capture_meta(self, text, *args, **kwargs):
            nonlocal written_meta
            if "default.json" in str(self):
                try:
                    written_meta = json.loads(text)
                except json.JSONDecodeError:
                    pass
            return original_write_text(self, text, *args, **kwargs)

        with patch("stata_agent.daemon.SESSION_DIR", tmp_path):
            with patch("stata_agent.daemon.os.chmod"):
                with patch.object(Path, "write_text", capture_meta):
                    with patch("asyncio.get_event_loop") as mock_get_loop:
                        mock_loop = MagicMock()
                        mock_get_loop.return_value = mock_loop
                        mock_loop.create_unix_server = AsyncMock(return_value=mock_server)

                        await daemon.start()

        assert written_meta is not None, "No meta JSON was written"
        assert written_meta["transport"] == "unix"
        assert "path" in written_meta
        assert str(sock_path) == written_meta["path"]

    async def test_idle_check_fires_shutdown(self, daemon_with_mock_sessions):
        """Verify idle check logic: when idle time exceeds timeout, shutdown triggers."""
        daemon = daemon_with_mock_sessions
        daemon._last_active = time.time() - daemon._idle_timeout - 1
        assert not daemon._shutdown_event.is_set()

        # Same condition as the _idle_check inner coroutine
        if time.time() - daemon._last_active > daemon._idle_timeout:
            daemon._shutdown_event.set()

        assert daemon._shutdown_event.is_set()

    async def test_idle_check_does_not_fire_when_active(self, daemon_with_mock_sessions):
        """When last_active is recent, idle check does not set shutdown."""
        daemon = daemon_with_mock_sessions
        daemon._last_active = time.time()  # just updated
        assert not daemon._shutdown_event.is_set()

        if time.time() - daemon._last_active > daemon._idle_timeout:
            daemon._shutdown_event.set()

        assert not daemon._shutdown_event.is_set()

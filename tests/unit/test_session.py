"""Unit tests for session management."""

from __future__ import annotations

from unittest.mock import patch, MagicMock

import pytest

from stata_agent.session import SessionManager, WorkerHandle, get_session_manager


class TestWorkerHandle:
    def test_worker_handle_creation(self):
        handle = WorkerHandle(
            process=MagicMock(),
            conn=MagicMock(),
            pid=12345,
            session_name="test",
        )
        assert handle.pid == 12345
        assert handle.session_name == "test"
        assert handle.created_at == 0.0


class TestSessionManager:
    def test_init(self):
        mgr = SessionManager()
        assert mgr.get_session_names() == []

    def test_stop_nonexistent(self):
        mgr = SessionManager()
        mgr.stop("nonexistent")  # Should not raise

    def test_stop_all_empty(self):
        mgr = SessionManager()
        mgr.stop_all()  # Should not raise

    def test_get_or_create_creates_default(self):
        """get_or_create('default') should spawn a worker."""
        mgr = SessionManager()
        with patch("stata_agent.session.ctx.Process") as mock_process:
            mock_proc = MagicMock()
            mock_proc.pid = 99999
            mock_process.return_value = mock_proc

            # Mock the pipe
            with patch("stata_agent.session.ctx.Pipe") as mock_pipe:
                parent_conn = MagicMock()
                child_conn = MagicMock()
                mock_pipe.return_value = (parent_conn, child_conn)

                # Mock the ready signal
                parent_conn.poll.return_value = True
                parent_conn.recv.return_value = {"event": "ready", "pid": 99999, "session": "test_session"}

                handle = mgr.create("test_session")
                assert handle.pid == 99999
                assert handle.session_name == "test_session"

    def test_get_or_create_reuses_existing(self):
        mgr = SessionManager()
        mock_handle = MagicMock()
        mock_handle.process.is_alive.return_value = True
        mgr._sessions["existing"] = mock_handle

        handle = mgr.get_or_create("existing")
        assert handle is mock_handle

    def test_get_or_create_restarts_dead(self):
        mgr = SessionManager()
        mock_handle = MagicMock()
        mock_handle.process.is_alive.return_value = False
        mgr._sessions["dead"] = mock_handle

        with patch.object(mgr, "create") as mock_create:
            mock_create.return_value = MagicMock()
            mgr.get_or_create("dead")
            mock_create.assert_called_once_with("dead")


class TestGetSessionManager:
    def test_singleton(self):
        mgr1 = get_session_manager()
        mgr2 = get_session_manager()
        assert mgr1 is mgr2

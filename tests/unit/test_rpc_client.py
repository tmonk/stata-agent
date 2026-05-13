"""Unit tests for rpc_client."""

from __future__ import annotations

import json
import os
import socket
import unittest.mock
import threading
from pathlib import Path

import pytest

from stata_agent.rpc_client import RpcClient, RpcError, _get_socket_path, _get_meta_path


class TestSocketPaths:
    def test_socket_path_default(self):
        path = _get_socket_path("default")
        assert str(path).endswith("/default.sock")

    def test_socket_path_custom(self):
        path = _get_socket_path("my_session")
        assert str(path).endswith("/my_session.sock")

    def test_meta_path(self):
        path = _get_meta_path("default")
        assert str(path).endswith("/default.json")


class TestRpcClient:
    def test_connect_fails_when_no_daemon(self):
        client = RpcClient(session="nonexistent_test")
        with pytest.raises(FileNotFoundError):
            client.call("health", {})

    def test_is_alive_when_no_daemon(self):
        client = RpcClient(session="nonexistent_test")
        assert client.is_alive() is False

    def test_is_daemon_running(self):
        # No daemon should be running for this test session
        assert RpcClient.is_daemon_running("nonexistent") is False


class TestRpcError:
    def test_rpc_error_basic(self):
        err = RpcError("test error", "TEST_CODE", {"key": "val"})
        assert str(err) == "test error"
        assert err.error_code == "TEST_CODE"
        assert err.details == {"key": "val"}

    def test_rpc_no_details(self):
        err = RpcError("simple error")
        assert err.error_code == ""
        assert err.details == {}

def _make_response(ok: bool, result=None, error="err"):
    """Construct an NDJSON response line for the mock daemon."""
    payload = {"ok": ok}
    if ok:
        payload["result"] = result or {}
    else:
        payload["error"] = error
        payload["error_code"] = "TEST_ERROR"
    return (json.dumps(payload) + "\n").encode()


class TestConnect:
    """Tests for RpcClient._connect."""

    def test_connect_unix_socket(self, tmp_path):
        import stata_agent.rpc_client as rpc

        orig = rpc.SESSION_DIR
        try:
            rpc.SESSION_DIR = tmp_path
            sock_file = tmp_path / "test.sock"
            sock_file.touch()

            with unittest.mock.patch("socket.socket") as mock_socket_cls:
                mock_sock = mock_socket_cls.return_value
                client = RpcClient(session="test")
                result = client._connect()

                mock_socket_cls.assert_called_once_with(
                    socket.AF_UNIX, socket.SOCK_STREAM
                )
                mock_sock.connect.assert_called_once_with(str(sock_file))
                assert result is mock_sock
        finally:
            rpc.SESSION_DIR = orig

    def test_connect_tcp_fallback(self, tmp_path):
        import stata_agent.rpc_client as rpc

        orig = rpc.SESSION_DIR
        try:
            rpc.SESSION_DIR = tmp_path
            meta_file = tmp_path / "test.json"
            meta_file.write_text(
                json.dumps({"transport": "tcp", "host": "127.0.0.1", "port": 12345})
            )

            with unittest.mock.patch("socket.socket") as mock_socket_cls:
                mock_sock = mock_socket_cls.return_value
                client = RpcClient(session="test")
                result = client._connect()

                mock_socket_cls.assert_called_once_with(
                    socket.AF_INET, socket.SOCK_STREAM
                )
                mock_sock.connect.assert_called_once_with(("127.0.0.1", 12345))
                assert result is mock_sock
        finally:
            rpc.SESSION_DIR = orig

    def test_connect_raises_when_nothing_exists(self, tmp_path):
        import stata_agent.rpc_client as rpc

        orig = rpc.SESSION_DIR
        try:
            rpc.SESSION_DIR = tmp_path
            client = RpcClient(session="test")
            with pytest.raises(FileNotFoundError, match="Daemon socket not found"):
                client._connect()
        finally:
            rpc.SESSION_DIR = orig


class TestCall:
    """Tests for RpcClient.call."""

    def test_call_success(self, tmp_path):
        import stata_agent.rpc_client as rpc

        orig = rpc.SESSION_DIR
        try:
            rpc.SESSION_DIR = tmp_path
            (tmp_path / "test.sock").touch()

            with unittest.mock.patch("socket.socket") as mock_socket_cls:
                mock_sock = mock_socket_cls.return_value
                mock_sock.recv.return_value = _make_response(
                    ok=True, result={"data": 42}
                )
                client = RpcClient(session="test")
                result = client.call("some_method", {"arg": 1})

                assert result == {"data": 42}
                mock_sock.close.assert_called_once()
        finally:
            rpc.SESSION_DIR = orig

    def test_call_raises_rpc_error_on_failure(self, tmp_path):
        import stata_agent.rpc_client as rpc

        orig = rpc.SESSION_DIR
        try:
            rpc.SESSION_DIR = tmp_path
            (tmp_path / "test.sock").touch()

            with unittest.mock.patch("socket.socket") as mock_socket_cls:
                mock_sock = mock_socket_cls.return_value
                mock_sock.recv.return_value = _make_response(
                    ok=False, error="Something went wrong"
                )
                client = RpcClient(session="test")
                with pytest.raises(RpcError, match="Something went wrong") as exc_info:
                    client.call("some_method")
                assert exc_info.value.error_code == "TEST_ERROR"
        finally:
            rpc.SESSION_DIR = orig

    def test_call_raises_on_connection_closed(self, tmp_path):
        import stata_agent.rpc_client as rpc

        orig = rpc.SESSION_DIR
        try:
            rpc.SESSION_DIR = tmp_path
            (tmp_path / "test.sock").touch()

            with unittest.mock.patch("socket.socket") as mock_socket_cls:
                mock_sock = mock_socket_cls.return_value
                mock_sock.recv.return_value = b""
                client = RpcClient(session="test")
                with pytest.raises(RpcError, match="Connection closed") as exc_info:
                    client.call("some_method")
                assert exc_info.value.error_code == "CONNECTION_CLOSED"
        finally:
            rpc.SESSION_DIR = orig


class TestIsAlive:
    """Tests for RpcClient.is_alive."""

    def test_is_alive_true(self, tmp_path):
        import stata_agent.rpc_client as rpc

        orig = rpc.SESSION_DIR
        try:
            rpc.SESSION_DIR = tmp_path
            (tmp_path / "test.sock").touch()

            with unittest.mock.patch("socket.socket") as mock_socket_cls:
                mock_sock = mock_socket_cls.return_value
                mock_sock.recv.return_value = _make_response(ok=True)
                client = RpcClient(session="test")
                assert client.is_alive() is True
        finally:
            rpc.SESSION_DIR = orig

    def test_is_alive_false_on_error(self, tmp_path):
        import stata_agent.rpc_client as rpc

        orig = rpc.SESSION_DIR
        try:
            rpc.SESSION_DIR = tmp_path
            client = RpcClient(session="test")
            assert client.is_alive() is False
        finally:
            rpc.SESSION_DIR = orig


class TestIsDaemonRunning:
    """Tests for RpcClient.is_daemon_running."""

    def test_is_daemon_running_false(self, tmp_path):
        import stata_agent.rpc_client as rpc

        orig = rpc.SESSION_DIR
        try:
            rpc.SESSION_DIR = tmp_path
            assert RpcClient.is_daemon_running("test") is False
        finally:
            rpc.SESSION_DIR = orig

    def test_is_daemon_running_true(self, tmp_path):
        import stata_agent.rpc_client as rpc

        orig = rpc.SESSION_DIR
        try:
            rpc.SESSION_DIR = tmp_path
            (tmp_path / "test.sock").touch()
            assert RpcClient.is_daemon_running("test") is True
        finally:
            rpc.SESSION_DIR = orig

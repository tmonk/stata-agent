"""Edge case and stress tests for rpc_client.py.

Covers failure modes and edge conditions that the basic unit tests don't reach.
"""

from __future__ import annotations

import json
import socket
import time
import unittest.mock
from pathlib import Path

import pytest

from stata_agent.rpc_client import RpcClient, RpcError, _get_socket_path, _get_meta_path


def _make_response(ok: bool, result=None, error="err", error_code="TEST_ERROR"):
    payload = {"ok": ok}
    if ok:
        payload["result"] = result or {}
    else:
        payload["error"] = error
        payload["error_code"] = error_code
    return (json.dumps(payload) + "\n").encode()


class TestRpcClientEdge:
    """Edge case tests for RpcClient."""

    def test_call_with_custom_id(self, tmp_path):
        """Custom request ID should appear in the sent JSON."""
        import stata_agent.rpc_client as rpc

        orig = rpc.SESSION_DIR
        try:
            rpc.SESSION_DIR = tmp_path
            (tmp_path / "test.sock").touch()

            sent_data = []
            with unittest.mock.patch("socket.socket") as mock_socket_cls:
                mock_sock = mock_socket_cls.return_value
                mock_sock.sendall.side_effect = lambda data: sent_data.append(data)
                mock_sock.recv.return_value = _make_response(True)

                client = RpcClient(session="test")
                client.call("some_method", {"arg": 1}, id="my-custom-id")

                # Verify the sent JSON includes our custom id
                sent_json = json.loads(sent_data[0].decode("utf-8"))
                assert sent_json["id"] == "my-custom-id"
                assert sent_json["method"] == "some_method"
                assert sent_json["args"] == {"arg": 1}
        finally:
            rpc.SESSION_DIR = orig

    def test_call_timeout_on_recv(self, tmp_path):
        """If recv() times out, an exception should propagate."""
        import stata_agent.rpc_client as rpc

        orig = rpc.SESSION_DIR
        try:
            rpc.SESSION_DIR = tmp_path
            (tmp_path / "test.sock").touch()

            with unittest.mock.patch("socket.socket") as mock_socket_cls:
                mock_sock = mock_socket_cls.return_value
                mock_sock.recv.side_effect = socket.timeout("timed out")

                client = RpcClient(session="test", timeout=0.1)
                with pytest.raises((socket.timeout, Exception)):
                    client.call("some_method")
        finally:
            rpc.SESSION_DIR = orig

    def test_call_recv_fragmented_response(self, tmp_path):
        """Response split across multiple recv() calls should be reassembled."""
        import stata_agent.rpc_client as rpc

        orig = rpc.SESSION_DIR
        try:
            rpc.SESSION_DIR = tmp_path
            (tmp_path / "test.sock").touch()

            full_response = _make_response(True, {"data": 42})
            mid = len(full_response) // 2
            recv_calls = [full_response[:mid], full_response[mid:]]

            with unittest.mock.patch("socket.socket") as mock_socket_cls:
                mock_sock = mock_socket_cls.return_value
                mock_sock.recv.side_effect = recv_calls

                client = RpcClient(session="test")
                result = client.call("some_method")

                assert result == {"data": 42}
        finally:
            rpc.SESSION_DIR = orig

    def test_call_multiple_lines_in_one_recv(self, tmp_path):
        """Multiple response lines in one recv() — only first should be used."""
        import stata_agent.rpc_client as rpc

        orig = rpc.SESSION_DIR
        try:
            rpc.SESSION_DIR = tmp_path
            (tmp_path / "test.sock").touch()

            combined = (
                _make_response(True, {"first": 1}) +
                _make_response(True, {"second": 2})
            )

            with unittest.mock.patch("socket.socket") as mock_socket_cls:
                mock_sock = mock_socket_cls.return_value
                mock_sock.recv.return_value = combined

                client = RpcClient(session="test")
                result = client.call("some_method")

                # Should return the first response only
                assert result == {"first": 1}
        finally:
            rpc.SESSION_DIR = orig

    def test_call_error_with_details(self, tmp_path):
        """Error response with details should propagate in RpcError."""
        import stata_agent.rpc_client as rpc

        orig = rpc.SESSION_DIR
        try:
            rpc.SESSION_DIR = tmp_path
            (tmp_path / "test.sock").touch()

            with unittest.mock.patch("socket.socket") as mock_socket_cls:
                mock_sock = mock_socket_cls.return_value
                mock_sock.recv.return_value = _make_response(
                    False, error="Something broke",
                    error_code="INTERNAL_ERROR",
                )

                client = RpcClient(session="test")
                with pytest.raises(RpcError) as exc_info:
                    client.call("some_method")

                assert exc_info.value.error_code == "INTERNAL_ERROR"
                assert "Something broke" in str(exc_info.value)
        finally:
            rpc.SESSION_DIR = orig

    def test_is_alive_with_tcp_meta(self, tmp_path):
        """is_alive should attempt TCP connection when meta says tcp."""
        import stata_agent.rpc_client as rpc

        orig = rpc.SESSION_DIR
        try:
            rpc.SESSION_DIR = tmp_path
            meta_file = tmp_path / "test.json"
            meta_file.write_text(
                json.dumps({"transport": "tcp", "host": "127.0.0.1", "port": 9999})
            )

            with unittest.mock.patch("socket.socket") as mock_socket_cls:
                mock_sock = mock_socket_cls.return_value
                mock_sock.recv.return_value = _make_response(True)

                client = RpcClient(session="test")
                assert client.is_alive() is True

                # Should have created a TCP socket
                mock_socket_cls.assert_called_with(socket.AF_INET, socket.SOCK_STREAM)
        finally:
            rpc.SESSION_DIR = orig

    def test_is_alive_connection_refused(self, tmp_path):
        """Connection refused should return False, not throw."""
        import stata_agent.rpc_client as rpc

        orig = rpc.SESSION_DIR
        try:
            rpc.SESSION_DIR = tmp_path
            (tmp_path / "test.sock").touch()

            with unittest.mock.patch("socket.socket") as mock_socket_cls:
                mock_sock = mock_socket_cls.return_value
                mock_sock.connect.side_effect = ConnectionRefusedError()

                client = RpcClient(session="test")
                assert client.is_alive() is False
        finally:
            rpc.SESSION_DIR = orig

    def test_is_alive_rpc_error(self, tmp_path):
        """RPC error response should return False."""
        import stata_agent.rpc_client as rpc

        orig = rpc.SESSION_DIR
        try:
            rpc.SESSION_DIR = tmp_path
            (tmp_path / "test.sock").touch()

            with unittest.mock.patch("socket.socket") as mock_socket_cls:
                mock_sock = mock_socket_cls.return_value
                mock_sock.recv.return_value = _make_response(False)

                client = RpcClient(session="test")
                assert client.is_alive() is False
        finally:
            rpc.SESSION_DIR = orig

    def test_connect_caches_no_meta(self, tmp_path):
        """_connect raises FileNotFoundError when no meta or sock exists."""
        import stata_agent.rpc_client as rpc

        orig = rpc.SESSION_DIR
        try:
            rpc.SESSION_DIR = tmp_path
            client = RpcClient(session="test")
            with pytest.raises(FileNotFoundError):
                client._connect()
        finally:
            rpc.SESSION_DIR = orig

    def test_invalid_meta_json(self, tmp_path):
        """Corrupt meta JSON should cause _connect to fail gracefully."""
        import stata_agent.rpc_client as rpc

        orig = rpc.SESSION_DIR
        try:
            rpc.SESSION_DIR = tmp_path
            meta_file = tmp_path / "test.json"
            meta_file.write_text("not valid json")

            client = RpcClient(session="test")
            with pytest.raises(FileNotFoundError, match="Daemon socket not found"):
                client._connect()
        finally:
            rpc.SESSION_DIR = orig

    def test_socket_removed_between_connect_and_send(self, tmp_path):
        """Socket file removed between connect and send should still raise."""
        import stata_agent.rpc_client as rpc

        orig = rpc.SESSION_DIR
        try:
            rpc.SESSION_DIR = tmp_path
            (tmp_path / "test.sock").touch()

            with unittest.mock.patch("socket.socket") as mock_socket_cls:
                mock_sock = mock_socket_cls.return_value
                mock_sock.sendall.side_effect = BrokenPipeError("broken pipe")

                client = RpcClient(session="test")
                with pytest.raises(BrokenPipeError):
                    client.call("some_method")
        finally:
            rpc.SESSION_DIR = orig

    def test_connect_tcp_without_host(self, tmp_path):
        """TCP meta without host should default to 127.0.0.1."""
        import stata_agent.rpc_client as rpc

        orig = rpc.SESSION_DIR
        try:
            rpc.SESSION_DIR = tmp_path
            meta_file = tmp_path / "test.json"
            meta_file.write_text(json.dumps({"transport": "tcp", "port": 9999}))

            with unittest.mock.patch("socket.socket") as mock_socket_cls:
                mock_sock = mock_socket_cls.return_value
                client = RpcClient(session="test")
                try:
                    client._connect()
                except Exception:
                    pass  # Connection will fail, but we verify the call

                # Should have tried to connect to 127.0.0.1
                calls = mock_sock.connect.call_args_list
                if calls:
                    assert calls[0][0][0] == ("127.0.0.1", 9999)
        finally:
            rpc.SESSION_DIR = orig

    def test_timeout_propagated_to_socket(self, tmp_path):
        """Client timeout should be set on the socket."""
        import stata_agent.rpc_client as rpc

        orig = rpc.SESSION_DIR
        try:
            rpc.SESSION_DIR = tmp_path
            (tmp_path / "test.sock").touch()

            with unittest.mock.patch("socket.socket") as mock_socket_cls:
                mock_sock = mock_socket_cls.return_value

                client = RpcClient(session="test", timeout=5.0)
                try:
                    client._connect()
                except Exception:
                    pass

                mock_sock.settimeout.assert_called_with(5.0)
        finally:
            rpc.SESSION_DIR = orig

    def test_concurrent_calls_same_client(self, tmp_path):
        """Multiple sequential calls on same client should work."""
        import stata_agent.rpc_client as rpc

        orig = rpc.SESSION_DIR
        try:
            rpc.SESSION_DIR = tmp_path
            (tmp_path / "test.sock").touch()

            with unittest.mock.patch("socket.socket") as mock_socket_cls:
                mock_sock = mock_socket_cls.return_value
                mock_sock.recv.side_effect = [
                    _make_response(True, {"n": 1}),
                    _make_response(True, {"n": 2}),
                    _make_response(True, {"n": 3}),
                ]

                client = RpcClient(session="test")

                r1 = client.call("m1")
                r2 = client.call("m2")
                r3 = client.call("m3")

                assert r1 == {"n": 1}
                assert r2 == {"n": 2}
                assert r3 == {"n": 3}
                # Each call should have opened a new socket (RpcClient doesn't pool)
                assert mock_socket_cls.call_count == 3
        finally:
            rpc.SESSION_DIR = orig

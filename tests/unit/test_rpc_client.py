"""Unit tests for rpc_client."""

from __future__ import annotations

import json
import os
import socket
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

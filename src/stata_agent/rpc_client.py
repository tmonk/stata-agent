"""NDJSON client for communicating with the stata-daemon."""
from __future__ import annotations

import json
import os
import socket
import sys
import uuid
from typing import Any, Optional
from pathlib import Path


SESSION_DIR = Path.home() / ".cache" / "stata-agent" / "sessions"


def _get_socket_path(session: str = "default") -> Path:
    return SESSION_DIR / f"{session}.sock"


def _get_meta_path(session: str = "default") -> Path:
    return SESSION_DIR / f"{session}.json"


class RpcError(Exception):
    """Raised when the daemon returns an error response."""
    def __init__(self, message: str, error_code: str = "", details: dict | None = None):
        super().__init__(message)
        self.error_code = error_code
        self.details = details or {}


class RpcClient:
    """Synchronous NDJSON client for the stata-daemon."""

    def __init__(self, session: str = "default", timeout: float = 30.0):
        self.session = session
        self.timeout = timeout

    def _connect(self) -> socket.socket:
        """Connect to the daemon socket."""
        # Try Unix socket first (not available on all Windows Python versions)
        sock_path = _get_socket_path(self.session)
        unix_available = hasattr(socket, "AF_UNIX")
        if sock_path.exists() and unix_available:
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            s.settimeout(self.timeout)
            s.connect(str(sock_path))
            return s

        # Fall back to TCP from meta file
        meta_path = _get_meta_path(self.session)
        if meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text())
            except (json.JSONDecodeError, ValueError):
                # Corrupt meta file — treat as missing
                meta_path.unlink(missing_ok=True)
                raise FileNotFoundError(f"Daemon socket not found for session '{self.session}'")
            if meta.get("transport") == "tcp":
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(self.timeout)
                try:
                    s.connect((meta["host"], meta.get("port", 0)))
                except (KeyError, TypeError):
                    s.close()
                    raise FileNotFoundError(f"Daemon socket not found for session '{self.session}'")
                return s

        raise FileNotFoundError(f"Daemon socket not found for session '{self.session}'")

    def call(self, method: str, args: dict | None = None, id: str | None = None) -> dict[str, Any]:
        """Send an NDJSON request and return the parsed response."""
        request_id = id or uuid.uuid4().hex
        request = {"id": request_id, "method": method, "args": args or {}}

        s = self._connect()
        try:
            s.sendall((json.dumps(request) + "\n").encode("utf-8"))
            buf = b""
            while True:
                chunk = s.recv(65536)
                if not chunk:
                    break
                buf += chunk
                if b"\n" in buf:
                    line, _ = buf.split(b"\n", 1)
                    response = json.loads(line.decode("utf-8"))
                    if not response.get("ok", False):
                        raise RpcError(
                            response.get("error", "Unknown error"),
                            error_code=response.get("error_code", ""),
                            details=response.get("details", {}),
                        )
                    return response.get("result", {})
            raise RpcError("Connection closed without response", error_code="CONNECTION_CLOSED")
        finally:
            s.close()

    def is_alive(self) -> bool:
        """Check if the daemon is running and responsive."""
        try:
            self.call("health", {})
            return True
        except (FileNotFoundError, ConnectionRefusedError, OSError, RpcError):
            return False

    @staticmethod
    def is_daemon_running(session: str = "default") -> bool:
        """Static check — does the daemon socket exist?"""
        sock_path = _get_socket_path(session)
        return sock_path.exists()

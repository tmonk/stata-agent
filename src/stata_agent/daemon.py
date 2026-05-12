"""stata-daemon — asyncio NDJSON server over Unix domain socket.

The daemon manages worker processes for named Stata sessions and
routes incoming NDJSON requests to the appropriate worker.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Optional

from stata_agent.session import SessionManager, get_session_manager
from stata_agent.log_manager import (
    tail_file,
    search_in_log,
    paginated_read,
)
from stata_agent.error_extractor import ErrorExtractor

logger = logging.getLogger("stata.daemon")

SESSION_DIR = Path.home() / ".cache" / "mcp-stata" / "sessions"
LOG_DIR = Path.home() / ".cache" / "mcp-stata" / "logs"


class JsonProtocol(asyncio.Protocol):
    """NDJSON protocol handler for a single client connection."""

    def __init__(self, daemon: "StataDaemon"):
        self.daemon = daemon
        self.buf = ""
        self.transport: Optional[asyncio.WriteTransport] = None

    def connection_made(self, transport: asyncio.WriteTransport) -> None:
        self.transport = transport

    def data_received(self, data: bytes) -> None:
        self.buf += data.decode("utf-8")
        while "\n" in self.buf:
            line, self.buf = self.buf.split("\n", 1)
            if not line.strip():
                continue
            try:
                req = json.loads(line)
                asyncio.create_task(self._handle(req))
            except json.JSONDecodeError:
                self._send({"ok": False, "error": "Invalid JSON", "error_code": "PARSE_ERROR"})

    async def _handle(self, req: dict) -> None:
        method = req.get("method", "")
        msg_id = req.get("id", uuid.uuid4().hex)
        args = req.get("args", {})
        try:
            result = await self.daemon.dispatch(method, args)
            self._send({"id": msg_id, "ok": True, "result": result})
        except Exception as e:
            self._send({
                "id": msg_id,
                "ok": False,
                "error": str(e),
                "error_code": getattr(e, "error_code", "INTERNAL_ERROR"),
                "details": getattr(e, "details", {}),
            })

    def _send(self, payload: dict) -> None:
        if self.transport and not self.transport.is_closing():
            self.transport.write((json.dumps(payload) + "\n").encode("utf-8"))

    def connection_lost(self, exc: Optional[Exception]) -> None:
        pass


class StataDaemon:
    """NDJSON daemon managing Stata worker sessions."""

    def __init__(
        self,
        session_name: str = "default",
        transport: str = "",
    ):
        self.session_name = session_name
        self.transport = transport or ("unix" if sys.platform != "win32" else "tcp")
        self.sock_path: Optional[Path] = None
        self.port: Optional[int] = None
        self.sessions: SessionManager = get_session_manager()
        self._extractor = ErrorExtractor()
        self._shutdown_event = asyncio.Event()
        self._last_active = time.time()
        self._idle_timeout = 1800  # 30 minutes
        LOG_DIR.mkdir(parents=True, exist_ok=True)

    async def start(self) -> None:
        """Start the daemon and listen for connections."""
        SESSION_DIR.mkdir(parents=True, exist_ok=True)

        if self.transport == "unix":
            self.sock_path = SESSION_DIR / f"{self.session_name}.sock"
            self.sock_path.unlink(missing_ok=True)
            server = await asyncio.get_event_loop().create_unix_server(
                lambda: JsonProtocol(self),
                str(self.sock_path),
            )
            os.chmod(str(self.sock_path), 0o600)
            meta: dict = {"transport": "unix", "path": str(self.sock_path)}
        else:
            server = await asyncio.get_event_loop().create_server(
                lambda: JsonProtocol(self),
                "127.0.0.1",
                0,
            )
            self.port = server.sockets[0].getsockname()[1]
            meta = {"transport": "tcp", "host": "127.0.0.1", "port": self.port}

        # Write metadata
        meta_path = SESSION_DIR / f"{self.session_name}.json"
        meta_path.write_text(json.dumps(meta))

        # Create default session worker
        self.sessions.get_or_create(self.session_name)

        print(f"Daemon listening on {json.dumps(meta)}", flush=True)

        # Signal handlers for graceful shutdown
        loop = asyncio.get_event_loop()
        try:
            loop.add_signal_handler(signal.SIGINT, self._shutdown_event.set)
            loop.add_signal_handler(signal.SIGTERM, self._shutdown_event.set)

            # Periodic idle timeout check
            async def _idle_check():
                while not self._shutdown_event.is_set():
                    await asyncio.sleep(60)
                    if time.time() - self._last_active > self._idle_timeout:
                        logger.info("Idle timeout reached; shutting down")
                        self._shutdown_event.set()
                        break

            asyncio.create_task(_idle_check())
        except NotImplementedError:
            # Windows or non-main-thread — signal handlers not supported
            pass

        await self._shutdown_event.wait()
        server.close()
        await server.wait_closed()
        self.sessions.stop_all()
        meta_path.unlink(missing_ok=True)
        if self.sock_path:
            self.sock_path.unlink(missing_ok=True)

    async def dispatch(self, method: str, args: dict) -> dict:
        """Route a method call to the appropriate handler."""
        self._last_active = time.time()

        session_name = args.get("session", self.session_name)

        if method == "health":
            return {
                "status": "ok",
                "pid": os.getpid(),
                "session_name": session_name,
                "sessions": self.sessions.get_session_names(),
            }

        if method == "stop":
            self.sessions.stop_all()
            self._shutdown_event.set()
            return {"acknowledged": True}

        if method == "break":
            return self.sessions.send_break(session_name)

        # All other methods need a worker
        handle = self.sessions.get_or_create(session_name)
        msg_id = uuid.uuid4().hex

        if method == "run":
            send_args = dict(args)
            if args.get("background"):
                task_id = uuid.uuid4().hex
                asyncio.create_task(self._background_run(handle, task_id, send_args))
                return {"task_id": task_id, "status": "running"}
            else:
                return self._call_worker(handle, "run", send_args)

        elif method == "run_file":
            return self._call_worker(handle, "run_file", args)

        elif method in (
            "inspect_describe", "inspect_summary", "inspect_codebook",
            "inspect_list", "inspect_get", "results",
            "graph_list", "graph_export",
            "log_tail", "log_errors",
        ):
            return self._call_worker(handle, method, args)

        elif method == "log_search":
            log_path = args.get("log_path", "")
            pattern = args.get("pattern", "")
            offset = args.get("offset", 0)
            max_bytes = args.get("max_bytes", 262144)
            return search_in_log(log_path, pattern, offset, max_bytes)

        elif method == "log_path":
            # Get the log path from the worker's latest result
            return {"log_path": str(LOG_DIR)}

        elif method == "task_status":
            task_id = args.get("task_id", "")
            tail = args.get("tail_lines", 0)
            task = self._background_tasks.get(task_id)
            if not task:
                return {"status": "not_found"}
            result = dict(task)
            if tail > 0 and task.get("log_path"):
                result["log_tail"] = tail_file(task["log_path"], lines=tail)
            return result

        elif method == "task_cancel":
            task_id = args.get("task_id", "")
            if task_id in self._background_tasks:
                self._background_tasks[task_id]["status"] = "cancelled"
                self.sessions.send_break(session_name)
                return {"cancelled": True}
            return {"cancelled": False, "error": "task not found"}

        elif method == "task_list":
            return {"tasks": [
                {"task_id": tid, "status": info.get("status", "unknown")}
                for tid, info in self._background_tasks.items()
            ]}

        else:
            raise ValueError(f"Unknown method: {method}")

    def _call_worker(self, handle, method: str, args: dict, timeout: float = 300) -> dict:
        """Send a method call to a worker and wait for the response."""
        msg_id = uuid.uuid4().hex
        handle.conn.send({
            "type": "method",
            "method": method,
            "id": msg_id,
            "args": args,
        })

        if handle.conn.poll(timeout):
            response = handle.conn.recv()
            if response.get("event") == "result":
                return response.get("result", {})
            elif response.get("event") == "error":
                raise Exception(
                    response.get("error", "Worker error"),
                )
            return response
        else:
            raise TimeoutError(f"Worker did not respond within {timeout}s")

    _background_tasks: dict[str, dict] = {}

    async def _background_run(self, handle, task_id: str, args: dict) -> None:
        """Run a command in the background."""
        self._background_tasks[task_id] = {
            "status": "running",
            "task_id": task_id,
            "created_at": time.time(),
        }
        try:
            result = self._call_worker(handle, "run", args)
            result["status"] = "completed"
            result["task_id"] = task_id
            self._background_tasks[task_id] = result
        except Exception as e:
            self._background_tasks[task_id] = {
                "status": "failed",
                "task_id": task_id,
                "error": str(e),
            }


def main() -> int:
    """Entry point for the daemon subprocess."""
    import argparse

    parser = argparse.ArgumentParser(description="Stata daemon")
    parser.add_argument("--session", default="default")
    parser.add_argument("--mock", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    if args.mock:
        from stata_agent.mock_backend import MockDaemon
        daemon = MockDaemon(session_name=args.session)
    else:
        daemon = StataDaemon(session_name=args.session)

    async def run():
        await daemon.start()

    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

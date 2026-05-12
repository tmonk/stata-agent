"""Session management — worker lifecycle, auto-start, named session routing.

Each named session has a StataWorker process. The default session is
auto-started on first use. Workers communicate via multiprocessing.Pipe.
"""

from __future__ import annotations

import atexit
import logging
import multiprocessing
import os
import time
from dataclasses import dataclass, field
from multiprocessing.connection import Connection
from typing import Optional

from stata_agent.worker import _worker_main

logger = logging.getLogger("stata.session")

ctx = multiprocessing.get_context("spawn")


@dataclass
class WorkerHandle:
    """Handle for a running worker process."""
    process: multiprocessing.Process
    conn: Connection
    pid: int
    session_name: str
    created_at: float = 0.0
    last_active: float = 0.0


class SessionManager:
    """Manages worker processes for named sessions.

    Usage:
        mgr = SessionManager()
        handle = mgr.get_or_create("default")
        handle.conn.send({"type": "run", ...})
        result = handle.conn.recv()
    """

    def __init__(self):
        self._sessions: dict[str, WorkerHandle] = {}

    def get_or_create(self, name: str = "default") -> WorkerHandle:
        """Get an existing session or spawn a new one.

        Auto-creates the default session; named sessions must be
        explicitly created via create().
        """
        handle = self._sessions.get(name)
        if handle is not None:
            if handle.process.is_alive():
                return handle
            logger.warning("Worker for session '%s' died; restarting", name)
            del self._sessions[name]

        return self.create(name)

    def create(self, name: str) -> WorkerHandle:
        """Spawn a new named session worker."""
        parent_conn, child_conn = ctx.Pipe()
        process = ctx.Process(
            target=_worker_main,
            args=(child_conn, name),
            daemon=True,
        )
        process.start()
        child_conn.close()  # parent doesn't need child end

        # Wait for ready signal (up to 30 seconds)
        if parent_conn.poll(30):
            ready = parent_conn.recv()
            if ready.get("event") != "ready":
                process.kill()
                raise RuntimeError(
                    f"Session '{name}' initialisation failed: "
                    f"expected 'ready', got {ready.get('event')}"
                )
        else:
            process.kill()
            raise RuntimeError(f"Session '{name}' failed to initialise within 30s")

        now = time.time()
        handle = WorkerHandle(
            process=process,
            conn=parent_conn,
            pid=process.pid,
            session_name=name,
            created_at=now,
            last_active=now,
        )
        self._sessions[name] = handle
        logger.info("Session '%s' started (PID %d)", name, process.pid)
        return handle

    def stop(self, name: str) -> None:
        """Stop a named session gracefully, then force-kill if needed."""
        handle = self._sessions.get(name)
        if handle is None:
            return

        try:
            handle.conn.send({"type": "stop"})
            handle.process.join(timeout=5)
        except Exception:
            logger.warning("Error sending stop to session '%s'", name, exc_info=True)

        if handle.process.is_alive():
            logger.warning("Session '%s' did not stop gracefully; killing", name)
            handle.process.kill()
            handle.process.join(timeout=2)

        try:
            handle.conn.close()
        except Exception:
            pass

        del self._sessions[name]
        logger.info("Session '%s' stopped", name)

    def stop_all(self) -> None:
        """Stop all sessions."""
        for name in list(self._sessions.keys()):
            self.stop(name)

    def send_break(self, name: str = "default") -> dict:
        """Send SIGTERM to the worker process to interrupt execution.

        The worker dies immediately (state lost) and is auto-restarted
        on the next request.
        """
        handle = self._sessions.get(name)
        if handle is None:
            return {"acknowledged": True, "note": f"Session '{name}' was not running"}

        pid = handle.pid
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError as e:
            logger.warning("Failed to send SIGTERM to PID %d: %s", pid, e)

        # Clean up the old handle
        try:
            handle.conn.close()
        except Exception:
            pass
        if handle.process.is_alive():
            handle.process.join(timeout=3)

        del self._sessions[name]

        # Auto-restart
        self.create(name)

        return {
            "acknowledged": True,
            "worker_restarted": True,
            "note": "Break acknowledged. Worker restarted. Session state has been reset.",
        }

    def get_session_names(self) -> list[str]:
        return list(self._sessions.keys())


# Module-level cleanup
_session_manager: SessionManager | None = None


def get_session_manager() -> SessionManager:
    global _session_manager
    if _session_manager is None:
        _session_manager = SessionManager()
        atexit.register(_session_manager.stop_all)
    return _session_manager


import signal  # noqa: E402 — needed for send_break

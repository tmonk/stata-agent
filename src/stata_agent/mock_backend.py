"""Mock Stata daemon for test/CI mode — speaks the same NDJSON protocol.

Activated via `stata daemon start --mock`.
Routes incoming commands to canned responses by pattern matching.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import time
import uuid
from pathlib import Path
from typing import Any, Optional

RESPONSES_DIR = Path(__file__).resolve().parent.parent.parent / "features" / "09-mock-test-mode" / "responses"


def _load_canned_responses() -> dict[str, dict[str, Any]]:
    """Load all canned response text files into a dict keyed by command pattern."""
    responses: dict[str, dict[str, Any]] = {}

    if not RESPONSES_DIR.exists():
        return responses

    file_map: dict[str, str] = {
        "display_1plus1.txt": ". display 1+1\n",
        "sysuse_auto.txt": "sysuse auto, clear",
        "describe_auto.txt": "describe",
        "summarize_auto.txt": "summarize price mpg",
        "reg_price_mpg.txt": "reg price mpg",
        "error_111.txt": "error 111",
        "capture_error_111.txt": "capture error 111",
        "assert_failure.txt": "capture assert 1==0",
        "tabulate_rep78.txt": "tab rep78",
    }

    for filename, command in file_map.items():
        filepath = RESPONSES_DIR / filename
        if filepath.exists():
            text = filepath.read_text(encoding="utf-8")
            responses[command] = {
                "output": text,
                "success": "r(" not in text.splitlines()[-1] if text.splitlines() else True,
            }

    return responses


_CANNED = _load_canned_responses()

# State machine for mock sessions
_session_state: dict[str, dict[str, Any]] = {}


def _get_state(session: str = "default") -> dict[str, Any]:
    if session not in _session_state:
        _session_state[session] = {
            "dataset": None,
            "vars": [],
            "obs": 0,
            "graphs": [],
            "last_rc": 0,
        }
    return _session_state[session]


def _normalize_command(code: str) -> str:
    """Normalize a Stata command for matching."""
    return " ".join(code.strip().split())


def _route_command(code: str, session: str = "default") -> dict[str, Any]:
    """Route a command to its response."""
    norm = _normalize_command(code)
    state = _get_state(session)

    # Exact match first
    if norm in _CANNED:
        entry = _CANNED[norm]
        output = entry["output"]

        # Update state for known commands
        if "sysuse auto" in norm:
            state["dataset"] = "auto"
            state["vars"] = [
                "make", "price", "mpg", "rep78", "headroom", "trunk",
                "weight", "length", "turn", "displacement", "gear_ratio", "foreign",
            ]
            state["obs"] = 74
        elif norm == "describe":
            pass  # state already tracked
        elif norm == "reg price mpg":
            pass
        elif norm == "summarize price mpg":
            pass
        elif "error 111" in norm and "capture" not in norm:
            state["last_rc"] = 111

        rc = 111 if "r(" in output.splitlines()[-1] if output.splitlines() else "" else 0
        return {
            "ok": rc == 0,
            "rc": rc,
            "stdout": output,
            "error": f"Stata error r({rc})" if rc else None,
            "log_path": f"/tmp/mock_{session}.log",
        }

    # Prefix matching for display expressions
    if norm.startswith("display ") or norm.startswith("di "):
        expr = norm.split(maxsplit=1)[1] if " " in norm else ""
        # Try to evaluate simple expressions
        try:
            # Remove quotes for evaluation
            val = expr.strip('"').strip("'")
            result = val
            return {
                "ok": True,
                "rc": 0,
                "stdout": f". {code}\n{result}\n",
                "log_path": f"/tmp/mock_{session}.log",
            }
        except Exception:
            return {
                "ok": True,
                "rc": 0,
                "stdout": f". {code}\n{expr}\n",
                "log_path": f"/tmp/mock_{session}.log",
            }

    # graph dir, memory
    if "graph dir" in norm:
        graphs = state.get("graphs", [])
        if not graphs:
            return {"ok": True, "rc": 0, "stdout": "", "log_path": f"/tmp/mock_{session}.log"}
        return {
            "ok": True,
            "rc": 0,
            "stdout": "  " + "  ".join(graphs),
            "log_path": f"/tmp/mock_{session}.log",
        }

    # graph export
    if "graph export" in norm:
        return {"ok": True, "rc": 0, "stdout": f"(file written in PNG format)", "log_path": f"/tmp/mock_{session}.log"}

    # generate
    if norm.startswith("gen ") or norm.startswith("generate "):
        return {"ok": True, "rc": 0, "stdout": f". {code}\n", "log_path": f"/tmp/mock_{session}.log"}

    # set more off — no output
    if norm.startswith("set "):
        return {"ok": True, "rc": 0, "stdout": "", "log_path": f"/tmp/mock_{session}.log"}

    # log using / log close
    if norm.startswith("log "):
        return {"ok": True, "rc": 0, "stdout": "", "log_path": f"/tmp/mock_{session}.log"}

    # Default: accept as valid but unknown
    return {
        "ok": True,
        "rc": 0,
        "stdout": f". {code}\n",
        "log_path": f"/tmp/mock_{session}.log",
    }


class MockJsonProtocol:
    """NDJSON protocol handler for the mock daemon."""

    def __init__(self, daemon: "MockDaemon"):
        self.daemon = daemon
        self.buf = ""
        self.transport = None

    def connection_made(self, transport):
        self.transport = transport

    def data_received(self, data: bytes):
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

    async def _handle(self, req: dict):
        method = req.get("method")
        msg_id = req.get("id", uuid.uuid4().hex)
        args = req.get("args", {})

        try:
            result = await self.daemon.dispatch(method, args)
            self._send({"id": msg_id, "ok": True, "result": result})
        except Exception as e:
            self._send({"id": msg_id, "ok": False, "error": str(e), "error_code": "INTERNAL_ERROR"})

    def _send(self, payload: dict):
        if self.transport:
            self.transport.write((json.dumps(payload) + "\n").encode("utf-8"))


class MockDaemon:
    """Mock daemon that routes commands to canned responses."""

    def __init__(self, session_name: str = "default"):
        self.session_name = session_name
        self.sock_path: Optional[Path] = None
        self.port: Optional[int] = None
        self._shutdown_event = asyncio.Event()

    async def start(self):
        cache_dir = Path.home() / ".cache" / "mcp-stata" / "sessions"
        cache_dir.mkdir(parents=True, exist_ok=True)

        import sys
        if sys.platform == "win32":
            server = await asyncio.get_event_loop().create_server(
                lambda: MockJsonProtocol(self), "127.0.0.1", 0
            )
            self.port = server.sockets[0].getsockname()[1]
            meta = {"transport": "tcp", "host": "127.0.0.1", "port": self.port}
        else:
            self.sock_path = cache_dir / f"{self.session_name}.sock"
            self.sock_path.unlink(missing_ok=True)
            server = await asyncio.get_event_loop().create_unix_server(
                lambda: MockJsonProtocol(self), str(self.sock_path)
            )
            meta = {"transport": "unix", "path": str(self.sock_path)}

        meta_path = cache_dir / f"{self.session_name}.json"
        meta_path.write_text(json.dumps(meta))

        print(f"Mock daemon listening on {json.dumps(meta)}", flush=True)
        await self._shutdown_event.wait()
        server.close()
        await server.wait_closed()
        if self.sock_path:
            self.sock_path.unlink(missing_ok=True)
        meta_path.unlink(missing_ok=True)

    async def dispatch(self, method: str, args: dict) -> dict:
        session = args.get("session", self.session_name)

        if method == "run":
            code = args.get("code", "")
            result = _route_command(code, session)
            return result

        elif method == "break":
            return {"acknowledged": True, "worker_restarted": True, "note": "Session state has been reset after break"}

        elif method == "health":
            return {"status": "running", "pid": os.getpid(), "session_name": self.session_name}

        elif method == "stop":
            self._shutdown_event.set()
            return {"acknowledged": True}

        elif method == "inspect":
            action = args.get("action", "")
            if action == "describe":
                return {"text": _CANNED.get("describe", {}).get("output", ""), "variables": [], "dataset": {}}
            elif action == "summary":
                return {"variables": {}}
            elif action == "list":
                return {"rows": [], "total_obs": 0, "returned": 0}
            else:
                return {"text": ""}

        elif method == "graph_list":
            state = _get_state(session)
            return {"graph_names": state.get("graphs", [])}

        elif method == "results":
            return {"stored_results": {}}

        elif method == "log_tail":
            return {"text": ""}

        elif method == "log_errors":
            return {"rc": None, "message": "", "context": ""}

        elif method == "help":
            return {"text": f"Help for {args.get('topic', '')}"}

        else:
            raise ValueError(f"Unknown method: {method}")


def main():
    """Entry point for mock daemon subprocess."""
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="Mock Stata daemon")
    parser.add_argument("--session", default="default")
    args = parser.parse_args()

    daemon = MockDaemon(session_name=args.session)

    async def run():
        await daemon.start()

    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

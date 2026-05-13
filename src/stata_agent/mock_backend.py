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
        "display_1plus1.txt": "display 1+1",
        "sysuse_auto.txt": "sysuse auto",
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
            "dataset": {},
            "vars": [],
            "obs": 0,
            "graphs": [],
            "last_rc": 0,
            "statest_scalars": {},
        }
    return _session_state[session]


def _normalize_command(code: str) -> str:
    """Normalize a Stata command for matching."""
    return " ".join(code.strip().split())


def _route_command(code: str, session: str = "default") -> dict[str, Any]:
    """Route a command to its response."""
    norm = _normalize_command(code)
    state = _get_state(session)

    # Exact match first, then prefix match (e.g., "sysuse auto, clear" matches "sysuse auto")
    entry = _CANNED.get(norm)
    if entry is None:
        for pattern in sorted(_CANNED, key=len, reverse=True):
            if norm.startswith(pattern):
                entry = _CANNED[pattern]
                break
    if entry is not None:
        output = entry["output"]

        # Update state for known commands
        if "sysuse auto" in norm:
            state["dataset"] = {
                "name": "auto",
                "observations": 74,
                "variables": [
                    {"name": "make", "type": "str18", "label": "Make and Model"},
                    {"name": "price", "type": "int", "label": "Price"},
                    {"name": "mpg", "type": "int", "label": "Mileage (mpg)"},
                    {"name": "rep78", "type": "int", "label": "Repair Record 1978"},
                    {"name": "headroom", "type": "float", "label": "Headroom (in.)"},
                    {"name": "trunk", "type": "int", "label": "Trunk space (cu. ft.)"},
                    {"name": "weight", "type": "int", "label": "Weight (lbs.)"},
                    {"name": "length", "type": "int", "label": "Length (in.)"},
                    {"name": "turn", "type": "int", "label": "Turn Circle (ft.)"},
                    {"name": "displacement", "type": "int", "label": "Displacement (cu. in.)"},
                    {"name": "gear_ratio", "type": "float", "label": "Gear Ratio"},
                    {"name": "foreign", "type": "byte", "label": "Car type"},
                ],
            }
        elif norm == "describe":
            pass  # state already tracked
        elif norm == "reg price mpg":
            pass
        elif norm == "summarize price mpg":
            pass
        elif "error 111" in norm and "capture" not in norm:
            state["last_rc"] = 111

        rc = 111 if "r(" in (output.splitlines()[-1] if output.splitlines() else "") else 0
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


class MockJsonProtocol(asyncio.Protocol):
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
        cache_dir = Path.home() / ".cache" / "stata-agent" / "sessions"
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
            if args.get("background"):
                import uuid
                return {"task_id": uuid.uuid4().hex, "status": "running"}
            result = _route_command(code, session)
            return result

        elif method == "run_file":
            path = args.get("path", "")
            fname = os.path.basename(path) if path else ""
            # Handle statest failure simulations by filename pattern
            state = _get_state(session)

            failure_map = {
                "fail_assert_scalar_fail": {
                    "statest_assertion_index": 1.0,
                    "statest_command": "st_assert_scalar",
                    "statest_variable": "",
                    "statest_actual": 6165.257,
                    "statest_expected": 5000.0,
                    "statest_tolerance": 0.0,
                },
                "fail_assert_macro_fail": {
                    "statest_assertion_index": 1.0,
                    "statest_command": "st_assert_macro",
                    "statest_variable": "",
                    "statest_actual_str": "regress",
                    "statest_expected_str": "summarize",
                },
                "fail_assert_matrix_fail": {
                    "statest_assertion_index": 1.0,
                    "statest_command": "st_assert_matrix",
                    "statest_variable": "A",
                    "statest_tolerance": 0.0,
                    "statest_error": "Matrix dimensions mismatch",
                },
                "fail_assert_rc_fail": {
                    "statest_assertion_index": 1.0,
                    "statest_command": "st_assert_rc",
                    "statest_variable": "use nonexistent.dta",
                    "statest_actual": 601.0,
                    "statest_expected": 0.0,
                    "statest_tolerance": 0.0,
                },
                "fail_assert_scalar_tol_fail": {
                    "statest_assertion_index": 1.0,
                    "statest_command": "st_assert_scalar",
                    "statest_variable": "",
                    "statest_actual": 6165.2568,
                    "statest_expected": 6165.0,
                    "statest_tolerance": 0.0001,
                },
                "fail_failure_capture": {
                    "statest_assertion_index": 1.0,
                    "statest_command": "st_assert_scalar",
                    "statest_variable": "",
                    "statest_actual": 1.0,
                    "statest_expected": 2.0,
                    "statest_tolerance": 0.0,
                },
                "fail_teardown_runs_on_fail": {
                    "statest_assertion_index": 1.0,
                    "statest_command": "st_assert_scalar",
                    "statest_variable": "",
                    "statest_actual": 1.0,
                    "statest_expected": 0.0,
                    "statest_tolerance": 0.0,
                },
            }

            for pattern, scalars in failure_map.items():
                if pattern in fname:
                    state["statest_scalars"] = scalars.copy()
                    state["last_rc"] = 9
                    return {
                        "ok": False,
                        "rc": 9,
                        "stdout": f"assertion failure: expected {scalars.get('statest_expected', '?')}, got {scalars.get('statest_actual', '?')}",
                        "log_path": f"/tmp/mock_{session}.log",
                        "error": "Assertion failure (rc=9)",
                    }

            return _route_command("", session)

        elif method == "break":
            return {"acknowledged": True, "worker_restarted": True, "note": "Session state has been reset after break"}

        elif method == "health":
            return {"status": "ok", "pid": os.getpid(), "session_name": self.session_name}

        elif method == "stop":
            session_arg = args.get("session", "")
            if session_arg:
                # Session-specific stop — don't shut down, just acknowledge
                state = _get_state(session_arg)
                state["statest_scalars"] = {}
                return {"acknowledged": True}
            self._shutdown_event.set()
            return {"acknowledged": True}

        elif method == "inspect_describe":
            state = _get_state(session)
            dataset = state.get("dataset", {})
            return {"text": "", "variables": dataset.get("variables", []), "dataset": dataset, "obs_count": dataset.get("observations", 0), "var_count": len(dataset.get("variables", []))}

        elif method == "inspect_summary":
            return {"text": ""}

        elif method == "inspect_codebook":
            return {"text": ""}

        elif method == "inspect_list":
            return {"text": "", "rows": [], "total_obs": 0, "returned": 0}

        elif method == "inspect_get":
            # Create a mock export file so the client can read it
            out_path = args.get("out_path", f"/tmp/mock_{session}_export.csv")
            try:
                Path(out_path).parent.mkdir(parents=True, exist_ok=True)
                Path(out_path).write_text("x,s\n1,hello\n.a,\n.z,\n")
                size_bytes = Path(out_path).stat().st_size
            except (OSError, PermissionError):
                return {"path": "", "size_bytes": 0, "error": "cannot write output"}
            return {"path": out_path, "size_bytes": size_bytes}

        elif method == "graph_list":
            state = _get_state(session)
            return {"graph_names": state.get("graphs", [])}

        elif method == "graph_export":
            return {"file_path": f"/tmp/mock_{args.get('name', 'graph')}.{args.get('format', 'pdf')}", "size_bytes": 0}

        elif method == "results":
            state = _get_state(session)
            statest_scalars = state.get("statest_scalars", {})
            if statest_scalars:
                return {"stored_results": {"scalars": statest_scalars}}
            return {"stored_results": {}}

        elif method == "log_tail":
            return {"text": ""}

        elif method == "log_errors":
            return {"rc": None, "message": "", "context": ""}

        elif method == "log_search":
            return {"matches": []}

        elif method == "log_path":
            return {"log_path": "/tmp/mock_log.log"}

        elif method == "task_status":
            return {"status": "completed", "rc": 0}

        elif method == "task_cancel":
            return {"cancelled": True}

        elif method == "task_list":
            return {"tasks": []}

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

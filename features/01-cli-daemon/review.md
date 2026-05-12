# Feature Review: CLI-Daemon Core Architecture

**Date:** 2026-05-12  
**Feature:** 01-cli-daemon  
**Status:** Review Complete → Ready for Implementation  
**Plan Ref:** plan.md §2.2, §2.3, §2.4, §2.5

---

## 1. Active Stata Verification

### 1.1 Batch Mode (`stata-se -b do /dev/null`)
```
$ stata-se -b do /dev/null
EXIT_CODE: 0
```
**Result:** Works. `-b` creates a plain-text `.log` file in the current working directory (not stdout). The log contains the full Stata banner, license info, and command output.

### 1.2 Batch vs Interactive Modes

| Flag | Behavior | Output |
|------|----------|--------|
| `-b` (batch) | Runs do-file, exits | Creates `.log` (plain text) in CWD |
| `-s` (batch SMCL) | Runs do-file, exits | Creates `.smcl` in CWD |
| `-q` (quiet) | Suppresses banner | Still interactive unless combined with `-b` |
| stdin pipe | `printf '...\nexit\n' \| stata-se -q` | Interactive mode reads stdin, prints to stdout |

**Key finding:** Stata does NOT support direct command-line execution like `-e 'display 1+1'`. It only accepts do-files or interactive stdin. This means the daemon must write code to a temp `.do` file and invoke `do tempfile.do`.

### 1.3 Unix Domain Socket Feasibility
```
$ python3 -c "import socket; s=socket.socket(socket.AF_UNIX, socket.SOCK_STREAM); s.bind('/tmp/test_stata.sock'); print('OK')"
OK
```
**Result:** Unix domain sockets work perfectly on macOS (and will on Linux). On Windows, TCP `127.0.0.1:<port>` fallback is required.

### 1.4 pystata Availability
```
$ python3 -c "import pystata; print(pystata.__file__)"
ModuleNotFoundError: No module named 'pystata'
```
**Result:** `pystata` is NOT available in the system Python (`/Library/Developer/CommandLineTools/usr/bin/python3`). It IS available inside Stata's embedded Python (`which python` from within Stata). The daemon must either:
- Run inside Stata's Python environment (if Stata is started with Python support)
- Use `stata_setup` to configure pystata from an external Python
- Use subprocess-based invocation as a fallback

**Current codebase approach:** `stata_client.py` uses `stata_setup` to configure pystata. This should remain the primary path, but the daemon should gracefully degrade to subprocess mode if pystata is unavailable.

### 1.5 Background Process Test
```bash
$ nohup stata-se -b do test.do > /tmp/test.log 2>&1 & echo $!
53504
```
**Result:** Background batch Stata works. The process detaches correctly. However:
- `-b` writes to a `.log` file in CWD, NOT to stdout/stderr
- The `nohup` redirect captures nothing useful (empty `/tmp/test.log`)
- This confirms that for a daemon to capture output, it must either:
  1. Read the `.log`/`.smcl` file after Stata exits (stateless), OR
  2. Use pystata/SFI to run commands in-process (stateful)

**Implication:** The daemon MUST use pystata for session-oriented stateful execution. Subprocess batch mode destroys state between invocations.

---

## 2. Architecture Description

### 2.1 Component Diagram (Text-Based)

```
┌─────────────────────────────────────────────────────────────────────┐
│  User / Agent Environment                                           │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐                 │
│  │ SKILL.md    │  │ SKILL.md    │  │ SKILL.md    │  ...            │
│  │ stata-run   │  │ stata-inspect│  │ stata-graph │                 │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘                 │
│         └─────────────────┴─────────────────┘                       │
│                           │                                         │
│                    ┌──────┴──────┐                                  │
│                    │  `stata`    │  CLI binary (Python entry point)│
│                    │  CLI front  │  • argparse subcommands         │
│                    │  end        │  • thin wrapper over RPC        │
│                    └──────┬──────┘                                  │
└───────────────────────────┼─────────────────────────────────────────┘
                            │  NDJSON over Unix socket / TCP
              ┌─────────────┴─────────────┐
              │    `stata-daemon`         │
              │    (1 per user)           │
              │    • Process manager      │
              │    • NDJSON router        │
              │    • Unix socket server   │
              └──────┬────────────┬───────┘
                     │            │
           ┌─────────┘            └──────────┐
           │                                 │
    ┌──────┴──────┐                 ┌────────┴────────┐
    │  StataWorker │                 │  StataWorker    │
    │  (default)   │                 │  (named session)│
    │  • pystata   │                 │  • pystata      │
    │  • stateful  │                 │  • stateful     │
    └──────┬───────┘                 └────────┬────────┘
           │                                  │
    ┌──────┴──────┐                    ┌─────┴─────┐
    │   Stata     │                    │   Stata   │
    │   Engine    │                    │   Engine  │
    └─────────────┘                    └───────────┘
```

### 2.2 Data Flow

#### Flow A: `stata run "reg price mpg"` (synchronous)

```
1. User runs: stata run --echo "reg price mpg"
2. cli.py parses args → constructs NDJSON request
3. rpc_client.py connects to ~/.cache/mcp-stata/sessions/default.sock
4. Sends: {"id":"abc123","method":"run","args":{"code":"reg price mpg","echo":true}}
5. daemon.py receives on socket, routes to StataWorker(default)
6. StataWorker runs code via pystata, captures output
7. Worker sends result back to daemon
8. Daemon writes NDJSON response to socket
9. rpc_client.py reads response, returns dict to cli.py
10. cli.py formats stdout (markdown), prints to terminal
```

#### Flow B: `stata daemon start` (lifecycle)

```
1. User runs: stata daemon start [--session NAME]
2. cli.py checks if socket already exists
3. If not, forks/spawns daemon.py process
4. daemon.py creates Unix socket at ~/.cache/mcp-stata/sessions/<name>.sock
5. daemon.py writes metadata to ~/.cache/mcp-stata/sessions/<name>.json
6. daemon.py spawns StataWorker process (or thread) with pystata
7. Worker initializes Stata, reports "ready"
8. daemon.py enters select()/asyncio event loop, listens for connections
9. cli.py polls socket until ready, prints success message
```

#### Flow C: `stata run --background` (async task)

```
1. cli.py sends request with `"background": true`
2. daemon.py creates Task record, assigns task_id
3. daemon.py dispatches to worker but does NOT wait for completion
4. cli.py immediately receives: `{"ok":true,"task_id":"...","status":"running"}`
5. Agent polls: stata task status --task-id <id>
6. daemon.py returns current task state from in-memory task registry
7. On completion, task registry updated with result + log_path
```

### 2.3 Protocol Specification

#### Transport
- **macOS/Linux:** Unix domain socket at `~/.cache/mcp-stata/sessions/<session_name>.sock`
- **Windows:** TCP `127.0.0.1:<port>` (ephemeral or specified)
- **Metadata:** `~/.cache/mcp-stata/sessions/<session_name>.json` contains `{"transport":"unix","path":"..."}` or `{"transport":"tcp","host":"127.0.0.1","port":...}`

#### Wire Format: NDJSON
Every message is a single line of JSON terminated by `\n`. No HTTP headers, no framing length prefixes.

**Request envelope:**
```json
{
  "id": "<uuid>",
  "method": "run|inspect|graph|results|log|break|stop",
  "args": { "method-specific": "payload" }
}
```

**Response envelope (success):**
```json
{
  "id": "<uuid>",
  "ok": true,
  "result": { "method-specific": "payload" }
}
```

**Response envelope (error):**
```json
{
  "id": "<uuid>",
  "ok": false,
  "error": "Human-readable message",
  "error_code": "WORKER_CRASH|TIMEOUT|STATA_ERROR|INVALID_METHOD",
  "details": { "optional": "context" }
}
```

**Streaming notification (from daemon to client, for long-running tasks):**
```json
{"event": "progress", "task_id": "...", "percent": 45, "message": "Bootstrap rep 4500/10000"}
{"event": "log_chunk", "task_id": "...", "text": "..."}
{"event": "done", "task_id": "...", "rc": 0, "log_path": "/path/to/log"}
```

#### Supported Methods

| Method | Args | Returns |
|--------|------|---------|
| `run` | `code`, `echo`, `background`, `max_output_tokens` | `stdout`, `rc`, `log_path`, `graphs[]` |
| `run_file` | `path`, `echo`, `background` | same as `run` |
| `break` | — | `acknowledged: bool` |
| `inspect_describe` | — | `dataset_state` |
| `inspect_summary` | `varlist` | `summary_text` |
| `inspect_list` | `varlist`, `from`, `count` | `rows[]` |
| `inspect_get` | `format`, `out_path` | `file_path` |
| `results` | `class` (r/e/s) | `stored_results` |
| `graph_list` | — | `graph_names[]` |
| `graph_export` | `name`, `format`, `out_path` | `file_path` |
| `log_tail` | `lines`, `bytes` | `text` |
| `log_search` | `pattern`, `offset`, `max_bytes` | `matches[]`, `next_offset` |
| `log_errors` | `context_lines` | `error_text` |
| `health` | — | `status`, `pid`, `session_name` |
| `stop` | — | `acknowledged` |

### 2.4 Session Model

- **1 daemon process** per user (not per agent). The daemon owns a process manager.
- **1 StataWorker** per named session. Default session is `"default"`.
- **Workers are reused** across CLI invocations, preserving Stata state (`use auto`, then `reg price mpg`).
- **Worker lifecycle:**
  1. Spawned on first `stata run` (auto-start) or explicit `stata daemon start`
  2. Initializes pystata + Stata engine
  3. Listens for commands from daemon via in-process queue (or pipe if subprocess)
  4. On `stata daemon stop`, worker gracefully exits Stata, daemon closes socket
  5. On daemon crash, `atexit` handlers in worker kill Stata process
- **Idle timeout:** Daemon auto-shutdown after configurable idle time (default 30 min). Workers are terminated when daemon exits.
- **No history snapshots, no diff tracking.** The agent can diff output itself. (Eliminates ~400 lines from current `sessions.py`.)

---

## 3. Basic Pseudo-Code

### 3.1 `cli.py` — Entry Point

```python
#!/usr/bin/env python3
"""stata CLI — single entry point with subcommands."""
import argparse
import sys
import os
from pathlib import Path

from mcp_stata.rpc_client import RpcClient
from mcp_stata.discovery import discover_stata


def cmd_daemon_start(args):
    # Check if already running
    session_name = args.session or "default"
    sock_path = Path.home() / ".cache/mcp-stata/sessions" / f"{session_name}.sock"
    if sock_path.exists():
        print(f"Daemon already running for session '{session_name}'")
        return 0

    # Fork/spawn daemon process
    import subprocess
    daemon_script = Path(__file__).with_name("daemon.py")
    env = os.environ.copy()
    env["MCP_STATA_SESSION"] = session_name
    if args.port:
        env["MCP_STATA_PORT"] = str(args.port)

    proc = subprocess.Popen(
        [sys.executable, str(daemon_script), "--session", session_name],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        start_new_session=True,
    )

    # Poll until socket appears or timeout
    for _ in range(50):  # 5 seconds
        if sock_path.exists():
            print(f"Daemon started (PID {proc.pid}) for session '{session_name}'")
            return 0
        import time
        time.sleep(0.1)
    print("Daemon failed to start within timeout")
    return 1


def cmd_daemon_stop(args):
    client = RpcClient(session=args.session or "default")
    try:
        client.call("stop", {})
    except Exception:
        pass
    # Clean up socket file
    sock_path = Path.home() / ".cache/mcp-stata/sessions" / f"{args.session or 'default'}.sock"
    sock_path.unlink(missing_ok=True)
    print(f"Daemon stopped for session '{args.session or 'default'}'")
    return 0


def cmd_run(args):
    client = RpcClient(session=args.session or "default")
    # Auto-start daemon if not running
    if not client.is_alive():
        print("Daemon not running, starting default session...", file=sys.stderr)
        cmd_daemon_start(argparse.Namespace(session=args.session or "default", port=0))
        client = RpcClient(session=args.session or "default")

    code = args.code
    if args.file:
        code = Path(args.file).read_text()

    result = client.call("run", {
        "code": code,
        "echo": args.echo,
        "background": args.background,
        "max_output_tokens": args.max_output_tokens,
    })

    if args.json:
        import json
        print(json.dumps(result))
    else:
        if result.get("rc", 0) != 0:
            print(f"[stata] ✗ Failed (rc={result['rc']})")
            if "error" in result:
                print(f"[stata] Error: {result['error']}")
            if "error_context" in result:
                print(result["error_context"])
        else:
            print(f"[stata] ✓ Completed (rc=0)")
            if result.get("truncated"):
                print(f"[stata] Output truncated. Full log: {result['log_path']}")
            if result.get("stdout"):
                print(result["stdout"])
        if result.get("graphs"):
            print(f"[stata] Graphs: {', '.join(result['graphs'])}")
    return result.get("rc", 0)


def main():
    parser = argparse.ArgumentParser(prog="stata")
    subparsers = parser.add_subparsers(dest="command")

    # daemon
    daemon = subparsers.add_parser("daemon", help="Daemon lifecycle")
    daemon_sub = daemon.add_subparsers(dest="daemon_cmd")
    d_start = daemon_sub.add_parser("start")
    d_start.add_argument("--session", default="default")
    d_start.add_argument("--port", type=int, default=0)
    d_stop = daemon_sub.add_parser("stop")
    d_stop.add_argument("--session", default="default")
    d_status = daemon_sub.add_parser("status")
    d_status.add_argument("--session", default="default")

    # run
    run = subparsers.add_parser("run", help="Run Stata code")
    run.add_argument("--session", default="default")
    run.add_argument("--echo", action="store_true", default=True)
    run.add_argument("--background", action="store_true")
    run.add_argument("--file")
    run.add_argument("--json", action="store_true")
    run.add_argument("--max-output-tokens", type=int, default=1000)
    run.add_argument("code", nargs="?", default="")

    # ... (inspect, graph, log, results, help, lint, doctor)

    args = parser.parse_args()
    if args.command == "daemon":
        if args.daemon_cmd == "start":
            return cmd_daemon_start(args)
        elif args.daemon_cmd == "stop":
            return cmd_daemon_stop(args)
    elif args.command == "run":
        return cmd_run(args)
    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main())
```

### 3.2 `daemon.py` — NDJSON Server

```python
#!/usr/bin/env python3
"""stata-daemon — session-oriented Stata host speaking NDJSON."""
import asyncio
import json
import os
import signal
import sys
import uuid
from pathlib import Path
from typing import Dict, Optional

from mcp_stata.sessions import SessionManager  # refactored, slimmed


class JsonProtocol(asyncio.Protocol):
    def __init__(self, daemon: "StataDaemon"):
        self.daemon = daemon
        self.buf = ""

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
        self.transport.write((json.dumps(payload) + "\n").encode("utf-8"))


class StataDaemon:
    def __init__(self, session_name: str = "default", transport: str = "unix"):
        self.session_name = session_name
        self.transport = transport
        self.sock_path: Optional[Path] = None
        self.port: Optional[int] = None
        self.session_manager = SessionManager()
        self._shutdown_event = asyncio.Event()
        self._tasks: Dict[str, dict] = {}  # background task registry

    async def start(self):
        cache_dir = Path.home() / ".cache/mcp-stata/sessions"
        cache_dir.mkdir(parents=True, exist_ok=True)

        if self.transport == "unix":
            self.sock_path = cache_dir / f"{self.session_name}.sock"
            self.sock_path.unlink(missing_ok=True)
            server = await asyncio.get_event_loop().create_unix_server(
                lambda: JsonProtocol(self), str(self.sock_path)
            )
            meta = {"transport": "unix", "path": str(self.sock_path)}
        else:
            server = await asyncio.get_event_loop().create_server(
                lambda: JsonProtocol(self), "127.0.0.1", 0
            )
            self.port = server.sockets[0].getsockname()[1]
            meta = {"transport": "tcp", "host": "127.0.0.1", "port": self.port}

        meta_path = cache_dir / f"{self.session_name}.json"
        meta_path.write_text(json.dumps(meta))

        # Initialize default session worker
        await self.session_manager.get_or_create_session(self.session_name)

        print(f"Daemon listening on {meta}", flush=True)

        # Graceful shutdown
        for sig in (signal.SIGINT, signal.SIGTERM):
            asyncio.get_event_loop().add_signal_handler(sig, self._shutdown_event.set)

        await self._shutdown_event.wait()
        server.close()
        await server.wait_closed()
        await self.session_manager.stop_all()
        meta_path.unlink(missing_ok=True)
        if self.sock_path:
            self.sock_path.unlink(missing_ok=True)

    async def dispatch(self, method: str, args: dict) -> dict:
        session = await self.session_manager.get_or_create_session(self.session_name)

        if method == "run":
            if args.get("background"):
                task_id = uuid.uuid4().hex
                self._tasks[task_id] = {"status": "running", "result": None}
                asyncio.create_task(self._background_run(session, task_id, args))
                return {"task_id": task_id, "status": "running"}
            else:
                return await session.call("run_command", args)

        elif method == "break":
            await session.send_break()
            return {"acknowledged": True}

        elif method == "stop":
            await session.stop()
            self._shutdown_event.set()
            return {"acknowledged": True}

        elif method == "health":
            info = session.get_info()
            return {"status": info.status, "pid": info.pid, "session": self.session_name}

        elif method in ("inspect_describe", "inspect_summary", "inspect_list",
                        "inspect_get", "results", "graph_list", "graph_export",
                        "log_tail", "log_search", "log_errors"):
            # Delegate directly to worker via session.call
            return await session.call(method, args)

        else:
            raise ValueError(f"Unknown method: {method}")

    async def _background_run(self, session, task_id: str, args: dict):
        try:
            result = await session.call("run_command", {**args, "background": False})
            self._tasks[task_id] = {"status": "done", "result": result}
        except Exception as e:
            self._tasks[task_id] = {"status": "failed", "error": str(e)}


def main():
    session = os.environ.get("MCP_STATA_SESSION", "default")
    port = os.environ.get("MCP_STATA_PORT")
    transport = "tcp" if port else "unix"
    daemon = StataDaemon(session_name=session, transport=transport)
    asyncio.run(daemon.start())


if __name__ == "__main__":
    main()
```

### 3.3 `rpc_client.py` — NDJSON Client

```python
"""Thin NDJSON client for the stata daemon."""
import json
import socket
import sys
from pathlib import Path
from typing import Any, Dict, Optional


class RpcClient:
    def __init__(self, session: str = "default"):
        self.session = session
        self.meta = self._load_meta()
        self._sock: Optional[socket.socket] = None

    def _load_meta(self) -> Dict[str, Any]:
        path = Path.home() / ".cache/mcp-stata/sessions" / f"{self.session}.json"
        if path.exists():
            return json.loads(path.read_text())
        return {}

    def is_alive(self) -> bool:
        try:
            self._connect()
            self._send({"id": "ping", "method": "health", "args": {}})
            resp = self._recv()
            return resp.get("ok", False)
        except Exception:
            return False
        finally:
            self._disconnect()

    def call(self, method: str, args: Dict[str, Any]) -> Dict[str, Any]:
        self._connect()
        try:
            req = {"id": f"{method}_{id(args)}", "method": method, "args": args}
            self._send(req)
            return self._recv()
        finally:
            self._disconnect()

    def _connect(self):
        if self._sock:
            return
        if self.meta.get("transport") == "unix":
            self._sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self._sock.connect(self.meta["path"])
        else:
            self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._sock.connect((self.meta.get("host", "127.0.0.1"), self.meta.get("port", 0)))

    def _disconnect(self):
        if self._sock:
            self._sock.close()
            self._sock = None

    def _send(self, payload: dict):
        self._sock.sendall((json.dumps(payload) + "\n").encode("utf-8"))

    def _recv(self) -> dict:
        buf = b""
        while b"\n" not in buf:
            chunk = self._sock.recv(4096)
            if not chunk:
                raise ConnectionError("Daemon closed connection")
            buf += chunk
        line, _ = buf.split(b"\n", 1)
        return json.loads(line.decode("utf-8"))
```

### 3.4 Worker Spawn (Refactored from `sessions.py` + `worker.py`)

The current architecture uses `multiprocessing.spawn` with a `multiprocessing.connection.Pipe`. In the new architecture, we have two options:

**Option A: Keep Pipe (simpler, reuse existing code)**
- `StataSession` spawns a worker process via `multiprocessing.spawn`
- Worker uses `Pipe` to communicate with daemon
- Daemon's `JsonProtocol` translates socket NDJSON → Pipe messages
- **Pros:** Minimal changes to `worker.py`, battle-tested
- **Cons:** Two IPC layers (socket + pipe)

**Option B: In-Process Worker (daemon thread)**
- Daemon creates one `StataClient` instance per session in a dedicated thread
- No separate process, no pipe
- Daemon calls `StataClient` methods directly
- **Pros:** Simpler IPC, easier break handling, lower latency
- **Cons:** `pystata` is not always thread-safe; Stata may block the GIL

**Recommendation:** Start with **Option A** (pipe-based worker) because:
1. The current `worker.py` already works
2. `pystata`/`sfi` has known thread-safety limitations
3. The pipe abstraction isolates Stata crashes from the daemon

**Refactored slim session manager (pseudo-code):**

```python
class StataSession:
    """Lightweight session wrapper. No history, no diff, no snapshots."""
    def __init__(self, session_id: str):
        self.id = session_id
        self.status = "starting"
        self._parent_conn, self._child_conn = Pipe()
        self._process = Process(target=_worker_main, args=(self._child_conn,))
        self._process.start()
        self._pending: Dict[str, asyncio.Future] = {}
        self._listener = asyncio.create_task(self._listen())

    async def _listen(self):
        loop = asyncio.get_running_loop()
        while True:
            if await loop.run_in_executor(None, self._parent_conn.poll, 0.2):
                msg = await loop.run_in_executor(None, self._parent_conn.recv)
                msg_id = msg.get("id")
                if msg.get("event") == "ready":
                    self.status = "running"
                elif msg.get("event") == "result" and msg_id in self._pending:
                    self._pending[msg_id].set_result(msg.get("result"))
                elif msg.get("event") == "error" and msg_id in self._pending:
                    self._pending[msg_id].set_exception(RuntimeError(msg.get("message")))

    async def call(self, method: str, args: dict) -> Any:
        msg_id = uuid.uuid4().hex
        future = asyncio.get_running_loop().create_future()
        self._pending[msg_id] = future
        self._parent_conn.send({"type": method, "id": msg_id, "args": args})
        return await future

    async def send_break(self):
        self._parent_conn.send({"type": "break"})

    async def stop(self):
        self._parent_conn.send({"type": "stop"})
        self._process.join(timeout=5)
        if self._process.is_alive():
            self._process.kill()
```

---

## 4. Key Design Decisions & Risks

### 4.1 pystata vs Subprocess

| Aspect | pystata (in-process) | Subprocess batch |
|--------|---------------------|------------------|
| Session state | ✅ Preserved | ❌ Destroyed each run |
| Speed | ✅ Fast (<1s warm) | ❌ Slow (~2–3s startup) |
| Break/cancel | ✅ `sfi.breakIn()` | ❌ `kill -9` only |
| Availability | ❌ Requires `stata_setup` | ✅ Always works |
| Graph capture | ✅ Via SFI | ❌ Must scan disk |
| Daemon dependency | ❌ Must run inside configured Python | ✅ Any Python |

**Decision:** Primary path is pystata. Subprocess fallback can be added later for environments without pystata.

### 4.2 Transport: Unix Socket vs TCP

- **Unix sockets** are faster, use file permissions, and leave no open TCP ports.
- **TCP localhost** is required for Windows (no native Unix socket support in older Python/Windows versions, though Windows 10 1803+ supports AF_UNIX).
- **Decision:** Use Unix socket on macOS/Linux, TCP on Windows. Auto-detect at daemon start.

### 4.3 Worker Isolation

- Each session gets its own worker process. This isolates crashes and preserves state.
- The daemon itself must be lightweight (just an NDJSON router).
- If a worker crashes, the daemon can auto-restart it on the next request.

### 4.4 Log Management

- The daemon writes persistent logs to `~/.cache/mcp-stata/logs/<session>_<timestamp>_<seq>.log`
- Default to **text logs** (`log using ..., text`) to eliminate SMCL cleaning overhead.
- The NDJSON response includes `log_path` but never the full log content.
- See feature `03-text-first-logs` for detailed log mitigation strategy.

### 4.5 Auto-Start Behavior

- `stata run` auto-starts the daemon if not running. This removes the need for `stata_manage_session(action="detect")`.
- Print a warning to stderr when auto-starting so the agent knows what happened.

---

## 5. Implementation Checklist

### Phase 0: Foundation
- [ ] Create `src/mcp_stata/cli.py` with `daemon start/stop` and `run` subcommands
- [ ] Create `src/mcp_stata/daemon.py` with NDJSON Unix socket server
- [ ] Create `src/mcp_stata/rpc_client.py` with NDJSON client
- [ ] Refactor `sessions.py` to remove history/diff/snapshots (keep ~100 lines)
- [ ] Add `stata = "mcp_stata.cli:main"` to `pyproject.toml` `[project.scripts]`
- [ ] Implement `stata run --echo "display 1+1"` E2E test
- [ ] Verify state persistence: `sysuse auto` then `reg price mpg`

### Phase 0.5: Verification Tests
- [ ] `tests/cli/test_daemon_lifecycle.sh` — start, run, stop
- [ ] `tests/cli/test_state_persistence.sh` — two `run` calls sharing state
- [ ] `tests/cli/test_background_task.sh` — `--background` + poll

---

## 6. Supporting Notes

### Note A: Stata Batch Mode Quirks
- `-b` creates `.log` in CWD, not stdout. The daemon must `cd` to a known directory or use absolute paths.
- Stata banner in `-b` mode is ~900 bytes. Use `-q` to suppress when invoking batch fallback.
- Batch mode exits with code 0 even on `r(111)`. Must parse the log for `r(...)`.

### Note B: Python Environment
- System Python is 3.9.6 (below `requires-python = ">=3.11"` in pyproject.toml).
- The project uses `.venv` (visible in directory listing). The daemon must run inside the project's venv where dependencies are installed.
- `pystata` is NOT in the system Python path. It requires Stata's bundled Python or `stata_setup` configuration.

### Note C: Current Entry Point
- Current `pyproject.toml` has `mcp-stata = "mcp_stata.server:main"`.
- Target: add `stata = "mcp_stata.cli:main"` alongside (or replace in Phase 3).
- `__main__.py` currently delegates to `server.main()`. Should be updated to `cli.main()`.

### Note D: Socket Cleanup
- Unix sockets leave filesystem artifacts if the daemon crashes. Use `atexit` and signal handlers to unlink.
- On macOS, `SO_REUSEADDR` does not apply to Unix sockets; always `unlink` before `bind`.

---

*End of review. This architecture is ready for Phase 0 implementation.*

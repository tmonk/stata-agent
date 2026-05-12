# Review: Simplified Session Management

**Date:** 2026-05-12
**Reviewer:** Subagent (review mode)
**Source:** `plan.md` §11.7, `sessions.py` (500 LOC), `worker.py` (323 LOC), live Stata verification tests

---

## 1. Summary

The plan proposes a radical simplification of session management:

| Aspect | Current | Proposed |
|--------|---------|----------|
| Sessions | Named, arbitrary, managed dict | One unnamed default; `--name` for explicit named |
| History | Snapshot-based diff tracking | Removed |
| Profile code | `set_profile()` runs before each command | Removed (user runs `stata run --file setup.do` once) |
| Daemon | No daemon; MCP server owns sessions | Lightweight daemon auto-started on first `stata run` |
| Transport | `multiprocessing.Connection` (pipe) | Unix socket / TCP (NDJSON) |
| **LOC** | `sessions.py` + `worker.py` = **823** | Target: **~250** (70% reduction) |

---

## 2. Verification Test Results

### 2.1 Test 1 — State Persistence Between `-b` Do-Files

**Setup:** `stata-se -b do test1a.do` (`sysuse auto, describe`) then `stata-se -b do test1b.do` (`regress price mpg`).

| Result | Evidence |
|--------|----------|
| **Each `-b` is fully isolated** | `test1b.log` shows: `regress price mpg` → `no variables defined` `r(111)` |
| State does NOT persist | Auto dataset loaded in test1a is gone in test1b |
| **Key takeaway** | `-b` mode is equivalent to running a fresh Stata every time |

**Implication for design:** The daemon must hold the Stata process in a persistent state (via pystata, not batch mode) for commands to share state. This confirms the daemon architecture is necessary.

### 2.2 Test 2 — pystata Availability

| Result | Evidence |
|--------|----------|
| `pystata` is NOT installed | `ModuleNotFoundError: No module named 'pystata'` |
| Stata-se binary IS available | `/usr/local/bin/stata-se` |

**Implication for design:** The simplified session manager must handle pystata absence gracefully. The daemon can fall back to spawning `stata-se -q` via pipe if pystata is missing, or require pystata as a dependency.

### 2.3 Test 3 — Interactive Pipe State Persistence

**Setup:** `echo -e "sysuse auto\nreg price mpg\n" | stata-se -q`

| Result | Evidence |
|--------|----------|
| **State persists within piped stdin** | Both commands executed in one session: `sysuse auto` loaded data, `reg price mpg` ran regression |
| Regression output complete | R² = 0.2196, F(1,72) = 20.26, coefficients correct |

**Implication for design:** Stata's console mode (`-q`) can maintain state across commands if they're fed via stdin within a single process. This confirms the viability of a persistent session held open via a pipe.

### 2.4 Test 4 — Process Isolation

**Setup:** Two simultaneous `stata-se -b` processes — test4a loads auto, test4b loads bpwide.

| Result | Evidence |
|--------|----------|
| **Processes are fully isolated** | Both completed with rc=0 independently |
| No interference | Each saved its own dataset successfully |
| Simultaneous execution works | Both ran concurrently |

**Implication for design:** Running multiple `-b` processes concurrently is safe. For the daemon, if named sessions are used, each named session would get its own worker process (same isolation model).

### 2.5 Test 5 — PID & Process Tree

**Setup:** `stata-se -b do sleepy.do` observed via `ps`.

| Result | Evidence |
|--------|----------|
| `stata-se` spawns as a child of the calling shell | PID chain: bash (62582) → stata-se (62584) |
| Each invocation = one `stata-se` process | No shared process; no daemon reuse |
| Process group is inherited from parent | PGID same as calling bash |

**Implication for design:** The daemon must be a long-lived process that spawns worker processes. The current `multiprocessing.spawn` context already does this. The simplified version should keep this model.

### 2.6 Test 6 — File-Based State Sharing

**Setup:** Two separate `-b` processes (test6a, test6b) read the same saved `dataset_a.dta`.

| Result | Evidence |
|--------|----------|
| **File-based sharing works** | test6a: `count if price > 10000` → 10 |
| | test6b: `count if mpg > 20` → 36 |
| Each process independently reads from disk | Both loaded dataset_a.dta successfully |

**Implication for design:** The filesystem is the natural state-sharing mechanism between sessions. The daemon does not need to provide in-memory data sharing between named sessions; they can read/write `.dta` files.

### 2.7 Test 7 — Socket Communication

**Setup:** Python Unix domain socket server/client exchanging NDJSON.

| Result | Evidence |
|--------|----------|
| **Socket server/client works** | Server received `{"id": "1", "cmd": "sysuse auto"}`, echoed back |
| NDJSON round-trip works | Client received `{"id": "1", "ok": true, "result": "Echo: sysuse auto"}` |
| Socket cleanup works | `os.remove(SOCK_PATH)` on shutdown |

**Implication for design:** The plan's proposed NDJSON-over-Unix-socket transport is viable. No HTTP overhead needed.

---

## 3. Architecture for Simplified Session Management

### 3.1 Proposed Component Layout

```
┌────────────────────────────────────────────┐
│               Agent (Bash)                 │
│  $ stata run "sysuse auto"                 │
└──────────────────┬─────────────────────────┘
                   │
┌──────────────────▼─────────────────────────┐
│         stata CLI (cli.py) ~100 LOC         │
│  • argparse subcommands                     │
│  • connects to daemon socket                │
│  • sends NDJSON, prints result              │
└──────────────────┬─────────────────────────┘
                   │ Unix socket (NDJSON)
┌──────────────────▼─────────────────────────┐
│         stata-daemon (daemon.py) ~150 LOC   │
│  • One daemon per user/agent session        │
│  • Listens on ~/.cache/mcp-stata/sessions/  │
│  • Routes to default or named StataWorker   │
│  • Auto-starts on first "stata run"         │
│  • Idle timeout → shutdown                  │
└──────────────────┬─────────────────────────┘
                   │ multiprocessing.spawn
┌──────────────────▼─────────────────────────┐
│   StataWorker (refactored worker.py) ~100   │
│  • Single Stata process (via pystata)       │
│  • No history snapshots                     │
│  • No profile code                          │
│  • No diff tracking                         │
│  • Only: run_command, file ops, graphs      │
└──────────────────┬─────────────────────────┘
                   │ pystata
┌──────────────────▼─────────────────────────┐
│              Stata instance                 │
│  • Persistent state                         │
│  • Dataset, macros, matrices persist        │
└─────────────────────────────────────────────┘
```

### 3.2 Session Dict (Simplified)

```python
# In-memory state in the daemon
sessions: Dict[str, StataSessionInfo] = {
    "default": {
        "worker": StataWorker(...),
        "pid": 12345,
        "created_at": "...",
        "last_active": "...",
        "status": "running",
    }
    # Named sessions only if explicitly created:
    # "thesis": { ... }
}

# No history snapshots, no diff tracking, no profile_code
```

### 3.3 Worker Spawn (Refactored)

```python
import multiprocessing

ctx = multiprocessing.get_context("spawn")

def spawn_worker(session_name: str) -> StataWorkerHandle:
    """Spawn a new Stata worker process using pystata isolation."""
    parent_conn, child_conn = ctx.Pipe()
    process = ctx.Process(target=_worker_main, args=(child_conn,))
    process.daemon = True
    process.start()
    child_conn.close()  # parent doesn't need child end
    return StataWorkerHandle(
        process=process,
        conn=parent_conn,
        pid=process.pid,
    )
```

### 3.4 Auto-Start Logic

```python
def ensure_daemon_running():
    """Check if daemon socket exists and is alive; if not, start daemon."""
    sock_path = get_socket_path("default")
    if not socket_exists_and_alive(sock_path):
        print("[stata] Starting daemon (background)...", file=stderr)
        subprocess.Popen(
            ["stata", "daemon", "start"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        # Wait for socket to appear
        for _ in range(50):  # 5 second timeout
            if os.path.exists(sock_path):
                return
            time.sleep(0.1)
        raise RuntimeError("Daemon failed to start")
```

### 3.5 Named Session Routing

```python
def route_request(session_name: str, method: str, args: dict) -> dict:
    """Route a command to the appropriate worker via its socket."""
    if session_name not in sessions:
        if session_name == "default":
            spawn_worker("default")
        else:
            raise ValueError(f"Session '{session_name}' not found. "
                           "Create it with 'stata daemon start --name {session_name}'")
    
    worker = sessions[session_name].worker
    msg_id = uuid.uuid4().hex
    worker.conn.send({
        "type": method,
        "id": msg_id,
        "args": args
    })
    # Wait for response (with timeout)
    return worker.conn.recv()
```

### 3.6 What Is Removed

| Feature | Removed | Rationale |
|---------|---------|-----------|
| `_SessionSnapshot` | Yes | No history diff needed |
| `_history` list | Yes | Agent can compare outputs itself |
| `_last_diff_snapshot` | Yes | ~ |
| `profile_code` | Yes | User runs `stata run --file setup.do` explicitly |
| `get_session_diff()` | Yes | ~ |
| `get_history_stats()` | Yes | ~ |
| `_record_post_command_snapshot()` | Yes | ~ |
| `_collect_snapshot()` | Yes | ~ |
| `_prune_history()` | Yes | ~ |
| `_STATEFUL_METHODS` | Yes | All methods are stateful now |
| Log listeners per msg_id | Yes | Simplified: stdout goes to response |
| Progress listeners per msg_id | Yes | Replaced by `--background` polling |
| `_listener_task` | Yes | Sync response instead of async listener |

### 3.7 What Is Preserved

| Feature | Preserved | Rationale |
|---------|-----------|-----------|
| `multiprocessing.spawn` context | Yes | Required for pystata thread safety and Rust compat |
| Pipe/async-worker pattern | Yes (simplified) | Worker process isolation from daemon |
| StataClient integration | Yes | SMCL cleaning, graph detection still needed |
| Session stop/cleanup with atexit | Yes | Prevent zombie processes |
| `startup_do_file` support | Yes (optional) | One-time init on session creation |

---

## 4. Basic Pseudo-Code

### 4.1 Session Dict + Worker Spawn + Auto-Start + Named Routing

```python
# --- daemon.py (simplified) ---

import os
import uuid
import json
import socket
import atexit
import logging
import subprocess
import multiprocessing
from dataclasses import dataclass, field
from typing import Dict, Optional
from multiprocessing.connection import Connection

logger = logging.getLogger("stata.daemon")

ctx = multiprocessing.get_context("spawn")

SOCK_DIR = os.path.expanduser("~/.cache/mcp-stata/sessions")
os.makedirs(SOCK_DIR, exist_ok=True)

@dataclass
class WorkerHandle:
    process: multiprocessing.Process
    conn: Connection
    pid: int
    session_name: str
    created_at: str = ""
    last_active: str = ""

# Global state (daemon process)
sessions: Dict[str, WorkerHandle] = {}

def _worker_main(conn: Connection, session_name: str):
    """Worker process entry point."""
    from mcp_stata.stata_client import StataClient
    client = StataClient()
    client.init()
    
    conn.send({"event": "ready", "pid": os.getpid(), "session": session_name})
    
    while True:
        try:
            if conn.poll(0.1):
                msg = conn.recv()
                if msg.get("type") == "stop":
                    break
                
                # Execute command (simplified — no profile, no snapshot)
                result = client.run_command(
                    msg["args"]["code"],
                    echo=msg["args"].get("echo", True),
                )
                conn.send({
                    "event": "result",
                    "id": msg["id"],
                    "result": result,
                })
        except (EOFError, BrokenPipeError):
            break
        except Exception as e:
            conn.send({"event": "error", "id": msg.get("id"), "message": str(e)})
    
    logger.info(f"Worker [{session_name}] exiting")
    conn.close()

def ensure_default_session() -> WorkerHandle:
    """Auto-start default session if not running."""
    if "default" in sessions:
        handle = sessions["default"]
        if handle.process.is_alive():
            return handle
        else:
            del sessions["default"]
            logger.warning("Default worker died; restarting")
    
    return _spawn_session("default")

def _spawn_session(name: str) -> WorkerHandle:
    """Spawn a named session worker."""
    parent_conn, child_conn = ctx.Pipe()
    process = ctx.Process(target=_worker_main, args=(child_conn, name))
    process.daemon = True
    process.start()
    child_conn.close()
    
    # Wait for ready signal
    if parent_conn.poll(30):
        ready = parent_conn.recv()
        assert ready["event"] == "ready", f"Expected ready, got {ready}"
    else:
        process.kill()
        raise RuntimeError(f"Session '{name}' failed to initialize")
    
    handle = WorkerHandle(
        process=process,
        conn=parent_conn,
        pid=process.pid,
        session_name=name,
    )
    sessions[name] = handle
    return handle

def stop_session(name: str):
    """Stop a named session."""
    if name in sessions:
        handle = sessions[name]
        try:
            handle.conn.send({"type": "stop"})
            handle.process.join(timeout=5)
        except Exception:
            pass
        if handle.process.is_alive():
            handle.process.kill()
            handle.process.join(timeout=1)
        handle.conn.close()
        del sessions[name]

@atexit.register
def _shutdown_all():
    for name in list(sessions.keys()):
        stop_session(name)

# --- Socket listener ---
def start_socket_listener(sock_path: str):
    """Unix domain socket listener for NDJSON requests."""
    import tempfile
    os.makedirs(os.path.dirname(sock_path), exist_ok=True)
    if os.path.exists(sock_path):
        os.remove(sock_path)
    
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(sock_path)
    server.listen(5)
    os.chmod(sock_path, 0o600)
    
    while True:
        conn, _ = server.accept()
        with conn:
            data = conn.recv(65536)
            if not data:
                continue
            request = json.loads(data.decode())
            session_name = request.get("session", "default")
            
            # Auto-start default if needed
            if session_name == "default" and session_name not in sessions:
                _spawn_session("default")
            
            handle = sessions.get(session_name)
            if not handle:
                response = {"id": request["id"], "ok": False, "error": f"Session '{session_name}' not found"}
                conn.sendall((json.dumps(response) + "\n").encode())
                continue
            
            # Forward to worker and get response
            msg_id = uuid.uuid4().hex
            handle.conn.send({"type": request["method"], "id": msg_id, "args": request.get("args", {})})
            
            # Wait for response
            if handle.conn.poll(30):
                result = handle.conn.recv()
                conn.sendall((json.dumps(result) + "\n").encode())
            else:
                conn.sendall((json.dumps({"id": msg_id, "ok": False, "error": "timeout"}) + "\n").encode())
```

---

## 5. Edge Cases & Risks

| Risk | Severity | Mitigation |
|------|----------|------------|
| Daemon crash kills default session | Medium | `stata run` detects dead socket and starts replacement worker |
| Named session clash between agents | Low | Session name includes agent PID or `$MCP_STATA_SESSION_ID` |
| Multiprocessing `spawn` is slow | Low | ~1s initial startup; acceptable for agent workflows |
| pystata not installed | Medium | Daemon falls back to `stata-se -q` pipe subprocess; or install pystata |
| Two `stata run` calls at same time to different named sessions | Low | Each named session has its own worker; no race condition |
| Socket path collisions | Low | Use `os.getpid()` or tempdir suffix; plan already handles this |

---

## 6. Code Review of Current Implementation

### 6.1 Current `sessions.py` (500 LOC)

**What's good:**
- Clean async pattern with `_listen_to_worker` task
- Proper process lifecycle: `ready` → `running` → `stopped` / `error`
- `atexit` global shutdown prevents zombies
- `spawn` context used correctly for Stata process safety

**What should be removed (per §11.7):**
- `_SessionSnapshot` dataclass (lines 34-41): entire snapshot machinery
- `_history` list + `_prune_history()` (lines 108-111): ~50 LOC diff tracking
- `_last_diff_snapshot` + `get_session_diff()` (lines 120-169): not needed
- `profile_code` + `set_profile()` (lines 192-198): user runs setup.do explicitly
- `_STATEFUL_METHODS` set (lines 44-49): all methods are stateful now
- `notify_log` / `notify_progress` per-msg listeners: simplify to direct response

**What should be preserved:**
- `StataSession._call_raw()` pattern (but without log/progress listeners)
- `send_break()` mechanism
- `stop()` with `_process.terminate()` → `kill()` escalation
- `_run_worker()` → `worker.main()` delegation

### 6.2 Current `worker.py` (323 LOC)

**What's good:**
- Thread-based out-of-band listener for break signals
- Async handler dispatching to StataClient methods
- Clear message type → method mapping

**What should be removed:**
- `self.profile_code` + `run_profile()` (lines 108-115): no profile code
- All the per-message `notify_log`/`notify_progress` callbacks (simplify to blocking response)
- Many message types can be collapsed (e.g., one `run_code` instead of separate `run_command` vs `run_do_file` vs `run_command_structured`)

**What should be preserved:**
- StataClient integration
- Break signal handling (still needed for Ctrl+C)
- Error propagation

---

## 7. Recommendations

1. **Implement the simplified daemon immediately** — it's the foundation for all Phase 0 work. Start with `daemon.py` (~150 LOC) and `cli.py` (~100 LOC) as described in plan §4.1.

2. **Keep `sessions.py` as a legacy shim** for the MCP server during migration, but do NOT port the complexity. The new daemon should be a clean break.

3. **Preserve the worker isolation model** — the `spawn` context + pipe pattern is correct and proven. Don't change the transport between daemon and worker (keep `multiprocessing.Connection`). Only change the external API surface from `FastMCP` to Unix socket NDJSON.

4. **`pystata` dependency warning** — if pystata is not available, the daemon should fall back to a `stata-se -q` pipe-based worker. See Test 2 above.

5. **Add a `stata-mock` mode** (plan §11.10) for CI tests without a Stata license.

6. **Test the auto-start path thoroughly** — it's the most critical UX change. The first `stata run` must: detect no daemon, start one, wait for it, then forward the command, all in <5s.

---

## 8. File Count Impact

| File | Before | After | Delta |
|------|--------|-------|-------|
| `sessions.py` | 500 LOC | 0 (removed) | -500 |
| `worker.py` | 323 LOC | ~100 LOC (refactored) | -223 |
| `daemon.py` | 0 LOC | ~150 LOC (new) | +150 |
| `cli.py` | 0 LOC | ~100 LOC (new) | +100 |
| `rpc_client.py` | 0 LOC | ~50 LOC (new) | +50 |
| **Total** | **823 LOC** | **~400 LOC** | **-423 LOC (51%)** |

# Review: Break/Cancel Mechanism (Feature 11)

**Date:** 2026-05-12
**Stata version:** StataNow 19.5 SE
**Reviewer:** Break/Cancel Feature Subagent
**Status:** ⚠️ Critical findings — plan assumption invalid

---

## 1. Executive Summary

The break/cancel mechanism proposed in plan.md §11.11 is **based on an incorrect assumption**: that `sfi.breakIn()` exists and can be called to interrupt a running Stata command. **It does not exist in StataNow 19.5**, and there is **no programmatic API** in pystata/SFI to set the break flag from Python.

The entire current break implementation in `stata_client.py` (`_request_break_in()`, lines 1524–1560) is a **silent no-op**: `getattr(sfi, "breakIn", None)` returns `None`, `callable(None)` is `False`, and the function returns without doing anything.

SIGINT (Ctrl+C) is **explicitly ignored** by Stata batch mode (`signal.SIG_IGN`). The only signal that reliably stops a running Stata command is **SIGTERM**, which kills the entire process without graceful cleanup.

---

## 2. Test Results

### 2.1 Signal Handling on Batch Stata (`stata-se -b do ...`)

| Signal | Behavior | Exit Code | Graceful? |
|--------|----------|-----------|-----------|
| SIGINT (2) | ❌ **Ignored** — process continues | — | No |
| SIGQUIT (3) | ❌ **Ignored** — process continues | — | No |
| SIGTERM (15) | ✅ **Stops** immediately | 143 (128+15) | ❌ No break message |
| SIGHUP (1) | ✅ **Stops** | 129 (128+1) | ❌ No break message |
| SIGUSR1 (10) | ✅ **Stops** | 138 (128+10) | ❌ No break message |
| SIGUSR2 (12) | ✅ **Stops** | 139 (128+12) | ❌ No break message |
| SIGABRT (6) | ✅ **Abort trap** | Core dump | ❌ |
| SIGKILL (9) | ✅ **Forced kill** | 137 (128+9) | ❌ |

### 2.2 SFI API Availability

| Function | Available in StataNow 19.5? | Notes |
|----------|----------------------------|-------|
| `sfi.breakIn()` | ❌ **NOT AVAILABLE** | Current code silently fails |
| `sfi.break_in()` | ❌ **NOT AVAILABLE** | Also not available |
| `sfi.BreakError` | ✅ Available | Exception class, subclass of `SFIError` |
| `sfi.SFIToolkit.pollnow()` | ✅ Available | Raises `BreakError` if Break key was pressed |
| `sfi.SFIToolkit.pollstd()` | ✅ Available | Same as pollnow, standard interval |
| `sfi.SFIToolkit.stata()` | ✅ Available | Executes Stata command (synchronous, blocking) |
| `sfi.SFIToolkit.error(rc)` | ✅ Available | Generates Stata error rc; terminates execution |
| `sfi.SFIToolkit.exit()` | ✅ Available | Forces Stata to exit |
| `stata_plugin` | ✅ Built-in C module | 0 public attributes; no break API |

### 2.3 SIGINT Handler State

Python code within Stata shows:

```
SIGINT handler before:  1  (SIG_IGN)
SIGINT handler after:   <function handler at 0x...>  (Python override)
```

- Stata sets **SIG_IGN** for SIGINT at process startup (C-level).
- Python can **override** this within Python-mode (`python:` blocks), but the handler is **never called** when Stata is executing a command.
- Even with a Python SIGINT handler installed, running `sfi.SFIToolkit.stata("longrun")` blocks Python and **SIGINT is ignored** at the C level.

### 2.4 Break Output

- **SIGTERM**: No "Break" message appears in the log. The log ends mid-command.
- **`sfi.SFIToolkit.error(1)`**: Produces `--Break--` and `r(1)` in the log, but this is a Stata error, not a clean break/interrupt mechanism.
- **GUI Break key** (not tested): Would produce `--Break-- r(1)` according to sfi.py docstrings.

### 2.5 Thread-based Interrupt

Attempting to interrupt a running `sfi.SFIToolkit.stata()` call from another thread:
- `os.kill(pid, SIGINT)` → ignored (SIG_IGN at C level)
- `threading.interrupt_main()` → does not interrupt blocked C call
- Result: **Cannot interrupt a running Stata command from another thread/process programmatically** without SIGTERM.

---

## 3. Current Code Analysis

### 3.1 Break Flow (Current MCP Architecture)

```
MCP Tool (stata_control break)
  → SessionManager.send_break()
    → Pipe send({"type": "break"})
      → Worker._listen_on_pipe() receives
        → StataClient._request_break_in()
          → getattr(sfi, "breakIn", None)  ← returns None
          → callable(None) → False         ← silently returns
          → NO BREAK HAPPENS
```

The break signal propagates through the pipe correctly, but the terminal action (`_request_break_in`) is a no-op because `sfi.breakIn()` does not exist.

### 3.2 Cancellation Flow

```python
# server.py line 3400+ (in run_command_streaming)
except get_cancelled_exc_class():       # asyncio.CancelledError
    self._request_break_in()             # ← no-op in practice
    await self._wait_for_stata_stop()    # polls pollnow(), never gets BreakError
    raise
```

The cancellation path is also broken — `_wait_for_stata_stop()` calls `pollnow()` which will **never** raise `BreakError` because no Break key was pressed.

### 3.3 Affected Files

| File | Lines | Issue |
|------|-------|-------|
| `stata_client.py` | 1524–1560 | `_request_break_in()` — dead code (no-op) |
| `stata_client.py` | 1550–1560 | `_request_break_in_fast()` — dead code (no-op) |
| `stata_client.py` | 1562–1584 | `_poll_break_ack()` — polls `pollnow()` but never gets BreakError |
| `stata_client.py` | 1586–1620 | `_wait_for_stata_stop()` — same issue |
| `stata_client.py` | 3479–3484 | Cancellation handler — calls non-functional break |
| `stata_client.py` | 3803–3806 | Same pattern in `run_do_file_streaming` |
| `worker.py` | 62–67 | Out-of-band break pipe handler — calls `_request_break_in()` |
| `sessions.py` | 220–233 | Cancellation handling — sends break via pipe |

---

## 4. Architecture Proposal for Break/Cancel Subsystem

### 4.1 Core Insight

There are only two reliable ways to stop a running Stata command from outside the GUI:

1. **SIGTERM** → kills the process (hard break, state lost)
2. **`sfi.SFIToolkit.error(rc)`** → generates a Stata error that terminates execution (soft break, but needs to be called from within the execution context)

Since we cannot call `error(rc)` from a signal handler (it raises a Python exception that gets swallowed by the C-level Stata engine), the viable architecture is:

### 4.2 Recommended Architecture: Process-Level Break with Auto-Restart

```
┌──────────────────────────────────────────────────┐
│  Daemon Process                                    │
│  ┌────────────────┐  ┌──────────────────────────┐  │
│  │ SIGINT Handler  │  │ Session Manager          │  │
│  │ sets break_flag │  │                          │  │
│  │ prints "^C..."  │  │  Worker Subprocess       │  │
│  └────────┬───────┘  │  ┌────────────────────┐  │  │
│           │          │  │  pystata / Stata    │  │  │
│           ├──────────┤  │  running command    │  │  │
│           │ on break │  │                    │  │  │
│           │ ────────►│  │  sends SIGTERM ────►│  │  │
│           │          │  │  wait for exit     │  │  │
│           │          │  │  restart worker    │  │  │
│           │          │  └────────────────────┘  │  │
│           │          │  ┌────────────────────┐  │  │
│           │          │  │  New Worker        │  │  │
│           │          │  │  (ready for next   │  │  │
│           │          │  │   command)         │  │  │
│           │          │  └────────────────────┘  │  │
│           │          └──────────────────────────┘  │
└───────────┼──────────────────────────────────────┘
            │
      CLI prints:
      "^C received, sending break..."
      "Break acknowledged, worker restarted."
      "Session state has been reset."
```

**Why this works:**
- SIGTERM is the only signal that **reliably** stops Stata
- Worker restart restores a clean Stata state
- Process isolation prevents corruption of the daemon
- The daemon can save/restore dataset state across breaks

### 4.3 Basic Pseudo-Code

#### 4.3.1 Signal Handler

```python
# In the daemon process
import signal, os, logging

_break_requested = False

def sigint_handler(signum, frame):
    """Handle Ctrl+C in the daemon."""
    global _break_requested
    if _break_requested:
        # Second Ctrl+C: force kill
        print("^C again, forcing exit...")
        os._exit(1)
    
    _break_requested = True
    print("^C received, sending break to Stata worker...")
    
    # If we're waiting for a command, interrupt the wait
    # The main event loop checks _break_requested

signal.signal(signal.SIGINT, sigint_handler)
```

#### 4.3.2 Break Dispatch

```python
async def handle_break(session_manager, session_id: str) -> Dict[str, Any]:
    """Send break to a running Stata session."""
    session = session_manager.get_session(session_id)
    
    if session.status == "idle":
        return {"status": "noop", "message": "No command running"}
    
    # Send SIGTERM to the worker subprocess
    worker_pid = session.worker_pid
    if worker_pid:
        os.kill(worker_pid, signal.SIGTERM)
        
        # Wait for graceful exit (up to 3 seconds)
        try:
            await asyncio.wait_for(
                session.wait_for_exit(), timeout=3.0
            )
        except asyncio.TimeoutError:
            # Force kill if timeout
            os.kill(worker_pid, signal.SIGKILL)
            await session.wait_for_exit()
        
        # Restart the worker
        await session.restart()
        
        return {
            "status": "break_sent",
            "session_id": session_id,
            "worker_restarted": True,
            "note": "Session state has been reset after break"
        }
```

#### 4.3.3 Poll for Completion

```python
async def run_with_break_check(
    session, code: str, break_check_interval: float = 0.5
) -> CommandResult:
    """Run a Stata command with periodic break-check polling."""
    
    # Reset break flag before starting
    global _break_requested
    _break_requested = False
    
    # Run the command in executor (non-blocking)
    loop = asyncio.get_running_loop()
    future = loop.run_in_executor(
        None, session.run_stata_command_sync, code
    )
    
    # Poll for completion while checking break flag
    while not future.done():
        done, _ = await asyncio.wait(
            [future], timeout=break_check_interval
        )
        if _break_requested:
            # Break was requested - terminate the worker
            await handle_break(session)
            raise CommandBreakError("Command interrupted by user")
    
    return future.result()
```

#### 4.3.4 Cleanup

```python
async def cleanup_after_break(session):
    """Clean up worker state after a break."""
    # Ensure worker is stopped
    if session.worker and session.worker.is_alive():
        session.worker.terminate()
        try:
            await asyncio.wait_for(session.worker.join(), timeout=3.0)
        except asyncio.TimeoutError:
            session.worker.kill()
    
    # Start fresh worker
    await session.start_worker()
    
    # Re-run minimal setup if needed
    if session.profile_code:
        await session.run_command(session.profile_code)
    
    # Reset break flag
    global _break_requested
    _break_requested = False
    
    logger.info(f"Session {session.id}: worker restarted after break")
```

### 4.4 Architecture Diagram

```
┌──────────────────────────────────────────────────────────┐
│                     DAEMON PROCESS                        │
│                                                            │
│  ┌─────────────────┐    ┌──────────────────────────────┐  │
│  │ CLI Listener     │    │ Session Manager              │  │
│  │ (Unix socket /   │    │                              │  │
│  │  TCP)            │───►│  ┌────────────────────────┐  │  │
│  └─────────────────┘    │  │ Worker Pool             │  │  │
│                          │  │                        │  │  │
│  ┌─────────────────┐    │  │  Session "default"      │  │  │
│  │ SIGINT Handler   │    │  │  ┌──────────────────┐  │  │  │
│  │                  │───►│  │  │ pystata (child)  │  │  │  │
│  │ Sets break_flag  │    │  │  │ PID: 12345       │  │  │  │
│  │ Prints "^C..."   │    │  │  │ Running command  │  │  │  │
│  └─────────────────┘    │  │  └────────┬─────────┘  │  │  │
│                          │  │           │            │  │  │
│  ┌─────────────────┐    │  │     SIGTERM│(on break)  │  │  │
│  │ Break Flag       │    │  │           ▼            │  │  │
│  │ (threading.Event)│────│  │  ┌──────────────────┐  │  │  │
│  │                  │    │  │  │ New pystata      │  │  │  │
│  │ .is_set() checked│    │  │  │ (auto-restarted) │  │  │  │
│  │ by main loop     │    │  │  └──────────────────┘  │  │  │
│  └─────────────────┘    │  └────────────────────────┘  │  │
│                          │                              │  │
│  ┌─────────────────┐    │  ┌────────────────────────┐  │  │
│  │ Log / Audit      │    │  │ State Store            │  │  │
│  │ "break at t=..." │    │  │ (dataset backup before │  │  │
│  └─────────────────┘    │  │  long commands)         │  │  │
│                          │  └────────────────────────┘  │  │
└──────────────────────────────────────────────────────────┘
```

### 4.5 State Preservation Strategy

Since break via SIGTERM loses the current Stata state, consider:

1. **Auto-save before long commands** (heuristic: commands expected to run >5s):
   ```python
   if is_likely_long_command(code):
       session.save_checkpoint()
   ```

2. **Checkpoint file** at `~/.cache/mcp-stata/checkpoints/<session>/`
   - Contains: dataset (.dta), Stata version, estimation results
   - On restart after break, offer to restore

3. **Grace period**: Before sending SIGTERM, try `sfi.SFIToolkit.error(1)` first:
   ```python
   def try_soft_break(session):
       """Attempt a 'soft' break via SFI error, fall back to SIGTERM."""
       try:
           # This only works if we can inject code execution
           session.inject_code("error 1")
           time.sleep(1)
           if session.is_still_running():
               session.terminate()  # SIGTERM
       except:
           session.terminate()
   ```

---

## 5. Comparison: Plan vs. Reality

| Plan.md §11.11 Assumption | Reality | Impact |
|--------------------------|---------|--------|
| "Daemon calls sfi.breakIn() synchronously" | ❌ `sfi.breakIn()` does not exist | Break cannot be triggered programmatically |
| "Ctrl+C sends SIGINT to the daemon" | ⚠️ SIGINT is ignored by Stata (SIG_IGN) | SIGINT handler works only between commands |
| "No worker sub-process needed" | ❌ Sub-process model needed for SIGTERM isolation | Direct pystata ownership cannot be cleanly interrupted |
| "Break handled in-process with standard Unix signals" | ⚠️ Only SIGTERM works, which kills the process | Architecture must handle process restart |
| "CLI shows `^C received, sending break...`" | ✅ Still feasible | Can print before dispatching SIGTERM |
| "Polls for completion" | ⚠️ Different polling needed | Poll for worker exit + restart, not for BreakError |

---

## 6. Implementation Recommendations

### 6.1 High Priority (Fix Current Break)

1. **Remove dead code**: Delete `_request_break_in()`, `_request_break_in_fast()`, `_poll_break_ack()`, `_wait_for_stata_stop()` — or rewrite them for the new architecture.

2. **Document the limitation**: In the daemon protocol spec, explicitly state: *"Break/cancel stops the Stata process and restarts it. Session state is NOT preserved."*

3. **Fix the worker-level break**: Replace the silent-no-op with actual SIGTERM dispatch to the worker subprocess.

### 6.2 Medium Priority (Daemon Architecture)

4. **Implement restart-after-break**: The session manager must detect worker termination and auto-restart.

5. **Add checkpointing**: Before long commands, auto-save dataset state.

6. **CLI feedback**: Print clear message about state reset on break.

### 6.3 Low Priority (Nice-to-Have)

7. **Explore `stata_plugin` C API**: The `stata_plugin` module exists as a built-in C module. Future investigation might reveal undocumented break functions.

8. **Investigate `_stp` native extension**: The `_stp.C` library (linked into Stata's Python) has `_st_pollnow()` and `_st_pollstd()`. There may be corresponding `_st_break()` or `_st_setbreak()` functions in the C API that are not exposed to Python.

9. **Windows-specific testing**: On Windows, `GenerateConsoleCtrlEvent` may provide a different break mechanism. The plan currently assumes Unix sockets; Windows break behavior needs separate verification.

---

## 7. Scripts Used for Testing

All test scripts are in: `stata-ai/features/11-break-cancel/`

| Script | Purpose |
|--------|---------|
| `test_long.do` | Long-running bootstrap (5000 reps) for interrupt testing |
| `test_while.do` | Infinite while-loop for signal testing |
| `test_sfi_break.do` | Verify sfi.breakIn() existence |
| `test_sfi_break2.do` | Test SFIToolkit.pollnow() |
| `test_sfi_detail.do` | Full SFI API inspection |
| `test_py_signal.do` | Test Python signal handling from Stata |
| `test_long_stata_cmd.do` | Test SIGINT during Stata command execution |
| `test_sigterm_break.do` | Test SIGTERM break with actual Stata workload |
| `test_signals.do` | Test all Unix signals against Stata |
| `check_poll.do` | Check pollnow/pollstd availability |
| `check_stata_plugin.do` | Inspect stata_plugin C module |
| `check_c_break.do` | Check for C-level break mechanism |
| `test_thread_interrupt.do` | Test thread-based interrupt of running Stata |

---

## 8. Conclusion

**The break/cancel mechanism proposed in plan.md §11.11 cannot work as described** because:

1. **`sfi.breakIn()` does not exist** — the fundamental building block is missing.
2. **SIGINT is ignored** by Stata (SIG_IGN) — the signal path is blocked.
3. **There is no SFI/API to programmatically interrupt** a running Stata command from Python.

The viable alternative is a **process-level break with automatic worker restart**:
- SIGTERM to the worker subprocess (reliable, but destroys state)
- Auto-restart the worker (keeps the daemon alive)
- Clear CLI feedback about state loss
- Optional checkpoint-based state preservation for long-running commands

This is a significant architectural departure from what plan.md proposes, and the design should be updated accordingly. The current implementation in `stata_client.py` should be treated as **dead/broken code** and either fixed or removed as part of the migration.

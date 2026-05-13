"""StataWorker process — runs Stata via pystata in a subprocess.

Communicates with the daemon over a multiprocessing.Pipe. Each worker
owns one Stata process (stateful, persistent across commands).
"""

from __future__ import annotations

import os
import signal
import sys
import time
import traceback
from multiprocessing.connection import Connection
from typing import Any

from stata_agent.models import RunResult, TaskStatus


def _worker_main(conn: Connection, session_name: str = "default") -> None:
    """Worker process entry point.

    Initializes Stata via pystata (or fallback), then enters a
    command loop reading from the pipe.
    """
    # Try to configure pystata via stata_setup before importing SFI.
    # Walk up from the binary path to find the root that contains
    # `utilities/` (where the proprietary pystata module lives).
    # This handles both standard installs and .app bundles.
    try:
        import stata_setup
        from stata_agent.discovery import find_stata_candidates

        candidates = find_stata_candidates()
        if candidates:
            stata_path, edition = candidates[0]
            # Walk up to find the root dir with utilities/
            bin_dir = os.path.dirname(stata_path)
            root = bin_dir
            for _ in range(5):  # max 5 levels up
                if os.path.isdir(os.path.join(root, "utilities")):
                    break
                parent = os.path.dirname(root)
                if parent == root:
                    root = None
                    break
                root = parent
            if root:
                edition_lower = edition.lower()
                # Insert utilities/ at head of sys.path first so PyPI
                # pystata doesn't shadow the proprietary one
                utils_path = os.path.join(root, "utilities")
                if os.path.isdir(utils_path) and utils_path not in sys.path:
                    sys.path.insert(0, utils_path)
                stata_setup.config(root, edition_lower, splash=False)
    except Exception:
        pass  # Fall through — will report pystata not available

    # Import pystata-related modules here so the daemon process
    # doesn't need them.
    try:
        from sfi import Macro, Results, Data
        from stata_agent.stata_client import StataClient

        stata = StataClient()
        stata.init()
        _has_pystata = True
    except ImportError:
        _has_pystata = False
        stata = None
        # We'll report the error to the daemon

    # Ignore SIGINT (Stata's domain) but handle SIGTERM for breaks
    signal.signal(signal.SIGINT, signal.SIG_IGN)

    conn.send({"event": "ready", "pid": os.getpid(), "session": session_name})

    running = True
    while running:
        try:
            if not conn.poll(0.5):
                continue

            msg = conn.recv()

            if msg.get("type") == "stop":
                break

            if msg.get("type") == "ping":
                conn.send({"event": "pong", "pid": os.getpid()})
                continue

            if not _has_pystata:
                conn.send({
                    "event": "error",
                    "id": msg.get("id", ""),
                    "error": "pystata not available in this worker process",
                    "error_code": "PYSTATA_MISSING",
                })
                continue

            method = msg.get("method", "")
            args = msg.get("args", {})
            msg_id = msg.get("id", "")

            try:
                result = _dispatch(stata, method, args)
                conn.send({"event": "result", "id": msg_id, "result": result})
            except Exception as e:
                conn.send({
                    "event": "error",
                    "id": msg_id,
                    "error": str(e),
                    "error_code": "EXECUTION_ERROR",
                    "details": {"traceback": traceback.format_exc()},
                })

        except (EOFError, BrokenPipeError):
            break
        except KeyboardInterrupt:
            # Stata ignores SIGINT, but our process might receive it
            continue

    # Cleanup
    if _has_pystata and stata:
        try:
            stata.close()
        except Exception:
            pass
    conn.close()


def _dispatch(stata: Any, method: str, args: dict) -> dict:
    """Route a method call to the appropriate StataClient method."""
    if method == "run":
        result = stata.run(
            args.get("code", ""),
            echo=args.get("echo", True),
            max_output_tokens=args.get("max_output_tokens", 1000),
            strict=args.get("strict", False),
            pre_allocated_log=args.get("pre_allocated_log"),
        )
        return _result_to_dict(result)

    elif method == "run_file":
        result = stata.run_file(
            args.get("path", ""),
            echo=args.get("echo", True),
            strict=args.get("strict", False),
        )
        return _result_to_dict(result)

    elif method == "inspect_describe":
        return stata.inspect_describe(
            varlist=args.get("varlist"),
            fullnames=args.get("fullnames", False),
        )

    elif method == "inspect_summary":
        return stata.inspect_summary(varlist=args.get("varlist"))

    elif method == "inspect_codebook":
        return stata.inspect_codebook(varlist=args.get("varlist"))

    elif method == "inspect_list":
        return stata.inspect_list(
            varlist=args.get("varlist"),
            from_row=args.get("from"),
            count=args.get("count"),
        )

    elif method == "inspect_get":
        return stata.inspect_get(
            format=args.get("format", "csv"),
            out_path=args.get("out_path"),
            varlist=args.get("varlist"),
            obs_range=args.get("obs_range"),
        )

    elif method == "results":
        return stata.get_results(result_class=args.get("class", "r"))

    elif method == "graph_list":
        return {"graph_names": list(stata.snapshot_graphs())}

    elif method == "graph_export":
        return stata.export_graph(
            name=args.get("name"),
            fmt=args.get("format", "pdf"),
            out_path=args.get("out_path"),
        )

    elif method == "log_tail":
        return {"text": stata.read_log_tail(
            lines=args.get("lines", 50),
            bytes=args.get("bytes", 0),
        )}

    elif method == "log_errors":
        return stata.get_log_errors(
            context_lines=args.get("context_lines", 20),
        )

    elif method == "health":
        return {
            "status": "ok",
            "pid": os.getpid(),
            "session": stata.session_name if hasattr(stata, "session_name") else "",
        }

    else:
        raise ValueError(f"Unknown method: {method}")


def _result_to_dict(r: RunResult) -> dict:
    return {
        "ok": r.ok,
        "rc": r.rc,
        "stdout": r.stdout,
        "log_path": r.log_path,
        "graphs": r.graphs,
        "truncated": r.truncated,
    }

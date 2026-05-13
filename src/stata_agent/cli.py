"""stata CLI — single entry point with all subcommands.

Usage:
    stata daemon start|stop|status [--session NAME] [--mock]
    stata run [--session NAME] [--echo] [--background] [--strict] <code>
    stata run [--session NAME] --file /path/to/file.do
    stata break [--session NAME]
    stata inspect describe|summary|codebook|list|get|sample [--session NAME] [varlist...]
    stata graph list|export|export-all [--session NAME] [options]
    stata results [--session NAME] [--return r|e|s]
    stata help <topic> [--format syntax|options|examples|summary|full] [--max-lines N]
    stata log tail|search|errors|path [--session NAME] [options]
    stata lint /path/to/file.do
    stata doctor
    stata discover
    stata task status|cancel|list [--session NAME] [options]
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Optional

from stata_agent import __version__
from stata_agent.rpc_client import RpcClient, RpcError
from stata_agent.statest.runner import run_tests, run_test, discover_tests
from stata_agent.statest.models import TestSuiteSummary

SESSION_DIR = Path.home() / ".cache" / "stata-agent" / "sessions"
LOG_DIR = Path.home() / ".cache" / "stata-agent" / "logs"


# ======================================================================
# Helpers
# ======================================================================

def _get_client(args: Any) -> RpcClient:
    """Get an RPC client for the specified or default session."""
    session = getattr(args, "session", "default")
    return RpcClient(session=session)


def _ensure_daemon(args: Any) -> RpcClient:
    """Ensure the daemon is running, auto-starting if needed."""
    session = getattr(args, "session", "default")
    client = RpcClient(session=session)
    if not client.is_alive():
        print(f"[stata] Daemon not running, starting session '{session}'...", file=sys.stderr)
        _start_daemon(session, mock=getattr(args, "mock", False))
        time.sleep(0.5)
        # Retry
        for _ in range(25):
            if client.is_alive():
                break
            time.sleep(0.2)
        if not client.is_alive():
            print("[stata] Failed to start daemon", file=sys.stderr)
            sys.exit(1)
    return client


def _start_daemon(session: str = "default", mock: bool = False) -> int:
    """Start the daemon process."""
    sock_path = SESSION_DIR / f"{session}.sock"
    if sock_path.exists():
        print(f"Daemon already running for session '{session}'")
        return 0

    SESSION_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    if mock:
        # Start the mock daemon
        daemon_module = "stata_agent.mock_backend"
    else:
        daemon_module = "stata_agent.daemon"

    env = os.environ.copy()
    env["STATA_AGENT_SESSION"] = session

    # Build subprocess command using -m module mode so sys.argv is clean
    cmd = [sys.executable, "-m", daemon_module, "--session", session]
    # Only pass --mock to the real daemon (mock_backend doesn't accept it)
    if mock and daemon_module == "stata_agent.daemon":
        cmd.append("--mock")

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        start_new_session=True,
    )

    # Poll until socket appears or timeout
    for _ in range(50):
        if sock_path.exists():
            print(f"Daemon started (PID {proc.pid}) for session '{session}'")
            return 0
        time.sleep(0.1)

    print("Daemon failed to start within timeout", file=sys.stderr)
    return 1


# ======================================================================
# Command handlers
# ======================================================================

def cmd_daemon_start(args: Any) -> int:
    return _start_daemon(args.session, getattr(args, "mock", False))


def cmd_daemon_stop(args: Any) -> int:
    client = _get_client(args)
    try:
        client.call("stop", {})
    except (FileNotFoundError, RpcError, ConnectionRefusedError):
        pass
    sock_path = SESSION_DIR / f"{args.session}.sock"
    sock_path.unlink(missing_ok=True)
    print(f"Daemon stopped for session '{args.session}'")
    return 0


def cmd_daemon_status(args: Any) -> int:
    client = _get_client(args)
    try:
        result = client.call("health", {})
        print(f"Daemon status: {result.get('status', 'unknown')}")
        print(f"PID: {result.get('pid', '?')}")
        sessions = result.get("sessions", [])
        if sessions:
            print(f"Sessions: {', '.join(sessions)}")
        return 0
    except (FileNotFoundError, ConnectionRefusedError, OSError):
        print(f"Daemon not running for session '{args.session}'")
        return 1


def cmd_run(args: Any) -> int:
    client = _ensure_daemon(args)

    code = args.code
    if args.file:
        code = Path(args.file).read_text(encoding="utf-8", errors="replace")

    echo = getattr(args, "echo", True)
    background = getattr(args, "background", False)
    strict = getattr(args, "strict", False)

    result = client.call("run", {
        "code": code,
        "echo": echo,
        "background": background,
        "strict": strict,
        "max_output_tokens": getattr(args, "max_output_tokens", 1000),
    })

    _print_run_result(result, json_output=getattr(args, "json", False))
    return 0 if result.get("ok", False) else result.get("rc", 1)


def _print_run_result(result: dict, json_output: bool = False) -> None:
    """Print a run result to stdout."""
    if json_output:
        print(json.dumps(result))
        return

    ok = result.get("ok", False)
    rc = result.get("rc", 0)

    if ok:
        print(f"[stata] Completed (rc={rc})")
    else:
        print(f"[stata] Failed (rc={rc})")

    if result.get("stdout"):
        print(result["stdout"].rstrip())

    if result.get("truncated"):
        print(f"[stata] Output truncated. Full log: {result.get('log_path', '?')}")

    graphs = result.get("graphs", {})
    if graphs and (graphs.get("created") or graphs.get("dropped")):
        parts = []
        if graphs.get("created"):
            parts.append(f"created: {', '.join(graphs['created'])}")
        if graphs.get("dropped"):
            parts.append(f"dropped: {', '.join(graphs['dropped'])}")
        print(f"[stata] Graphs: {'; '.join(parts)}")

    log_path = result.get("log_path")
    if log_path:
        print(f"[stata] Log: {log_path}")

    if not ok and result.get("error"):
        print(f"[stata] Error: {result['error']}", file=sys.stderr)


def cmd_break(args: Any) -> int:
    client = _ensure_daemon(args)
    result = client.call("break", {"session": args.session})
    print(f"Break acknowledged. Worker restarted. Session state has been reset.")
    if result.get("note"):
        print(f"[stata] {result['note']}")
    return 0


def _get_inspect_handler(args: Any) -> Any:
    """Get the RPC client for inspect operations."""
    return _ensure_daemon(args)


def cmd_inspect_describe(args: Any) -> int:
    client = _get_inspect_handler(args)
    result = client.call("inspect_describe", {
        "varlist": args.varlist,
        "fullnames": getattr(args, "fullnames", False),
    })
    if args.json:
        print(json.dumps(result))
    else:
        dataset = result.get("dataset_name", "")
        obs = result.get("obs_count", 0)
        vars_count = result.get("var_count", 0)
        print(f"Dataset: {dataset or '(no data loaded)'}")
        print(f"Observations: {obs}")
        print(f"Variables: {vars_count}")
        for v in result.get("variables", []):
            label = v.get("label", "")
            lbl_str = f"  -- {label}" if label else ""
            print(f"  {v['name']:20s} {v.get('type', '?')}{lbl_str}")
    return 0


def cmd_inspect_summary(args: Any) -> int:
    client = _get_inspect_handler(args)
    result = client.call("inspect_summary", {"varlist": args.varlist})
    text = result.get("text", "")
    print(_truncate_output(text, args.max_lines))
    return 0


def cmd_inspect_codebook(args: Any) -> int:
    client = _get_inspect_handler(args)
    result = client.call("inspect_codebook", {"varlist": args.varlist})
    text = result.get("text", "")
    print(_truncate_output(text, args.max_lines))
    return 0


def cmd_inspect_list(args: Any) -> int:
    client = _get_inspect_handler(args)
    result = client.call("inspect_list", {
        "varlist": args.varlist,
        "from": args.from_row,
        "count": args.count,
    })
    text = result.get("text", "")
    print(_truncate_output(text, args.max_lines))
    return 0


def cmd_inspect_get(args: Any) -> int:
    client = _get_inspect_handler(args)
    result = client.call("inspect_get", {
        "varlist": args.varlist,
        "format": args.format,
        "out_path": args.out,
        "obs_range": args.obs_range,
    })
    print(f"Exported to: {result.get('path', '?')}")
    print(f"Size: {result.get('size_bytes', 0)} bytes")
    return 0


def cmd_graph_list(args: Any) -> int:
    client = _ensure_daemon(args)
    result = client.call("graph_list", {})
    names = result.get("graph_names", [])
    if names:
        print(f"Graphs in memory ({len(names)}):")
        for name in names:
            display = name if name != "Graph" else "(unnamed)"
            print(f"  - {display}")
    else:
        print("No graphs in memory.")
    return 0


def cmd_graph_export(args: Any) -> int:
    client = _ensure_daemon(args)
    out_path = args.out or f"{args.name or 'graph'}.{args.format}"
    result = client.call("graph_export", {
        "name": args.name,
        "format": args.format,
        "out_path": out_path,
    })
    print(f"Exported to: {result.get('file_path', '?')} ({result.get('size_bytes', 0)} bytes)")
    return 0


def cmd_graph_export_all(args: Any) -> int:
    client = _ensure_daemon(args)
    names_result = client.call("graph_list", {})
    names = names_result.get("graph_names", [])
    if not names:
        print("No graphs to export.")
        return 0

    outdir = Path(args.outdir or ".")
    outdir.mkdir(parents=True, exist_ok=True)

    for name in names:
        display_name = name if name != "Graph" else "_unnamed"
        out_path = str(outdir / f"{display_name}.{args.format}")
        result = client.call("graph_export", {
            "name": name,
            "format": args.format,
            "out_path": out_path,
        })
        print(f"  {display_name} -> {result.get('file_path', '?')} ({result.get('size_bytes', 0)} bytes)")

    return 0


def cmd_results(args: Any) -> int:
    client = _ensure_daemon(args)
    result = client.call("results", {"class": args.return_class or "r"})
    if args.json:
        print(json.dumps(result))
    else:
        stored = result.get("stored_results", {})
        if stored:
            print(f"Stored results ({result.get('class', '?')}()):")
            for k, v in stored.items():
                print(f"  {k} = {v}")
        else:
            print(f"No stored results in {result.get('class', '?')}()")
    return 0


def cmd_help(args: Any) -> int:
    """Stateless help subprocess: runs stata-se -q with 'help topic'."""
    topic = args.topic
    max_lines = getattr(args, "max_lines", 0)

    # Try to find stata binary
    try:
        from stata_agent.discovery import find_stata_path
        stata_bin, _ = find_stata_path()
    except (ImportError, Exception):
        stata_bin = "stata-se"

    try:
        proc = subprocess.run(
            [stata_bin, "-q", "-e", f"help {topic}"],
            input="exit\n",
            text=True,
            capture_output=True,
            timeout=30,
            env={**os.environ, "TERM": "dumb"},
        )
        output = proc.stdout
    except FileNotFoundError:
        print(f"[stata] Stata binary not found: {stata_bin}")
        return 1
    except subprocess.TimeoutExpired:
        print(f"[stata] Help command timed out")
        return 1

    # Strip terminal control codes
    import re
    output = re.sub(r'\x1b\[[0-9;]*[a-zA-Z]', '', output)
    output = re.sub(r'\x1b\][0-9;]*[^\x1b]*\x1b\\', '', output)

    # Section extraction
    fmt = getattr(args, "format", "full")
    if fmt == "syntax":
        # Extract syntax section
        lines = output.split("\n")
        syntax_lines = []
        in_syntax = False
        for line in lines:
            if line.strip().startswith("Syntax") or line.strip().startswith("syntax"):
                in_syntax = True
            elif in_syntax and (line.strip() == "" or any(
                line.strip().startswith(s) for s in ["Description", "Options", "Examples", "Remarks"]
            )):
                break
            if in_syntax:
                syntax_lines.append(line)
        output = "\n".join(syntax_lines) if syntax_lines else output
    elif fmt == "options":
        lines = output.split("\n")
        options_lines = []
        in_options = False
        for line in lines:
            if line.strip().startswith("Options") or line.strip().startswith("options"):
                in_options = True
            elif in_options and (line.strip() == "" or any(
                line.strip().startswith(s) for s in ["Examples", "Remarks", "Stored results"]
            )):
                break
            if in_options:
                options_lines.append(line)
        output = "\n".join(options_lines) if options_lines else output
    elif fmt == "examples":
        lines = output.split("\n")
        examples_lines = []
        in_examples = False
        for line in lines:
            if line.strip().startswith("Examples") or line.strip().startswith("examples"):
                in_examples = True
            elif in_examples and (line.strip() == "" or any(
                line.strip().startswith(s) for s in ["Remarks", "Stored results", "References"]
            )):
                break
            if in_examples:
                examples_lines.append(line)
        output = "\n".join(examples_lines) if examples_lines else output

    # Limit lines
    if max_lines > 0:
        output = "\n".join(output.split("\n")[:max_lines])

    print(output)
    return 0


def cmd_log_tail(args: Any) -> int:
    client = _get_client(args)
    lines = getattr(args, "lines", 50)
    # Try to get log path from worker
    try:
        result = client.call("log_tail", {"lines": lines})
        print(result.get("text", ""))
    except (FileNotFoundError, RpcError):
        # Fall back to reading the log file directly
        log_path = LOG_DIR / f"{args.session}_*.log"
        print(f"[stata] Daemon not running. Logs at: {LOG_DIR}/")
        return 1
    return 0


def cmd_log_search(args: Any) -> int:
    client = _get_client(args)
    pattern = args.pattern
    result = client.call("log_search", {
        "pattern": pattern,
        "offset": getattr(args, "offset", 0),
        "max_bytes": getattr(args, "max_bytes", 262144),
    })
    matches = result.get("matches", [])
    if matches:
        print(f"Found {len(matches)} match(es):")
        for m in matches:
            print(f"  {m}")
    else:
        print("No matches found.")
    return 0


def cmd_log_errors(args: Any) -> int:
    client = _get_client(args)
    try:
        result = client.call("log_errors", {"context_lines": getattr(args, "context_lines", 20)})
        if result.get("rc") is not None:
            print(f"Error: rc={result['rc']}")
            if result.get("message"):
                print(f"Message: {result['message']}")
            if result.get("context"):
                print(f"Context:\n{result['context']}")
            print(f"Source: {result.get('source', '?')}")
        else:
            print("No errors found in log.")
    except (FileNotFoundError, RpcError):
        print("[stata] Daemon not running.")
        return 1
    return 0


def cmd_log_path(args: Any) -> int:
    log_path = LOG_DIR / f"{args.session}"
    print(str(log_path))
    return 0


def cmd_lint(args: Any) -> int:
    from stata_agent.linter import lint_file, format_lint_results

    issues = lint_file(args.path)
    print(format_lint_results(issues))

    error_count = sum(1 for i in issues if i.severity == "error")
    return 1 if error_count > 0 else 0


def cmd_doctor(args: Any) -> int:
    """Check the stata-agent environment and report status."""
    # If --json, use verify.py's doctor() for structured output
    if getattr(args, "json", False):
        try:
            from scripts.install.verify import doctor as verify_doctor
            result = verify_doctor()
            print(json.dumps(result.to_dict(), indent=2))
            return 1 if result.issues else 0
        except ImportError:
            print(json.dumps({"error": "verify module not available", "issues": ["verify.py not found"]}))
            return 1

    print("[stata-agent] Checking environment...")
    issues = []

    # Check Python version
    if sys.version_info < (3, 11):
        issues.append(("error", f"Python {sys.version} (need >= 3.11)"))
    else:
        print(f"  Python: {sys.version}")

    # Check cache dirs
    for d in [SESSION_DIR, LOG_DIR]:
        if d.exists():
            print(f"  {d}: OK")
        else:
            print(f"  {d}: not found (will be created on first use)")

    # Check discovery
    try:
        from stata_agent.discovery import find_stata_path
        path, edition = find_stata_path()
        print(f"  Stata: {path} ({edition})")
    except ImportError:
        print("  Stata: discovery module not available")
    except Exception as e:
        print(f"  Stata: {e}")

    # Check pystata
    try:
        import pystata  # noqa: F401
        print(f"  pystata: available")
    except ImportError:
        print(f"  pystata: not available (install via 'pip install pystata' or use Stata's Python)")

    # Check daemon
    try:
        client = RpcClient()
        health = client.call("health", {})
        print(f"  Daemon: running (PID {health.get('pid', '?')})")
    except Exception:
        print(f"  Daemon: not running")

    # Check update state
    try:
        from stata_agent.skills_installer import _get_state_dir
        state_dir = _get_state_dir()
        state_file = state_dir / "update_state.json"
        if state_file.exists():
            state = json.loads(state_file.read_text())
            print(f"  Update state: {state.get('last_check_result', 'unknown')}")
            if state.get("denylist_active"):
                issues.append(("warning", f"Current version is denylisted. Upgrade required."))
        else:
            print(f"  Update state: not yet checked")
    except Exception:
        pass

    if issues:
        for severity, msg in issues:
            print(f"  [{severity}] {msg}")
        return 1
    return 0


def cmd_install_skills(args: Any) -> int:
    """Register skills with detected AI agents."""
    try:
        from stata_agent.skills_installer import install_skills, uninstall_skills
    except ImportError as e:
        print(f"Error: skills_installer module not available: {e}", file=sys.stderr)
        return 1

    quiet = getattr(args, "quiet", False)
    dry_run = getattr(args, "dry_run", False)
    repair = getattr(args, "repair", False)
    verbose = getattr(args, "verbose", False)

    if getattr(args, "uninstall", False):
        if not quiet:
            print("[stata-agent] Uninstalling skills...")
        results = uninstall_skills(dry_run=dry_run, verbose=verbose)
    else:
        if not quiet:
            print("[stata-agent] Installing skills...")
        agents_filter = None
        if getattr(args, "agents", None):
            agents_filter = [a.strip() for a in args.agents.split(",")]
        results = install_skills(
            dry_run=dry_run,
            repair=repair,
            verbose=verbose,
            agents_filter=agents_filter,
        )

    for agent, msgs in results.items():
        for msg in msgs:
            if not quiet:
                print(f"  {agent}: {msg}")

    # Return non-zero if any failures
    has_failures = any("Failed" in m for msgs in results.values() for m in msgs)
    return 1 if has_failures else 0


def cmd_upgrade(args: Any) -> int:
    """Upgrade stata-agent to the latest version."""
    try:
        from stata_agent.skills_installer import check_and_upgrade, _fetch_latest_version, _parse_version
        from stata_agent import __version__
    except ImportError as e:
        print(f"Error: upgrade module not available: {e}", file=sys.stderr)
        return 1

    quiet = getattr(args, "quiet", False)
    force = getattr(args, "force", False)
    to_version = getattr(args, "to_version", None)

    if to_version:
        # Install specific version (downgrade support)
        if not quiet:
            print(f"[stata-agent] Installing version {to_version}...")
        result = subprocess.run(
            ["uv", "tool", "install", "stata-agent", "==" + to_version, "--force"],
            check=not quiet,
            capture_output=quiet,
            timeout=120,
        )
        if result.returncode == 0:
            if not quiet:
                print(f"[stata-agent] Downgraded to {to_version}")
            # Re-register skills
            subprocess.run(
                [sys.argv[0], "install-skills", "--quiet"],
                capture_output=True, timeout=30,
            )
            return 0
        else:
            if not quiet:
                print(f"[stata-agent] Failed to install {to_version}")
            return 1

    if not quiet:
        print(f"[stata-agent] Checking for updates (current: {__version__})...")

    check_and_upgrade(force=force)
    return 0


def cmd_discover(args: Any) -> int:
    """Discover Stata installations."""
    try:
        from stata_agent.discovery import find_stata_candidates, verify_stata_install

        candidates = find_stata_candidates()
        if candidates:
            print(f"Found {len(candidates)} Stata candidate(s):")
            for path, edition in candidates:
                verified = verify_stata_install(path, edition)
                status = "verified" if verified else "unverified"
                print(f"  {path} ({edition}) - {status}")
        else:
            print("No Stata candidates found.")
            return 1
    except ImportError:
        print("Discovery module not available.")
        return 1
    return 0


def cmd_task(args: Any) -> int:
    client = _ensure_daemon(args)

    if args.task_cmd == "status":
        result = client.call("task_status", {
            "task_id": args.task_id,
            "tail_lines": getattr(args, "tail_lines", 0),
            "wait": getattr(args, "wait", False),
            "timeout": getattr(args, "timeout", 300),
        })
        status = result.get("status", "unknown")
        print(f"Task {args.task_id}: {status}")
        if result.get("rc") is not None:
            print(f"  rc: {result['rc']}")
        if result.get("log_tail"):
            print(f"  Log tail:\n{result['log_tail']}")
        if result.get("error"):
            print(f"  Error: {result['error']}")
        return 0 if status == "completed" else 1

    elif args.task_cmd == "cancel":
        result = client.call("task_cancel", {"task_id": args.task_id})
        if result.get("cancelled"):
            print(f"Task {args.task_id} cancelled.")
            return 0
        else:
            print(f"Task {args.task_id} not found.")
            return 1

    elif args.task_cmd == "list":
        result = client.call("task_list", {})
        tasks = result.get("tasks", [])
        if tasks:
            print(f"Background tasks ({len(tasks)}):")
            for t in tasks:
                print(f"  {t['task_id'][:12]}... - {t.get('status', '?')}")
        else:
            print("No background tasks.")

    return 0


def _truncate_output(text: str, max_lines: int = 0) -> str:
    """Truncate output to max_lines if specified."""
    if max_lines <= 0:
        return text
    lines = text.split("\n")
    if len(lines) <= max_lines:
        return text
    return "\n".join(lines[:max_lines]) + f"\n... (truncated, {len(lines)} total lines)"


def cmd_test_discover(args: Any) -> int:
    """Discover test files without running them."""
    files = discover_tests(args.path)
    if not files:
        print(f"[statest] No test files found under {args.path}")
        return 0
    for f in files:
        print(f)
    print(f"[statest] Found {len(files)} test file(s)")
    return 0


def cmd_test_run(args: Any) -> int:
    """Run a single test file."""
    # Ensure daemon is running
    _ensure_daemon(args)

    import asyncio
    result = asyncio.run(run_test(
        path=args.path,
        base_session=args.session,
    ))

    _print_test_result(result, json_output=getattr(args, "json", False))
    return 0 if result.success else 1


def cmd_test_run_all(args: Any) -> int:
    """Run all tests under a directory."""
    # Ensure daemon is running
    _ensure_daemon(args)

    import asyncio
    summary = asyncio.run(run_tests(
        path=args.path,
        parallel=getattr(args, "parallel", False),
        max_workers=getattr(args, "workers", 4),
        junit_xml_path=getattr(args, "junit", None),
    ))

    _print_test_summary(summary, json_output=getattr(args, "json", False))
    return 1 if summary.failed > 0 else 0


def _print_test_result(result, json_output: bool = False) -> None:
    """Print a single test result."""
    if json_output:
        import json
        print(json.dumps(result.model_dump()))
        return

    status = "\u2713" if result.success else "\u2717"
    print(f"[statest] {status} {result.test_path} ({result.duration_seconds:.1f}s)")
    if not result.success:
        if result.failure:
            f = result.failure
            print(f"[statest]   assertion {f.assertion_index}: {f.command}")
            print(f"[statest]   expected: {f.expected}")
            print(f"[statest]   actual: {f.actual}")
            print(f"[statest]   rc: {f.rc}")
        else:
            print(f"[statest]   rc: {result.rc}")
        if result.log_path:
            print(f"[statest]   log: {result.log_path}")


def _print_test_summary(summary, json_output: bool = False) -> None:
    """Print a full test suite summary."""
    if json_output:
        import json
        print(json.dumps(summary.model_dump()))
        return

    print(f"[statest] Ran {summary.total_tests} tests")
    if summary.failed > 0:
        print(f"[statest] \u2717 {summary.failed} failed, {summary.passed} passed")
        print()
        for r in summary.results:
            if not r.success:
                _print_test_result(r)
                print()
    else:
        print(f"[statest] \u2713 {summary.passed} passed")

    if summary.junit_xml_path:
        print(f"[statest] JUnit XML: {summary.junit_xml_path}")

# ======================================================================
# Parser construction
# ======================================================================

def build_parser() -> argparse.ArgumentParser:
    """Build the full argument parser."""
    parser = argparse.ArgumentParser(prog="stata-agent", description="CLI-native Stata integration")
    parser.add_argument("--json", action="store_true", help="Output in JSON format")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subparsers = parser.add_subparsers(dest="command")

    # ---- daemon ----
    daemon = subparsers.add_parser("daemon", help="Daemon lifecycle")
    daemon_sub = daemon.add_subparsers(dest="daemon_cmd")

    d_start = daemon_sub.add_parser("start", help="Start the daemon")
    d_start.add_argument("--session", default="default")
    d_start.add_argument("--port", type=int, default=0)
    d_start.add_argument("--mock", action="store_true", help="Use mock backend (no Stata)")

    d_stop = daemon_sub.add_parser("stop", help="Stop the daemon")
    d_stop.add_argument("--session", default="default")

    d_status = daemon_sub.add_parser("status", help="Check daemon status")
    d_status.add_argument("--session", default="default")

    # ---- run ----
    run = subparsers.add_parser("run", help="Run Stata code")
    run.add_argument("--session", default="default")
    run.add_argument("--echo", action="store_true", default=True)
    run.add_argument("--no-echo", action="store_false", dest="echo")
    run.add_argument("--background", action="store_true")
    run.add_argument("--strict", action="store_true", help="Disable capture-noisily wrapper")
    run.add_argument("--file", help="Run a do-file")
    run.add_argument("--max-output-tokens", type=int, default=1000)
    run.add_argument("code", nargs="?", default="")

    # ---- break ----
    brk = subparsers.add_parser("break", help="Break running command")
    brk.add_argument("--session", default="default")

    # ---- inspect ----
    inspect = subparsers.add_parser("inspect", help="Data inspection")
    inspect_sub = inspect.add_subparsers(dest="inspect_cmd")

    insp_describe = inspect_sub.add_parser("describe", help="Describe dataset")
    insp_describe.add_argument("--session", default="default")
    insp_describe.add_argument("varlist", nargs="*")
    insp_describe.add_argument("--fullnames", action="store_true")

    insp_summary = inspect_sub.add_parser("summary", help="Summarize variables")
    insp_summary.add_argument("--session", default="default")
    insp_summary.add_argument("varlist", nargs="*")
    insp_summary.add_argument("--max-lines", type=int, default=0)

    insp_codebook = inspect_sub.add_parser("codebook", help="Show codebook")
    insp_codebook.add_argument("--session", default="default")
    insp_codebook.add_argument("varlist", nargs="*")
    insp_codebook.add_argument("--max-lines", type=int, default=0)

    insp_list = inspect_sub.add_parser("list", help="List data")
    insp_list.add_argument("--session", default="default")
    insp_list.add_argument("varlist", nargs="*")
    insp_list.add_argument("--from", dest="from_row", type=int, default=None)
    insp_list.add_argument("--count", type=int, default=None)
    insp_list.add_argument("--max-lines", type=int, default=0)

    insp_get = inspect_sub.add_parser("get", help="Export data")
    insp_get.add_argument("--session", default="default")
    insp_get.add_argument("--format", default="csv", choices=["csv", "json", "arrow"])
    insp_get.add_argument("--out", required=True)
    insp_get.add_argument("varlist", nargs="*")
    insp_get.add_argument("--obs-range", default=None, help="Observation range to export (e.g. 1:100)")

    # ---- graph ----
    graph = subparsers.add_parser("graph", help="Graph operations")
    graph_sub = graph.add_subparsers(dest="graph_cmd")

    g_list = graph_sub.add_parser("list", help="List graphs in memory")
    g_list.add_argument("--session", default="default")

    g_export = graph_sub.add_parser("export", help="Export a graph")
    g_export.add_argument("--session", default="default")
    g_export.add_argument("--name", required=True)
    g_export.add_argument("--format", default="pdf", choices=["pdf", "png", "svg"])
    g_export.add_argument("--out", default=None)

    g_export_all = graph_sub.add_parser("export-all", help="Export all graphs")
    g_export_all.add_argument("--session", default="default")
    g_export_all.add_argument("--format", default="pdf", choices=["pdf", "png", "svg"])
    g_export_all.add_argument("--outdir", default="./figures")

    # ---- results ----
    results = subparsers.add_parser("results", help="Get stored results")
    results.add_argument("--session", default="default")
    results.add_argument("--return", dest="return_class", default="r", choices=["r", "e", "s"])

    # ---- help ----
    help_cmd = subparsers.add_parser("help", help="Get Stata help (stateless subprocess)")
    help_cmd.add_argument("topic", help="Stata command/function name")
    help_cmd.add_argument("--format", default="full", choices=["syntax", "options", "examples", "summary", "full"])
    help_cmd.add_argument("--max-lines", type=int, default=0)

    # ---- log ----
    log = subparsers.add_parser("log", help="Log operations")
    log_sub = log.add_subparsers(dest="log_cmd")

    log_tail = log_sub.add_parser("tail", help="Read log tail")
    log_tail.add_argument("--session", default="default")
    log_tail.add_argument("--lines", type=int, default=50)

    log_search = log_sub.add_parser("search", help="Search log")
    log_search.add_argument("--session", default="default")
    log_search.add_argument("pattern")
    log_search.add_argument("--offset", type=int, default=0)
    log_search.add_argument("--max-bytes", type=int, default=262144)

    log_errors = log_sub.add_parser("errors", help="Extract errors")
    log_errors.add_argument("--session", default="default")
    log_errors.add_argument("--context-lines", type=int, default=20)

    log_path = log_sub.add_parser("path", help="Show log path")
    log_path.add_argument("--session", default="default")

    # ---- lint ----
    lint = subparsers.add_parser("lint", help="Lint a do-file")
    lint.add_argument("path", help="Path to do-file")

    # ---- doctor ----
    doctor = subparsers.add_parser("doctor", help="Check environment")
    doctor.add_argument("--json", action="store_true", help="Output in JSON format")
    doctor.add_argument("--no-upgrade", action="store_true", help="Skip auto-upgrade check")

    # ---- discover ----
    discover = subparsers.add_parser("discover", help="Discover Stata installations")

    # ---- install-skills ----
    install_skills = subparsers.add_parser("install-skills", help="Register skills with detected AI agents")
    install_skills.add_argument("--dry-run", action="store_true", help="Print actions without executing")
    install_skills.add_argument("--verbose", action="store_true", help="Show detailed output")
    install_skills.add_argument("--uninstall", action="store_true", help="Remove skills links/copies")
    install_skills.add_argument("--quiet", action="store_true", help="Suppress output")
    install_skills.add_argument("--repair", action="store_true", help="Fix stale links and missing hooks")
    install_skills.add_argument("--agents", help="Comma-separated list of agents to target (e.g. claude,codex)")

    # ---- upgrade ----
    upgrade = subparsers.add_parser("upgrade", help="Upgrade stata-agent to latest version")
    upgrade.add_argument("--force", action="store_true", help="Remove timeout and force upgrade check")
    upgrade.add_argument("--quiet", action="store_true", help="Suppress output")
    upgrade.add_argument("--verbose", action="store_true", help="Show detailed output")
    upgrade.add_argument("--to", dest="to_version", help="Install a specific version (for downgrade)")

    # ---- task ----
    task = subparsers.add_parser("task", help="Background task management")
    task_sub = task.add_subparsers(dest="task_cmd")

    task_status = task_sub.add_parser("status", help="Check task status")
    task_status.add_argument("--session", default="default")
    task_status.add_argument("--task-id", required=True)
    task_status.add_argument("--wait", action="store_true")
    task_status.add_argument("--timeout", type=int, default=300)
    task_status.add_argument("--tail-lines", type=int, default=0)

    task_cancel = task_sub.add_parser("cancel", help="Cancel a task")
    task_cancel.add_argument("--session", default="default")
    task_cancel.add_argument("--task-id", required=True)

    task_list = task_sub.add_parser("list", help="List background tasks")
    task_list.add_argument("--session", default="default")


    # ---- test ----
    test = subparsers.add_parser("test", help="Run statest test suites")
    test_sub = test.add_subparsers(dest="test_cmd")

    test_discover = test_sub.add_parser("discover", help="Discover test files")
    test_discover.add_argument("path", help="Path to search for test files")

    test_run = test_sub.add_parser("run", help="Run a single test file")
    test_run.add_argument("path", help="Path to test .do file")
    test_run.add_argument("--session", default="default")
    test_run.add_argument("--mock", action="store_true", help="Use mock backend")

    test_run_all = test_sub.add_parser("run-all", help="Run all tests under a path")
    test_run_all.add_argument("path", help="Path to search for test files")
    test_run_all.add_argument("--session", default="default")
    test_run_all.add_argument("--mock", action="store_true", help="Use mock backend")
    test_run_all.add_argument("--parallel", action="store_true", help="Run tests in parallel")
    test_run_all.add_argument("--workers", type=int, default=4, help="Max parallel workers")
    test_run_all.add_argument("--junit", help="Output JUnit XML to this path")
    return parser


# ======================================================================
# Main entry point
# ======================================================================

def main(argv: list[str] | None = None) -> int:
    """Entry point for the stata CLI."""
    # Auto-update check (skip for upgrade and install-skills to prevent recursion)
    if argv is None:
        argv = sys.argv[1:]
    # Handle --version before auto-upgrade check
    if '--version' in argv or '-v' in argv:
        print(f"stata-agent {__version__}")
        return 0

    # Determine subcommand without full parse
    subcommand = None
    for i, a in enumerate(argv):
        if not a.startswith("-") and a in (
            "daemon", "run", "break", "inspect", "graph", "results",
            "help", "log", "lint", "doctor", "discover", "task", "test",
            "install-skills", "upgrade",
        ):
            subcommand = a
            break
    # Run auto-upgrade for all commands except upgrade, install-skills
    if subcommand not in ("upgrade", "install-skills"):
        try:
            from stata_agent.skills_installer import check_and_upgrade
            check_and_upgrade(force=False)
        except Exception:
            pass  # Never crash on auto-update failure

    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit:
        return 2

    # Map '--json' from root parser into subcommand args
    if hasattr(args, 'json'):
        for subattr in ('run', 'results'):
            sub = getattr(args, subattr, None)
            if sub is not None:
                pass  # subcommands that need json already read it

    if args.command == "daemon":
        if args.daemon_cmd == "start":
            return cmd_daemon_start(args)
        elif args.daemon_cmd == "stop":
            return cmd_daemon_stop(args)
        elif args.daemon_cmd == "status":
            return cmd_daemon_status(args)
        else:
            print("Usage: stata daemon start|stop|status [--session NAME]")
            return 1

    elif args.command == "run":
        return cmd_run(args)

    elif args.command == "break":
        return cmd_break(args)

    elif args.command == "inspect":
        if args.inspect_cmd == "describe":
            return cmd_inspect_describe(args)
        elif args.inspect_cmd == "summary":
            return cmd_inspect_summary(args)
        elif args.inspect_cmd == "codebook":
            return cmd_inspect_codebook(args)
        elif args.inspect_cmd == "list":
            return cmd_inspect_list(args)
        elif args.inspect_cmd == "get":
            return cmd_inspect_get(args)
        else:
            print("Usage: stata inspect describe|summary|codebook|list|get [varlist...]")
            return 1

    elif args.command == "graph":
        if args.graph_cmd == "list":
            return cmd_graph_list(args)
        elif args.graph_cmd == "export":
            return cmd_graph_export(args)
        elif args.graph_cmd == "export-all":
            return cmd_graph_export_all(args)
        else:
            print("Usage: stata graph list|export|export-all [options]")
            return 1

    elif args.command == "results":
        return cmd_results(args)

    elif args.command == "help":
        return cmd_help(args)

    elif args.command == "log":
        if args.log_cmd == "tail":
            return cmd_log_tail(args)
        elif args.log_cmd == "search":
            return cmd_log_search(args)
        elif args.log_cmd == "errors":
            return cmd_log_errors(args)
        elif args.log_cmd == "path":
            return cmd_log_path(args)
        else:
            print("Usage: stata log tail|search|errors|path [options]")
            return 1

    elif args.command == "lint":
        return cmd_lint(args)

    elif args.command == "doctor":
        return cmd_doctor(args)

    elif args.command == "discover":
        return cmd_discover(args)

    elif args.command == "task":
        if args.task_cmd == "status":
            return cmd_task(args)
        elif args.task_cmd == "cancel":
            return cmd_task(args)
        elif args.task_cmd == "list":
            return cmd_task(args)
        else:
            print("Usage: stata task status|cancel|list [options]")
            return 1

    elif args.command == "test":
        if args.test_cmd == "discover":
            return cmd_test_discover(args)
        elif args.test_cmd == "run":
            return cmd_test_run(args)
        elif args.test_cmd == "run-all":
            return cmd_test_run_all(args)
        else:
            print("Usage: stata test discover|run|run-all [options]")
            return 1

    elif args.command == "install-skills":
        return cmd_install_skills(args)

    elif args.command == "upgrade":
        return cmd_upgrade(args)

    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main())

"""Statest testing framework runner — RpcClient-based.

Replaces the old session_manager coupling with direct RPC
calls to the stata-agent daemon.
"""

from __future__ import annotations

import asyncio
import glob
import logging
import os
import time
import uuid
from pathlib import Path
from typing import Any, Optional

from stata_agent.rpc_client import RpcClient

from .models import TestResult, AssertionFailure, TestSuiteSummary
from .junit import write_junit_xml

logger = logging.getLogger("stata_agent.statest.runner")


def discover_tests(path: str) -> list[str]:
    """Find all test_*.do files recursively under path."""
    search_path = os.path.join(path, "**", "test_*.do")
    return sorted(glob.glob(search_path, recursive=True))


class StatestSessionPool:
    """Pool of warm Stata sessions for statest, backed by daemon sessions.

    Each pooled session is a named daemon session (statest-<uuid8>).
    Sessions are created on demand and returned to the pool after use.
    """

    def __init__(self, base_session: str = "default", size: int = 4):
        self._client = RpcClient(session=base_session)
        self._pool: asyncio.Queue[str] = asyncio.Queue(maxsize=size)
        self._size = size
        self._created_count = 0
        self._lock = asyncio.Lock()
        startup_file = Path(__file__).parent / "statest.mata"
        self._startup_file = str(startup_file.resolve())

    async def _rpc(self, method: str, args: dict | None = None) -> dict[str, Any]:
        """Run RPC call in executor to avoid blocking event loop."""
        return await asyncio.to_thread(self._client.call, method, args or {})

    async def acquire(self) -> str:
        """Get a warm session from the pool or create a new one."""
        # Try existing warm session first
        try:
            return self._pool.get_nowait()
        except asyncio.QueueEmpty:
            pass

        # Create new session if under the limit
        async with self._lock:
            if self._created_count < self._size:
                session_id = f"statest-{uuid.uuid4().hex[:8]}"
                # Load statest.mata into the new session
                await self._rpc("run_file", {
                    "session": session_id,
                    "path": self._startup_file,
                    "echo": False,
                })
                self._created_count += 1
                return session_id

        # All sessions busy — wait for one to be released
        return await self._pool.get()

    async def release(self, session_id: str) -> None:
        """Reset session state and return to pool."""
        try:
            await self._rpc("run", {
                "session": session_id,
                "code": "statest_reset\nclear all",
            })
            await self._pool.put(session_id)
        except Exception as e:
            logger.warning("Failed to reset/release session %s: %s", session_id, e)
            async with self._lock:
                self._created_count -= 1

    async def drain(self) -> None:
        """Stop all sessions and drain the pool."""
        while self._created_count > 0:
            try:
                sid = await asyncio.wait_for(self._pool.get(), timeout=2.0)
                await self._rpc("stop", {"session": sid})
                self._created_count -= 1
            except asyncio.TimeoutError:
                break


async def _fetch_assertion_failure(
    client: RpcClient,
    session_id: str,
    test_path: str,
    rc: int,
    log_path: str | None,
) -> tuple[int | None, AssertionFailure | None]:
    """Fetch statest_* results after a failure using the results RPC."""
    try:
        results = await asyncio.to_thread(
            client.call, "results", {"session": session_id, "class": "r"}
        )
        stored = results.get("stored_results", {})
        scalars = stored.get("scalars", {})
        data = {k: v for k, v in scalars.items() if k.startswith("statest_")}

        assertion_index_raw = data.get("statest_assertion_index")
        if assertion_index_raw is not None:
            try:
                idx = int(float(assertion_index_raw))
                actual = data.get("statest_actual_str") or data.get("statest_actual")
                expected = data.get("statest_expected_str") or data.get("statest_expected")

                # Fetch log excerpt if possible
                log_excerpt: str | None = None
                if log_path and os.path.exists(log_path):
                    with open(log_path, "r") as f:
                        lines = f.readlines()
                        log_excerpt = "".join(lines[-20:])

                failure = AssertionFailure(
                    test=os.path.basename(test_path),
                    assertion_index=idx,
                    command=str(data.get("statest_command") or "unknown"),
                    variable=str(data.get("statest_variable") or ""),
                    expected=str(expected) if expected is not None else None,
                    actual=str(actual) if actual is not None else None,
                    tolerance=float(data["statest_tolerance"]) if data.get("statest_tolerance") else None,
                    rc=rc,
                    log_excerpt=log_excerpt,
                )
                return idx, failure
            except (ValueError, TypeError):
                pass
    except Exception as e:
        logger.warning("Failed to fetch statest results for %s: %s", test_path, e)

    return None, None


async def run_test(
    path: str,
    base_session: str = "default",
    pool: StatestSessionPool | None = None,
    existing_session_id: str | None = None,
) -> TestResult:
    """Run a single test do-file, optionally using a pool or existing session.

    Args:
        path: Path to the test .do file.
        base_session: Base daemon session name.
        pool: Optional session pool for managing warm sessions.
        existing_session_id: Use a specific session (pool takes precedence).
    """
    start_time = time.time()
    client = RpcClient(session=base_session)

    # Determine session id
    session_id = existing_session_id
    if not session_id and pool:
        session_id = await pool.acquire()
    elif not session_id:
        session_id = f"statest-{uuid.uuid4().hex[:8]}"
        # Load statest.mata into new session
        startup_file = str((Path(__file__).parent / "statest.mata").resolve())
        await asyncio.to_thread(
            client.call, "run_file", {
                "session": session_id,
                "path": startup_file,
                "echo": False,
            }
        )

    should_stop = False

    setup_rc = 0
    teardown_rc = 0
    rc = 0
    success = False
    log_path: str | None = None
    assertion_index: int | None = None
    failure: AssertionFailure | None = None

    try:
        test_dir = os.path.dirname(os.path.abspath(path))

        # 1. Setup
        setup_file = os.path.join(test_dir, "statest_setup.do")
        if os.path.exists(setup_file):
            setup_res = await asyncio.to_thread(
                client.call, "run", {
                    "session": session_id,
                    "code": f'statest_reset\ndo "{setup_file}"',
                    "echo": False,
                }
            )
            setup_rc = setup_res.get("rc", 0)
            if setup_rc != 0:
                duration = time.time() - start_time
                return TestResult(
                    test_path=path, success=False, rc=setup_rc, setup_rc=setup_rc,
                    duration_seconds=duration, log_path=setup_res.get("log_path"),
                )
        else:
            # Still need to reset even if no setup file
            await asyncio.to_thread(
                client.call, "run", {
                    "session": session_id,
                    "code": "statest_reset",
                    "echo": False,
                }
            )

        # 2. Test
        test_res = await asyncio.to_thread(
            client.call, "run_file", {
                "session": session_id,
                "path": os.path.abspath(path),
                "echo": False,
            }
        )
        rc = test_res.get("rc", 0)
        success = test_res.get("ok", False) or rc == 0
        log_path = test_res.get("log_path")

        if not success:
            assertion_index, failure = await _fetch_assertion_failure(
                client, session_id, path, rc, log_path
            )

        # 3. Teardown (always runs)
        teardown_file = os.path.join(test_dir, "statest_teardown.do")
        if os.path.exists(teardown_file):
            teardown_res = await asyncio.to_thread(
                client.call, "run_file", {
                    "session": session_id,
                    "path": teardown_file,
                    "echo": False,
                }
            )
            teardown_rc = teardown_res.get("rc", 0)

        duration = time.time() - start_time
        return TestResult(
            test_path=path,
            success=success and (teardown_rc == 0),
            rc=rc,
            assertion_index=assertion_index,
            failure=failure,
            log_path=log_path,
            duration_seconds=duration,
            setup_rc=setup_rc,
            teardown_rc=teardown_rc,
        )
    finally:
        if pool:
            await pool.release(session_id)


async def run_tests(
    path: str,
    base_session: str = "default",
    parallel: bool = False,
    max_workers: int = 4,
    junit_xml_path: str | None = None,
) -> TestSuiteSummary:
    """Discover and run all tests under path."""
    test_files = discover_tests(path)

    if not test_files:
        return TestSuiteSummary(
            path=path,
            total_tests=0,
            passed=0,
            failed=0,
            results=[],
            summary_text="No tests found.",
            junit_xml_path=junit_xml_path,
        )

    # Initialize pool
    pool_size = max_workers if parallel else 1
    pool = StatestSessionPool(base_session=base_session, size=pool_size)

    try:
        # Run conftest.do if present — in the first pooled session
        conftest_file = os.path.join(path, "statest_conftest.do")
        if os.path.exists(conftest_file):
            sid = await pool.acquire()
            try:
                await asyncio.to_thread(
                    pool._client.call, "run_file", {
                        "session": sid,
                        "path": os.path.abspath(conftest_file),
                        "echo": False,
                    }
                )
            finally:
                await pool.release(sid)

        results: list[TestResult] = []

        if parallel:
            results = await asyncio.gather(
                *(run_test(f, base_session=base_session, pool=pool) for f in test_files)
            )
        else:
            for f in test_files:
                res = await run_test(f, base_session=base_session, pool=pool)
                results.append(res)

        # Sort results by path for deterministic output
        results.sort(key=lambda r: r.test_path)

        passed = sum(1 for r in results if r.success)
        failed = len(results) - passed
        summary_text = f"Ran {len(results)} tests. {passed} passed, {failed} failed."

        summary = TestSuiteSummary(
            path=path,
            total_tests=len(results),
            passed=passed,
            failed=failed,
            results=results,
            summary_text=summary_text,
            junit_xml_path=junit_xml_path,
        )

        if junit_xml_path:
            write_junit_xml(summary, junit_xml_path)

        return summary
    finally:
        await pool.drain()

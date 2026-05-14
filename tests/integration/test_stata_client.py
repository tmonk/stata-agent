"""Integration tests for StataClient with a real Stata backend.

These tests require a licensed Stata installation (macOS/Linux/Windows).
They are auto-skipped if Stata is not available or when STATA_AGENT_MOCK=1.
"""

from __future__ import annotations

import os
import tempfile

import pytest


@pytest.fixture(scope="module")
def stata_client():
    """Create a StataClient, initialise pystata-x, and clean up."""
    import sys
    import os

    # Use the known StataNow root path directly (avoids find_stata_path()
    # which can hang on macOS when trying to verify the GUI binary).
    # For CI or other machines, set STATA_PATH env var to the root dir
    # that contains utilities/.
    root = os.environ.get("STATA_PATH", "/Applications/StataNow")
    edition = "se"

    from pystata_x.stata_setup import config as px_setup_config
    px_setup_config(root, edition, splash=False)

    from stata_agent.stata_client import StataClient

    client = StataClient()
    client.init()
    yield client
    client.close()


@pytest.mark.requires_stata
def test_stata_run_basic(stata_client):
    """Verify _stata_run returns output and rc for a simple command."""
    stdout, rc = stata_client._stata_run("display 1+1", echo=False)
    assert rc == 0
    assert "2" in stdout

    stdout, rc = stata_client._stata_run("display 2+2", echo=True)
    assert rc == 0
    # With echo=True, the command itself should appear in output
    assert "display" in stdout or "2+2" in stdout
    assert "4" in stdout


@pytest.mark.requires_stata
def test_stata_run_error_detection(stata_client):
    """Verify _stata_run correctly detects and returns error codes."""
    # error NNN always produces rc=NNN
    stdout, rc = stata_client._stata_run("error 111", echo=False)
    assert rc == 111

    stdout, rc = stata_client._stata_run("error 601", echo=False)
    assert rc == 601


@pytest.mark.requires_stata
def test_stata_run_multi_line(stata_client):
    """Verify multi-line code execution returns correct rc."""
    # Multi-line code: first line succeeds, second fails
    code = (
        'display "before"\n'
        'error 111\n'
        'display "after"'
    )
    stdout, rc = stata_client._stata_run(code, echo=False)
    # Without capture, Stata stops at 'error 111'
    assert rc == 111
    assert "before" in stdout
    # "after" should NOT appear because execution stopped at error 111
    assert "after" not in stdout


@pytest.mark.requires_stata
def test_stata_run_rc_accuracy(stata_client):
    """Verify rc from StataSO_Execute matches _rc after capture noisily."""
    from pystata_x import _config as _px_config

    # Run a command that fails, wrapped in capture noisily
    # The StataSO_Execute rc will be 0 (capture succeeds), but _rc holds error
    code = (
        'capture noisily {\n'
        '    error 111\n'
        '}\n'
        'display "_rc=" _rc'
    )
    stdout, rc = stata_client._stata_run(code, echo=False)
    # rc from StataSO_Execute is 0 because capture succeeded
    assert rc == 0
    # But _rc should be 111 (displayed in output)
    assert "_rc=111" in stdout


@pytest.mark.requires_stata
def test_run_method_rc(stata_client):
    """Verify the public run() method returns correct rc."""
    # Successful command
    result = stata_client.run("display 1+1", echo=False)
    assert result.ok is True
    assert result.rc == 0

    # Failed command
    result = stata_client.run("error 111", echo=False)
    assert result.ok is False
    assert result.rc == 111


@pytest.mark.requires_stata
def test_run_file_method_rc(stata_client):
    """Verify run_file() returns correct rc from do-file execution."""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".do", delete=False, encoding="utf-8"
    ) as f:
        f.write('display "Hello from do-file"\n')
        f.write('display 2+2\n')
        do_path = f.name

    try:
        result = stata_client.run_file(do_path, echo=False)
        assert result.ok is True
        assert result.rc == 0
        assert "Hello from do-file" in result.stdout
        assert "4" in result.stdout
    finally:
        os.unlink(do_path)


@pytest.mark.requires_stata
def test_stata_run_stdout_capture(stata_client):
    """Verify stdout is fully captured and returned."""
    code = (
        'display "line 1"\n'
        'display "line 2"\n'
        'display "line 3"'
    )
    stdout, rc = stata_client._stata_run(code, echo=False)
    assert rc == 0
    assert "line 1" in stdout
    assert "line 2" in stdout
    assert "line 3" in stdout

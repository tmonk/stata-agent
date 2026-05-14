"""Unit tests for ErrorExtractor."""

from __future__ import annotations

from pathlib import Path

from stata_agent.error_extractor import ErrorExtractor


def _extract(log_text: str, default_rc: int | None = None):
    return ErrorExtractor().extract(log_text, default_rc)


def _extract_tail(log_path: str | Path, default_rc: int | None = None):
    return ErrorExtractor().extract_from_tail(str(log_path), default_rc)


def _extract_deep(log_path: str | Path, default_rc: int | None = None):
    return ErrorExtractor().extract_deep(str(log_path), default_rc)


class TestMarkerExtraction:
    """Phase 1: structured [AGENT-ERROR] markers."""

    def test_basic_marker(self):
        log = (
            ". regress y z_nonexistent\n"
            "variable z_nonexistent not found\n"
            "r(111);\n"
            "[AGENT-ERROR] rc=111\n"
            "[AGENT-MSG] variable not found\n"
        )
        err = _extract(log)
        assert err is not None
        assert err.rc == 111
        assert err.marker_found is True
        assert err.source == "marker"
        assert "variable not found" in err.message

    def test_marker_no_msg(self):
        log = "[AGENT-ERROR] rc=9\n"
        err = _extract(log)
        assert err is not None
        assert err.rc == 9
        assert err.marker_found is True
        assert "r(9)" in err.message

    def test_marker_mata(self):
        log = (
            "mata: x = y + z\n"
            "<istmt>:  3499  y not found\n"
            "r(3499);\n"
            "[AGENT-ERROR] rc=3499\n"
        )
        err = _extract(log)
        assert err is not None
        assert err.rc == 3499
        assert err.marker_found is True

    def test_no_marker(self):
        log = ". display 1+1\n2\nend of do-file\n"
        err = _extract(log)
        assert err is None

    def test_empty_log(self):
        err = _extract("")
        assert err is None

    def test_whitespace_only(self):
        err = _extract("   \n  \n")
        assert err is None


class TestFallbackExtraction:
    """Phase 2: native error signatures without markers."""

    def test_r_code_simple(self):
        log = (
            ". regress y z_nonexistent\n"
            "variable z_nonexistent not found\n"
            "r(111);\n"
        )
        err = _extract(log)
        assert err is not None
        assert err.rc == 111
        assert err.source == "r_code"
        assert err.marker_found is False
        assert "not found" in err.message

    def test_mata_error(self):
        log = (
            ". mata: x = y + z\n"
            "                 <istmt>:  3499  y not found\n"
            "r(3499);\n"
        )
        err = _extract(log)
        assert err is not None
        assert err.source == "mata"
        assert "y not found" in err.message
        assert err.rc == 3499

    def test_assertion_failure(self):
        log = (
            ". assert 1==0\n"
            "assertion is false\n"
            "r(9);\n"
        )
        err = _extract(log)
        assert err is not None
        assert err.rc == 9
        assert err.source == "assertion"
        assert err.message == "assertion is false"

    def test_break_interrupt(self):
        log = "--Break--\nr(1);\n"
        err = _extract(log)
        assert err is not None
        assert err.rc == 1
        assert err.source == "break"
        assert "Break" in err.message

    def test_error_111(self):
        log = ". error 111\ninvalid syntax\nr(111);\n"
        err = _extract(log)
        assert err is not None
        assert err.rc == 111
        assert err.source == "r_code"

    def test_no_error(self):
        log = (
            ". sysuse auto, clear\n"
            "(1978 automobile data)\n"
            ". display 1+1\n"
            "2\n"
        )
        err = _extract(log)
        assert err is None


class TestTailExtraction:
    """Fast path: extract from last 32 KB of file."""

    def test_extract_from_tail_no_file(self):
        err = _extract_tail("/nonexistent/path.log")
        assert err is None

    def test_extract_deep_no_file(self):
        err = _extract_deep("/nonexistent/path.log")
        assert err is None


def test_extract_multiple_errors_takes_last():
    """Backward scan should find the last (most recent) error."""
    log = "r(1);\nsome output\nr(9);\n"
    err = _extract(log)
    assert err is not None
    assert err.rc == 9  # most recent error

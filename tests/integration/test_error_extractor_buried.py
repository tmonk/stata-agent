"""Integration test: ErrorExtractor vs a real Stata trace-swollen log.

The fixture log (big_trace_with_buried_error.log) is a ~76K-line, 2.8 MB
Stata batch log produced with `set trace on`. An error (`confirm variable
__nonexist_xyz__` under `capture noisily`) occurs at line ~22,710, but
trace output from subsequent iterations and a postamble continues for
another ~53,000 lines.

This tests that:
  - extract_from_tail() — the fast 32KB tail scan — misses the error
  - extract_deep() — full backward scan — finds the buried error
  - The returned StructuredError has the correct rc, message, and source
"""

from __future__ import annotations

from pathlib import Path

import pytest

from stata_agent.error_extractor import ErrorExtractor


FIXTURE_DIR = Path(__file__).resolve().parent.parent / "fixtures"
LOG_PATH = FIXTURE_DIR / "big_trace_with_buried_error.log"


@pytest.mark.skipif(
    not LOG_PATH.exists(),
    reason=f"Fixture log not found at {LOG_PATH}; "
    "run 'stata-se -b do testdata/big_trace_with_buried_error.do' to generate it",
)
class TestErrorExtractorBuriedError:
    """Tests that the error extractor handles real trace-swollen Stata logs."""

    def setup_method(self) -> None:
        self.extractor = ErrorExtractor()
        self.log_text = LOG_PATH.read_text("utf-8", errors="replace")
        self.lines = self.log_text.splitlines()

    # ------------------------------------------------------------------
    #  Basic structure
    # ------------------------------------------------------------------

    def test_log_is_large(self) -> None:
        assert len(self.lines) > 50_000, (
            f"Log should be >50K lines to exercise tail-scan limits; "
            f"got {len(self.lines)}"
        )

    def test_error_is_buried(self) -> None:
        """The buried error is not in the last 32 KB of the file."""
        # Find the error line
        error_line = next(
            i for i, line in enumerate(self.lines, 1)
            if "__nonexist_xyz__ not found" in line
        )
        total = len(self.lines)
        assert total - error_line > 1000, (
            f"Error at line {error_line} is too close to end ({total} lines); "
            f"tail scan (32 KB ≈ ~500 lines) would reach it"
        )

    # ------------------------------------------------------------------
    #  Tail-scan (fast path) — should MISS the error
    # ------------------------------------------------------------------

    def test_tail_scan_misses_buried_error(self) -> None:
        """extract_from_tail() reads only the last 32 KB and should miss
        the buried error."""
        err = self.extractor.extract_from_tail(str(LOG_PATH))
        if err is not None:
            # If the tail scan somehow finds something, it should NOT be
            # the buried confirm-variable error
            assert "nonexist" not in (err.message or ""), (
                f"Tail scan should not reach the buried error but found: "
                f"rc={err.rc} msg={err.message}"
            )

    def test_tail_scan_returns_none_or_unrelated(self) -> None:
        """The tail portion of the log has no r(code); line (the do-file
        exits cleanly), so tail scan should return None."""
        err = self.extractor.extract_from_tail(str(LOG_PATH))
        # The do-file runs to completion with exit code 0, so there
        # should be no r(NNN); in the tail 32 KB.
        assert err is None or err.rc == 0, (
            f"Expected None or rc=0 from clean exit; got rc={err.rc}"
        )

    # ------------------------------------------------------------------
    #  Deep scan (full backward) — should FIND the buried error
    # ------------------------------------------------------------------

    def test_deep_scan_finds_buried_error(self) -> None:
        """extract_deep() scans the full file backward and finds the
        buried confirm-variable error."""
        err = self.extractor.extract_deep(str(LOG_PATH))
        assert err is not None, "Deep scan should find the buried error"
        assert err.rc == 111, (
            f"Expected rc=111 (variable not found); got rc={err.rc}"
        )
        assert err.source in ("r_code", "native_msg"), (
            f"Expected source='r_code' or 'native_msg'; got '{err.source}'"
        )

    def test_deep_scan_context_includes_error_line(self) -> None:
        """The context field should include the 'not found' line."""
        err = self.extractor.extract_deep(str(LOG_PATH))
        assert err is not None
        assert "__nonexist_xyz__" in err.context, (
            "Context should include the failing variable name"
        )
        assert "not found" in err.context, (
            "Context should include the 'not found' message"
        )

    # ------------------------------------------------------------------
    #  Full-text extract (no file I/O) — should also find it
    # ------------------------------------------------------------------

    def test_extract_from_text_finds_error(self) -> None:
        """extract() on the full text should find the buried error."""
        err = self.extractor.extract(self.log_text)
        assert err is not None
        assert err.rc == 111
        assert "not found" in (err.message or "")

    # ------------------------------------------------------------------
    #  Edge: empty / truncated
    # ------------------------------------------------------------------

    def test_extract_from_empty_returns_none(self) -> None:
        assert self.extractor.extract("") is None
        assert self.extractor.extract("   \n  \n") is None

    def test_extract_from_nonexistent_file_returns_none(self) -> None:
        assert (
            self.extractor.extract_from_tail("/nonexistent/path.log") is None
        )
        assert (
            self.extractor.extract_deep("/nonexistent/path.log") is None
        )

    # ------------------------------------------------------------------
    #  Verify the fixture structure (documentation)
    # ------------------------------------------------------------------

    def test_fixture_has_exactly_one_trace_error(self) -> None:
        """The buried error (trace-level 'not found') appears exactly once.
        The do-file's FINISHED display message also contains the variable name
        but that's not a Stata error — only the trace output from the
        capture noisily confirm command counts."""
        # The real error is preceded by the capture noisily command in trace
        capture_lines = sum(
            1 for i, line in enumerate(self.lines)
            if "capture noisily confirm variable __nonexist_xyz__" in line
            and i + 1 < len(self.lines)
            and "not found" in self.lines[i + 1]
        )
        assert capture_lines == 1, (
            f"Expected exactly 1 capture+error pair; got {capture_lines}"
        )
        # Also count raw 'not found' lines for the variable
        raw_count = sum(
            1 for line in self.lines
            if "__nonexist_xyz__ not found" in line
        )
        assert raw_count >= 1, "Should have at least one raw error line"
        # The extra occurrences are our display message, which is not a Stata error

    def test_fixture_ends_with_clean_exit(self) -> None:
        """The very last line should be 'end of do-file' without r(code)."""
        last_lines = self.lines[-5:]
        combined = "\n".join(last_lines)
        assert "end of do-file" in combined
        # No r(code); in the final lines
        import re
        rcode_lines = [
            l for l in last_lines if re.search(r"^r\(\d+\);$", l.strip())
        ]
        assert len(rcode_lines) == 0, (
            f"Expected clean exit with no r(code); but found: {rcode_lines}"
        )

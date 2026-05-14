"""Structured error extraction from Stata text logs.

Two-phase parser:
  Phase 1: Forward scan for [AGENT-ERROR] / [AGENT-MSG] markers (authoritative).
  Phase 2: Fallback backward scan for native error signatures (r(NNN);,
           Mata <istmt>, assertion failures).
"""

from __future__ import annotations

import re
from typing import Optional

from stata_agent.models import StructuredError

# Patterns for structured markers (Phase 1)
MARKER_ERROR_RE = re.compile(r"\[AGENT-ERROR\] rc=(\d+)")
MARKER_MSG_RE = re.compile(r"\[AGENT-MSG\] (.+)")

# Fallback patterns for text-mode logs (Phase 2)
R_CODE_RE = re.compile(r"^r\((\d+)\);?\s*$")
MATA_ERROR_RE = re.compile(r"<istmt>:\s*(\d+)\s+(.+)")
ASSERTION_RE = re.compile(r"assertion is false")
NOT_FOUND_RE = re.compile(r"not found$", re.IGNORECASE)
INVALID_SYNTAX_RE = re.compile(r"invalid syntax$", re.IGNORECASE)
NO_OBSERVATIONS_RE = re.compile(r"no observations", re.IGNORECASE)
BREAK_ERROR_RE = re.compile(r"^--Break--$", re.IGNORECASE)

# rc code for each native error pattern
PATTERN_RC: dict[re.Pattern, int] = {
    NOT_FOUND_RE: 111,
    INVALID_SYNTAX_RE: 198,
    NO_OBSERVATIONS_RE: 2000,
    ASSERTION_RE: 9,
}

TAIL_SCAN_BYTES = 32768

# Combined regex built from existing error patterns (no duplication).
# Used by extract_deep for a single-pass scan over the full text.
_COMBINED_ERROR_RE: Optional[re.Pattern] = None


def _build_combined_error_re() -> re.Pattern:
    """Build a single combined str regex from the existing error patterns.

    Avoids hardcoding new patterns — joins existing pattern strings.
    Cached for reuse. Returns a MULTILINE str regex for fast single-pass
    scanning over decoded text.
    """
    global _COMBINED_ERROR_RE
    if _COMBINED_ERROR_RE is not None:
        return _COMBINED_ERROR_RE

    parts = []
    # Fallback native error patterns only (Phase 2)
    parts.append(R_CODE_RE.pattern)
    parts.append(MATA_ERROR_RE.pattern)
    parts.append(ASSERTION_RE.pattern)
    parts.append(BREAK_ERROR_RE.pattern)
    for p in PATTERN_RC:
        parts.append(p.pattern)

    combined = "|".join(f"(?:{p})" for p in parts)
    flags = re.MULTILINE | re.IGNORECASE
    _COMBINED_ERROR_RE = re.compile(combined, flags)
    return _COMBINED_ERROR_RE


class ErrorExtractor:
    """Extract structured errors from text logs."""

    def extract(
        self, log_text: str, default_rc: Optional[int] = None
    ) -> Optional[StructuredError]:
        """Return parsed StructuredError or None.

        Phase 1 scans for structured [AGENT-ERROR] markers.
        Phase 2 falls back to native error pattern scanning.
        """
        if not log_text or not log_text.strip():
            return None

        lines = log_text.splitlines()

        # Phase 1: structured markers (most authoritative)
        err = self._marker_extract(lines)
        if err is not None:
            return err

        # Phase 2: fallback backward scan
        return self._fallback_extract(lines, default_rc)

    def extract_from_tail(
        self, log_path: str, default_rc: Optional[int] = None
    ) -> Optional[StructuredError]:
        """Read last 32 KB of a log file and extract errors.

        Fast path: reads only the tail. Returns None if no errors found.
        """
        import os

        try:
            file_size = os.path.getsize(log_path)
        except OSError:
            return None

        if file_size == 0:
            return None

        with open(log_path, "rb") as f:
            start = max(0, file_size - TAIL_SCAN_BYTES)
            f.seek(start)
            data = f.read()

        # Align to newline if we started mid-line
        if start > 0:
            nl = data.find(b"\n")
            if nl != -1:
                data = data[nl + 1 :]

        text = data.decode("utf-8", errors="replace")
        return self.extract(text, default_rc)

    def extract_deep(
        self, log_path: str, default_rc: Optional[int] = None
    ) -> Optional[StructuredError]:
        """Deep backward scan of entire log file.

        First tries fast tail scan (32 KB). If nothing found, reads
        the full file and runs the two-phase parser (markers +
        fallback backward scan) on the decoded text.
        """
        # Fast path
        err = self.extract_from_tail(log_path, default_rc)
        if err is not None:
            return err

        import os
        try:
            file_size = os.path.getsize(log_path)
        except OSError:
            return None

        if file_size == 0:
            return None

        with open(log_path, "rb") as f:
            data = f.read()

        text = data.decode("utf-8", errors="replace")
        lines = text.splitlines()

        # Phase 2: backward scan for native errors
        err = self._fallback_extract(lines, default_rc)
        if err is not None:
            return err

        # Phase 1: forward scan for structured markers
        return self._marker_extract(lines)

    def _marker_extract(
        self, lines: list[str]
    ) -> Optional[StructuredError]:
        """Phase 1: scan forward for [AGENT-ERROR] markers."""
        marker_rc: Optional[int] = None
        marker_msg: Optional[str] = None
        marker_line_idx: Optional[int] = None

        for i, line in enumerate(lines):
            m = MARKER_ERROR_RE.search(line)
            if m:
                marker_rc = int(m.group(1))
                marker_line_idx = i
                for j in range(i + 1, min(i + 3, len(lines))):
                    mm = MARKER_MSG_RE.search(lines[j])
                    if mm:
                        marker_msg = mm.group(1).strip()
                        break
                break

        if marker_rc is not None:
            context_start = max(0, marker_line_idx - 10)
            context = "\n".join(lines[context_start : marker_line_idx + 3])
            return StructuredError(
                rc=marker_rc,
                message=marker_msg or f"Stata error r({marker_rc})",
                context=context,
                marker_found=True,
                source="marker",
            )

        return None

    def _fallback_extract(
        self, lines: list[str], default_rc: Optional[int]
    ) -> Optional[StructuredError]:
        """Phase 2: scan backwards for native error signatures.

        Priority: specific patterns (assertion, mata, break) > generic r_code.
        When we find an r(NNN); line, check the preceding lines for context
        to determine the specific source.
        """
        for i in range(len(lines) - 1, -1, -1):
            line = lines[i].strip()

            # Check specific patterns first (on their own lines)
            if BREAK_ERROR_RE.search(line):
                context_start = max(0, i - 5)
                ctx = "\n".join(lines[context_start : min(i + 3, len(lines))])
                return StructuredError(
                    rc=1, message="--Break--", context=ctx,
                    marker_found=False, source="break",
                )

            if ASSERTION_RE.search(line):
                context_start = max(0, i - 5)
                ctx = "\n".join(lines[context_start : i + 1])
                return StructuredError(
                    rc=9, message="assertion is false", context=ctx,
                    marker_found=False, source="assertion",
                )

            if MATA_ERROR_RE.search(line):
                m = MATA_ERROR_RE.search(line)
                rc_val = int(m.group(1))
                context_start = max(0, i - 10)
                ctx = "\n".join(lines[context_start : i + 1])
                # Look ahead for r(NNN);
                rc = default_rc or rc_val
                if i + 1 < len(lines):
                    rm = R_CODE_RE.match(lines[i + 1].strip())
                    if rm:
                        rc = int(rm.group(1))
                return StructuredError(
                    rc=rc, message=m.group(2).strip(), context=ctx,
                    marker_found=False, source="mata",
                )

            # Generic r(NNN); — check preceding lines for specific context first
            m = R_CODE_RE.match(line)
            if m:
                rc = int(m.group(1))
                context_start = max(0, i - 15)
                ctx_lines = lines[context_start : i + 1]
                ctx = "\n".join(ctx_lines)
                msg = f"Stata error r({rc})"
                source = "r_code"
                # Check preceding lines for specific error context
                if i > 0:
                    prev = lines[i - 1].strip()
                    if prev and not prev.startswith("."):
                        msg = prev
                    # Detective work: check if preceding lines have specific signatures
                    for j in range(max(0, i - 3), i):
                        pl = lines[j].strip()
                        if ASSERTION_RE.search(pl):
                            source = "assertion"
                            break
                        if BREAK_ERROR_RE.search(pl):
                            source = "break"
                            break
                        if MATA_ERROR_RE.search(pl):
                            source = "mata"
                            break
                return StructuredError(
                    rc=rc, message=msg, context=ctx,
                    marker_found=False, source=source,
                )

            # Native error message without r(NNN); (e.g. capture noisily)
            # The error message is printed but r(code); is suppressed.
            for pattern, rc in PATTERN_RC.items():
                if pattern.search(line):
                    context_start = max(0, i - 10)
                    ctx = "\n".join(lines[context_start : i + 1])
                    return StructuredError(
                        rc=rc,
                        message=line,
                        context=ctx,
                        marker_found=False,
                        source="native_msg",
                    )

        return None

    def _check_error_line(
        self, line: str, default_rc: Optional[int]
    ) -> Optional[StructuredError]:
        """Check a single isolated line against error patterns."""
        # r(NNN);
        m = R_CODE_RE.match(line)
        if m:
            return StructuredError(
                rc=int(m.group(1)), message=f"Stata error r({m.group(1)})",
                context=line, marker_found=False, source="r_code",
            )

        # Mata error format
        m = MATA_ERROR_RE.search(line)
        if m:
            return StructuredError(
                rc=int(m.group(1)), message=m.group(2).strip(),
                context=line, marker_found=False, source="mata",
            )

        # Assertion
        if ASSERTION_RE.search(line):
            return StructuredError(
                rc=9, message="assertion is false",
                context=line, marker_found=False, source="assertion",
            )

        # Break
        if BREAK_ERROR_RE.search(line):
            return StructuredError(
                rc=1, message="--Break--",
                context=line, marker_found=False, source="break",
            )

        # Native error messages (e.g. capture noisily suppresses r(code);)
        for pattern, rc in PATTERN_RC.items():
            if pattern.search(line):
                return StructuredError(
                    rc=rc, message=line,
                    context=line, marker_found=False, source="native_msg",
                )

        return None

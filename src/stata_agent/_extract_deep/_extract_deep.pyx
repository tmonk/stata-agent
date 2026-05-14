# cython: language_level=3, boundscheck=False, wraparound=False, cdivision=True
"""Cython-accelerated deep error scan for Stata log files.

CONSTRAINT: No hardcoded error pattern strings, byte-level checks, or
pattern pre-filters. All error matching MUST use ONLY the existing
re.compile pattern objects passed by the Python caller. This ensures
that if error patterns change in future Stata releases, only the
re.compile definitions in error_extractor.py need updating.

Implementation approach:
- Typed Cython loops (cdef, cpdef) to reduce Python-level loop overhead
- Patterns received as compiled re.Pattern objects from Python
- Same two-phase algorithm as the Python implementation
"""

import re
from libc.string cimport memchr
from cpython.list cimport PyList_GET_ITEM, PyList_GET_SIZE
from cpython.object cimport PyObject_CallFunctionObjArgs
from cpython.unicode cimport PyUnicode_FromString, PyUnicode_AsUTF8String


cdef struct _ErrorResult:
    int rc
    int has_error
    int marker_found
    int line_idx
    char* message
    char* context
    char* source


cdef str _decode(bytes data, Py_ssize_t start, Py_ssize_t end):
    """Decode a bytes slice to str, trimming trailing whitespace."""
    cdef bytes raw
    raw = data[start:end]
    if raw is None:
        return ""
    return raw.decode("utf-8", errors="replace")


def extract_deep_scan(
    str log_path,
    object r_code_re,
    object mata_error_re,
    object assertion_re,
    object break_error_re,
    object marker_error_re,
    object marker_msg_re,
    list pattern_rc_pairs,
    int default_rc=-1,
):
    """Fast deep scan of a Stata log file.

    Args:
        log_path: Path to the log file.
        r_code_re: Compiled re for r(NNN);
        mata_error_re: Compiled re for Mata <istmt> errors
        assertion_re: Compiled re for assertion failures
        break_error_re: Compiled re for --Break--
        marker_error_re: Compiled re for [AGENT-ERROR] markers
        marker_msg_re: Compiled re for [AGENT-MSG] markers
        pattern_rc_pairs: List of (pattern, rc) for fallback patterns
        default_rc: Default return code if not found in match

    Returns:
        dict with keys (rc, message, context, source, line_idx, marker_found)
        or None if no error found.
    """
    # Read file
    cdef bytes raw_data
    try:
        with open(log_path, "rb") as f:
            raw_data = f.read()
    except OSError:
        return None

    cdef Py_ssize_t file_size = len(raw_data)
    if file_size == 0:
        return None

    # Decode once and split into lines
    cdef str text = raw_data.decode("utf-8", errors="replace")
    cdef list lines = text.splitlines()
    cdef Py_ssize_t n_lines = PyList_GET_SIZE(lines)
    cdef Py_ssize_t i
    cdef str line, stripped
    cdef object match, m
    cdef int rc_val
    cdef Py_ssize_t context_start
    cdef Py_ssize_t j, n_patterns
    cdef object pattern, pat_rc

    n_patterns = PyList_GET_SIZE(pattern_rc_pairs)

    # ---- Phase 2: backward scan for native errors ----
    for i in range(n_lines - 1, -1, -1):
        line = <str>PyList_GET_ITEM(lines, i)
        stripped = line.strip()
        if not stripped:
            continue

        # 1. Break
        match = break_error_re.search(stripped)
        if match is not None:
            context_start = 0 if i < 5 else i - 5
            ctx = "\n".join(lines[context_start:i + 3])
            return {
                "rc": 1,
                "message": "--Break--",
                "context": ctx,
                "source": "break",
                "line_idx": i,
                "marker_found": False,
            }

        # 2. Assertion
        match = assertion_re.search(stripped)
        if match is not None:
            context_start = 0 if i < 5 else i - 5
            ctx = "\n".join(lines[context_start:i + 1])
            return {
                "rc": 9,
                "message": "assertion is false",
                "context": ctx,
                "source": "assertion",
                "line_idx": i,
                "marker_found": False,
            }

        # 3. Mata error
        match = mata_error_re.search(stripped)
        if match is not None:
            rc_val = int(match.group(1))
            context_start = 0 if i < 10 else i - 10
            ctx = "\n".join(lines[context_start:i + 1])
            rc = default_rc if default_rc >= 0 else rc_val
            if i + 1 < n_lines:
                m = r_code_re.match((<str>PyList_GET_ITEM(lines, i + 1)).strip())
                if m is not None:
                    rc = int(m.group(1))
            return {
                "rc": rc,
                "message": match.group(2).strip(),
                "context": ctx,
                "source": "mata",
                "line_idx": i,
                "marker_found": False,
            }

        # 4. Generic r(NNN);
        match = r_code_re.match(stripped)
        if match is not None:
            rc_val = int(match.group(1))
            context_start = 0 if i < 15 else i - 15
            ctx_lines = lines[context_start:i + 1]
            ctx = "\n".join(ctx_lines)
            msg = f"Stata error r({rc_val})"
            source_name = "r_code"
            # Check preceding lines for context
            if i > 0:
                prev = (<str>PyList_GET_ITEM(lines, i - 1)).strip()
                if prev and not prev.startswith("."):
                    msg = prev
                for j in range(0 if i < 3 else i - 3, i):
                    pl = (<str>PyList_GET_ITEM(lines, j)).strip()
                    if assertion_re.search(pl):
                        source_name = "assertion"
                        break
                    if break_error_re.search(pl):
                        source_name = "break"
                        break
                    if mata_error_re.search(pl):
                        source_name = "mata"
                        break
            return {
                "rc": rc_val,
                "message": msg,
                "context": ctx,
                "source": source_name,
                "line_idx": i,
                "marker_found": False,
            }

        # 5. Native error messages (PATTERN_RC)
        for j in range(n_patterns):
            pattern = <object>PyList_GET_ITEM(pattern_rc_pairs, j)
            # pattern is a tuple (compiled_re, rc_int)
            pat_rc = pattern
            if isinstance(pattern, (list, tuple)):
                pat_re = <object>pattern[0]
                pat_rc_val = <int>pattern[1]
            else:
                continue
            match = (<object>pat_re).search(stripped)
            if match is not None:
                context_start = 0 if i < 10 else i - 10
                ctx = "\n".join(lines[context_start:i + 1])
                return {
                    "rc": pat_rc_val,
                    "message": line,
                    "context": ctx,
                    "source": "native_msg",
                    "line_idx": i,
                    "marker_found": False,
                }

    # ---- Phase 1: forward scan for markers ----
    cdef int marker_rc = -1
    cdef str marker_msg_str = ""
    cdef int marker_line_idx = -1

    for i in range(n_lines):
        line = <str>PyList_GET_ITEM(lines, i)
        match = marker_error_re.search(line)
        if match is not None:
            marker_rc = int(match.group(1))
            marker_line_idx = i
            for j in range(i + 1, min(i + 3, n_lines)):
                m = marker_msg_re.search(<str>PyList_GET_ITEM(lines, j))
                if m is not None:
                    marker_msg_str = m.group(1).strip()
                    break
            break

    if marker_rc >= 0:
        context_start = 0 if marker_line_idx < 10 else marker_line_idx - 10
        ctx = "\n".join(lines[context_start:marker_line_idx + 3])
        return {
            "rc": marker_rc,
            "message": marker_msg_str or f"Stata error r({marker_rc})",
            "context": ctx,
            "source": "marker",
            "line_idx": marker_line_idx,
            "marker_found": True,
        }

    return None

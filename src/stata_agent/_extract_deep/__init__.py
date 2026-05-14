"""Cython-accelerated deep error scan for Stata log files.

This module provides a Cython-accelerated version of the extract_deep
function (full-file error scan). Falls back gracefully to the pure-Python
implementation if the Cython extension has not been compiled yet.
"""

from __future__ import annotations

import importlib
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Try to import the compiled Cython extension
_cython_available = False
_extract_fn = None  # type: ignore


def _load_cython_ext():
    """Try to load the compiled Cython extension module."""
    global _cython_available, _extract_fn
    try:
        from stata_agent._extract_deep import _extract_deep  # type: ignore
        _extract_fn = _extract_deep.extract_deep_scan
        _cython_available = True
        logger.debug("Cython _extract_deep extension loaded successfully")
    except (ImportError, AttributeError) as e:
        _cython_available = False
        _extract_fn = None
        logger.debug("Cython _extract_deep extension not available: %s", e)


def maybe_extract_deep_scan(
    log_path: str,
    r_code_re: Any,
    mata_error_re: Any,
    assertion_re: Any,
    break_error_re: Any,
    marker_error_re: Any,
    marker_msg_re: Any,
    pattern_rc_pairs: list,
    default_rc: int = -1,
) -> Optional[dict]:
    """Call the Cython extension if available, otherwise return None.

    The caller should fall back to the Python implementation if None is returned.
    """
    if not _cython_available:
        _load_cython_ext()
    if _cython_available and _extract_fn is not None:
        try:
            return _extract_fn(
                log_path,
                r_code_re,
                mata_error_re,
                assertion_re,
                break_error_re,
                marker_error_re,
                marker_msg_re,
                pattern_rc_pairs,
                default_rc,
            )
        except Exception as e:
            logger.warning("Cython extract_deep_scan failed: %s; falling back to Python", e)
            return None
    return None

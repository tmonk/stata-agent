"""Stata executable auto-discovery across macOS, Linux, and Windows."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Optional

# Module-level cache for find_stata_path() results.
# Populated once on first successful discovery; cleared via clear_cache().
_CACHE: dict[str, tuple[str, str]] = {}
_CACHE_KEY = "discovery_result"


def _normalize_platform() -> str:
    """Return the current platform identifier."""
    return sys.platform


def _parse_edition_from_binary(path: str) -> str:
    """Extract Stata edition (SE/MP/BE) from a binary path.

    Inspects the filename stem (case-insensitive) for edition markers.
    Defaults to SE when no marker is present.
    """
    name = Path(path).stem.lower()
    if "mp" in name:
        return "MP"
    if "be" in name:
        return "BE"
    return "SE"


def _platform_candidates() -> list[str]:
    """Build a list of candidate binary paths for the current platform.

    Paths are returned in priority order — more common / general
    installations first.
    """
    plat = _normalize_platform()
    paths: list[str] = []

    if plat == "darwin":
        # macOS: .app bundles first, then /usr/local/bin
        for edition in ("SE", "MP", "BE"):
            paths.append(
                f"/Applications/StataNow/Stata{edition}.app/Contents/MacOS/Stata{edition}"
            )
        for edition in ("SE", "MP", "BE"):
            paths.append(
                f"/Applications/Stata/Stata{edition}.app/Contents/MacOS/Stata{edition}"
            )
        paths.extend([
            "/usr/local/bin/stata-se",
            "/usr/local/bin/stata-mp",
            "/usr/local/bin/stata-be",
            "/usr/local/bin/stata",
        ])
    elif plat == "win32":
        for edition in ("SE", "MP", "BE"):
            paths.append(f"C:\\Program Files\\StataNow\\Stata{edition}.exe")
        for edition in ("SE", "MP", "BE"):
            paths.append(f"C:\\Program Files\\Stata\\Stata{edition}.exe")
    else:
        # Linux and other Unix-like systems
        for edition in ("SE", "MP", "BE"):
            paths.append(f"/usr/local/stata/stata-{edition.lower()}")
        paths.append("/usr/local/stata/stata")
        for edition in ("SE", "MP", "BE"):
            paths.append(f"/usr/lib/stata/stata-{edition.lower()}")

    return paths


def find_stata_candidates() -> list[tuple[str, str]]:
    """Search common paths for Stata binaries.

    Checks every candidate path on disk and returns a list of
    ``(path, edition)`` tuples for those that exist.  The
    ``STATA_PATH`` environment variable is consulted first if set.

    Returns
    -------
    list of (path, edition)
        Each *edition* is one of ``"SE"``, ``"MP"``, or ``"BE"``.
    """
    seen: set[str] = set()
    results: list[tuple[str, str]] = []

    # Collect paths; STATA_PATH first if present
    candidate_paths: list[str] = []
    env_path = os.environ.get("STATA_PATH")
    if env_path:
        candidate_paths.append(env_path)
    candidate_paths.extend(_platform_candidates())

    for p in candidate_paths:
        if p in seen:
            continue
        seen.add(p)
        if Path(p).exists():
            edition = _parse_edition_from_binary(p)
            results.append((p, edition))

    return results


def verify_stata_install(path: str, edition: str, timeout: int = 120) -> bool:
    """Verify a Stata installation by running it in quiet mode.

    Launches the binary with ``-q``, pipes ``exit\\n`` to stdin, and
    checks the return code.

    Parameters
    ----------
    path : str
        Full path to the Stata executable.
    edition : str
        Edition label (SE, MP, or BE) — currently informational.
    timeout : int
        Seconds to wait before giving up (default 120).

    Returns
    -------
    bool
        ``True`` if the process exits with code 0.
    """
    try:
        result = subprocess.run(
            [path, "-q"],
            input=b"exit\n",
            capture_output=True,
            timeout=timeout,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False


def find_stata_path() -> tuple[str, str]:
    """Find a working Stata installation.

    Iterates candidates from :func:`find_stata_candidates` and returns
    the first that passes :func:`verify_stata_install`.  The result is
    cached for the lifetime of the process (or until :func:`clear_cache`
    is called).

    Returns
    -------
    (path, edition)
        The path and edition of the first working candidate.

    Raises
    ------
    FileNotFoundError
        If no candidate exists on disk or none pass verification.
    """
    if _CACHE_KEY in _CACHE:
        return _CACHE[_CACHE_KEY]

    candidates = find_stata_candidates()
    for path, edition in candidates:
        if verify_stata_install(path, edition):
            _CACHE[_CACHE_KEY] = (path, edition)
            return (path, edition)

    raise FileNotFoundError(
        "No working Stata installation found. "
        "Set STATA_PATH or install Stata."
    )


def discover_stata() -> str:
    """Discover a working Stata executable path.

    Convenience wrapper around :func:`find_stata_path` that returns
    only the path component.  Shares the same process-global cache.

    Returns
    -------
    str
        Path to a working Stata binary.

    Raises
    ------
    FileNotFoundError
        If no working Stata installation is found.
    """
    path, _ = find_stata_path()
    return path


def clear_cache() -> None:
    """Clear the module-level discovery cache.

    The next call to :func:`find_stata_path` or :func:`discover_stata`
    will re-run discovery from scratch.
    """
    _CACHE.pop(_CACHE_KEY, None)

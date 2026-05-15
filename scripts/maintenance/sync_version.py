#!/usr/bin/env python3
"""Sync the package version across version locations in the repository.

Reads the canonical version from ``pyproject.toml`` (``project.version``)
and writes it into the Python ``__version__`` variable in
``src/stata_agent/__init__.py``.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PYPROJECT_TOML = ROOT / "pyproject.toml"
INIT_PY = ROOT / "src" / "stata_agent" / "__init__.py"

_VERSION_TOML_RE = re.compile(
    r'^version\s*=\s*"(.+?)"\s*$', re.MULTILINE
)
_VERSION_PY_RE = re.compile(
    r'^__version__\s*=\s*"(.+?)"\s*$', re.MULTILINE
)


def get_version() -> str:
    """Return the canonical version from pyproject.toml."""
    text = PYPROJECT_TOML.read_text(encoding="utf-8")
    m = _VERSION_TOML_RE.search(text)
    if not m:
        sys.stderr.write(
            f"ERROR: could not find 'version = ...' in {PYPROJECT_TOML}\n"
        )
        sys.exit(1)
    return m.group(1)


def sync_init_py(version: str) -> bool:
    """Update __version__ in __init__.py if it differs."""
    text = INIT_PY.read_text(encoding="utf-8")
    m = _VERSION_PY_RE.search(text)
    if not m:
        sys.stderr.write(f"ERROR: could not find __version__ in {INIT_PY}\n")
        sys.exit(1)
    if m.group(1) == version:
        return False
    text = _VERSION_PY_RE.sub(f'__version__ = "{version}"', text)
    INIT_PY.write_text(text, encoding="utf-8")
    return True


def main() -> None:
    version = get_version()
    changed = sync_init_py(version)
    rel = lambda p: str(p.relative_to(ROOT))
    if changed:
        print(f"  updated  {rel(INIT_PY)}")
    else:
        print(f"  ok       {rel(INIT_PY)}")
    print(f"\nversion: {version}  ({'updated' if changed else 'unchanged'})")


if __name__ == "__main__":
    main()

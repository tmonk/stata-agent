"""Log lifecycle management: rotation, truncation, tail, search.

Manages text logs for Stata sessions with rotation, efficient tail/search,
and structured error extraction access.
"""

from __future__ import annotations

import os
import re
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

LOG_DIR_DEFAULT = Path.home() / ".cache" / "stata-agent" / "logs"


class LogRotator:
    """Per-session log rotation manager.

    Rotates when command count exceeds max_commands or file exceeds max_bytes.
    """

    def __init__(
        self,
        session_name: str,
        log_dir: Path = LOG_DIR_DEFAULT,
        max_commands_per_log: int = 100,
        max_log_bytes: int = 50_000_000,
        ttl_hours: int = 24,
    ):
        self.session_name = session_name
        self.log_dir = log_dir
        self.max_commands = max_commands_per_log
        self.max_bytes = max_log_bytes
        self.ttl = timedelta(hours=ttl_hours)
        self.command_count = 0
        self._sequence = 0
        self.current_path = self._new_path()

    def _new_path(self) -> Path:
        self._sequence += 1
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.log_dir.mkdir(parents=True, exist_ok=True)
        return self.log_dir / f"{self.session_name}_{ts}_{self._sequence:03d}.log"

    def rotate_if_needed(self) -> bool:
        """Check rotation triggers and rotate if necessary.

        Returns True if rotation occurred.
        """
        self.command_count += 1
        size = self.current_path.stat().st_size if self.current_path.exists() else 0
        if self.command_count > self.max_commands or size > self.max_bytes:
            self.current_path = self._new_path()
            self.command_count = 0
            return True
        return False

    def get_current_path(self) -> Path:
        return self.current_path

    def next_path(self) -> Path:
        """Return the path that would be used on the next rotation, without rotating."""
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        next_seq = self._sequence + 1
        return self.log_dir / f"{self.session_name}_{ts}_{next_seq:03d}.log"

    def cleanup_old(self) -> int:
        """Remove log files older than TTL.

        Returns number of files removed.
        """
        cutoff = datetime.now() - self.ttl
        removed = 0
        if not self.log_dir.exists():
            return 0
        for f in self.log_dir.iterdir():
            if f.name.startswith(self.session_name) and f.suffix == ".log":
                try:
                    mtime = datetime.fromtimestamp(f.stat().st_mtime)
                    if mtime <= cutoff:
                        f.unlink()
                        removed += 1
                except OSError:
                    pass
        return removed


# ---------------------------------------------------------------------------
# Truncation
# ---------------------------------------------------------------------------

MAX_OUTPUT_TOKENS = 1000
MAX_OUTPUT_CHARS = MAX_OUTPUT_TOKENS * 4


def truncate_for_agent(text: str, max_chars: int = MAX_OUTPUT_CHARS) -> tuple[str, bool]:
    """Truncate text to approximately max_chars, preferring tail.

    Returns (truncated_text, was_truncated).
    """
    if not text:
        return text, False
    if len(text) <= max_chars:
        return text, False

    tail = text[-max_chars:]
    first_nl = tail.find("\n")
    if first_nl != -1:
        tail = tail[first_nl + 1 :]

    notice = f"[Output truncated. Showing last ~{max_chars // 4} tokens.]\n"
    return notice + tail, True


def truncate_for_error(text: str, max_chars: int = 256) -> str:
    """Truncate error context to approximately max_chars, preferring head."""
    if not text or len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n...[truncated]"


# ---------------------------------------------------------------------------
# Tail, Search, Read
# ---------------------------------------------------------------------------


def tail_file(log_path: str | Path, lines: int = 50) -> str:
    """Read the last N lines of a file efficiently."""
    path = Path(log_path)
    if not path.exists():
        return ""

    with open(path, "rb") as f:
        try:
            f.seek(0, os.SEEK_END)
            file_size = f.tell()
        except OSError:
            return ""

        if file_size == 0:
            return ""

        # Estimate position: lines * avg_line_length
        avg_line = 80
        pos = max(0, file_size - lines * avg_line * 2)
        f.seek(pos)

        data = f.read()
        text = data.decode("utf-8", errors="replace")

        # If we didn't get enough lines, read more (iterative, not recursive)
        split = text.splitlines()
        if len(split) < lines and pos > 0:
            # Read double-sized chunk from earlier position
            pos = max(0, pos - lines * avg_line * 4)
            f.seek(pos)
            data = f.read()
            text = data.decode("utf-8", errors="replace")
            split = text.splitlines()

        return "\n".join(split[-lines:])


def search_in_log(
    log_path: str | Path,
    pattern: str,
    offset: int = 0,
    max_bytes: int = 262144,
) -> dict:
    """Search for pattern in log file with pagination.

    Returns {"matches": [...], "next_offset": int | None, "total_size": int}.
    """
    path = Path(log_path)
    if not path.exists():
        return {"matches": [], "next_offset": None, "total_size": 0}

    file_size = path.stat().st_size
    if offset >= file_size:
        return {"matches": [], "next_offset": None, "total_size": file_size}

    # Fast path: if pattern contains no regex metacharacters, use simple substring search
    compiled = re.compile(pattern)
    is_simple = not any(c in pattern for c in r"\.*+?^$()[]{}| ")

    matches = []
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        f.seek(offset)
        remaining = max_bytes
        while remaining > 0:
            chunk_size = min(remaining, 65536)  # 64 KB chunks
            data = f.read(chunk_size)
            if not data:
                break
            remaining -= len(data.encode("utf-8"))

            for line in data.splitlines():
                if is_simple:
                    if pattern in line:
                        matches.append(line)
                else:
                    if compiled.search(line):
                        matches.append(line)

    # Calculate actual bytes consumed
    with open(path, "rb") as f:
        f.seek(offset)
        raw = f.read(max_bytes)
    next_offset = offset + len(raw)
    if next_offset >= file_size:
        next_offset = None

    return {
        "matches": matches,
        "next_offset": next_offset,
        "total_size": file_size,
    }


def paginated_read(
    log_path: str | Path,
    offset: int = 0,
    max_bytes: int = 65536,
) -> dict:
    """Read a chunk of the log with pagination metadata.

    Returns {"data": str, "offset": int, "next_offset": int | None, "total_size": int}.
    """
    path = Path(log_path)
    if not path.exists():
        return {"data": "", "offset": offset, "next_offset": None, "total_size": 0}

    file_size = path.stat().st_size
    if offset >= file_size:
        return {"data": "", "offset": offset, "next_offset": None, "total_size": file_size}

    with open(path, "r", encoding="utf-8", errors="replace") as f:
        f.seek(offset)
        data = f.read(max_bytes)

    next_offset = offset + len(data.encode("utf-8"))
    if next_offset >= file_size:
        next_offset = None

    return {
        "data": data,
        "offset": offset,
        "next_offset": next_offset,
        "total_size": file_size,
    }

"""Unit tests for log_manager."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from stata_agent.log_manager import (
    LogRotator,
    truncate_for_agent,
    tail_file,
    search_in_log,
    paginated_read,
)


class TestTruncation:
    def test_short_text_not_truncated(self):
        text = "hello world"
        result, truncated = truncate_for_agent(text, max_chars=100)
        assert truncated is False
        assert result == text

    def test_long_text_truncated(self):
        text = "a" * 500 + "\n" + "b" * 500
        result, truncated = truncate_for_agent(text, max_chars=200)
        assert truncated is True
        assert "Output truncated" in result
        assert result.endswith("b" * 200 + "]") is False  # no, truncated differently
        # Should contain tail
        assert "b" in result

    def test_empty_text(self):
        result, truncated = truncate_for_agent("")
        assert truncated is False
        assert result == ""


class TestTailFile:
    def test_tail_empty_file(self, tmp_path):
        p = tmp_path / "empty.log"
        p.write_text("")
        assert tail_file(p, lines=10) == ""

    def test_tail_nonexistent_file(self):
        assert tail_file("/nonexistent/foo.log") == ""

    def test_tail_fewer_lines_than_requested(self, tmp_path):
        p = tmp_path / "short.log"
        p.write_text("line1\nline2\nline3\n")
        result = tail_file(p, lines=10)
        assert result.count("line") == 3

    def test_tail_more_lines_than_file(self, tmp_path):
        lines = [f"line{i}" for i in range(100)]
        p = tmp_path / "long.log"
        p.write_text("\n".join(lines) + "\n")
        result = tail_file(p, lines=10)
        assert len(result.splitlines()) == 10
        assert result.splitlines()[0] == "line90"


class TestSearchInLog:
    def test_search_found(self, tmp_path):
        lines = [
            "normal line",
            "error: something broke",
            "another normal",
            "r(111);",
        ]
        p = tmp_path / "search.log"
        p.write_text("\n".join(lines) + "\n")

        result = search_in_log(p, "r\(111\)")
        assert len(result["matches"]) == 1
        assert "r(111)" in result["matches"][0]

    def test_search_not_found(self, tmp_path):
        p = tmp_path / "nope.log"
        p.write_text("all good\n")
        result = search_in_log(p, "error")
        assert len(result["matches"]) == 0
        assert result["total_size"] > 0

    def test_search_nonexistent(self):
        result = search_in_log("/nonexistent.log", "pattern")
        assert result["matches"] == []


class TestPaginatedRead:
    def test_basic_read(self, tmp_path):
        content = "abcdefghijklmnopqrstuvwxyz" * 100
        p = tmp_path / "page.log"
        p.write_text(content)

        result = paginated_read(p, offset=0, max_bytes=50)
        assert len(result["data"]) == 50
        assert result["next_offset"] is not None
        assert result["total_size"] == len(content)

    def test_read_beyond_eof(self, tmp_path):
        p = tmp_path / "small.log"
        p.write_text("hi")
        result = paginated_read(p, offset=100, max_bytes=50)
        assert result["data"] == ""

    def test_nonexistent_file(self):
        result = paginated_read("/nonexistent.log")
        assert result["data"] == ""


class TestLogRotator:
    def test_initial_path_created(self, tmp_path):
        rot = LogRotator("test", log_dir=tmp_path)
        assert rot.current_path is not None
        assert rot.current_path.suffix == ".log"
        assert rot.session_name == "test"

    def test_rotation_by_command_count(self, tmp_path):
        rot = LogRotator("test", log_dir=tmp_path, max_commands_per_log=3)
        first = rot.current_path

        rot.rotate_if_needed()  # command 1
        rot.rotate_if_needed()  # command 2
        rot.rotate_if_needed()  # command 3 — still under limit
        assert rot.current_path == first  # no rotation yet

        rot.rotate_if_needed()  # command 4 — should rotate
        assert rot.current_path != first

    def test_rotation_by_bytes(self, tmp_path):
        rot = LogRotator("test", log_dir=tmp_path, max_log_bytes=10)
        # Touch the current log with content
        rot.current_path.write_text("x" * 20)
        first = rot.current_path

        rot.command_count = 0
        rot.max_commands = 100
        rot.rotate_if_needed()

        # Should have rotated due to size
        assert rot.current_path != first

    def test_cleanup_old(self, tmp_path):
        rot = LogRotator("test", log_dir=tmp_path, ttl_hours=0)  # 0 TTL = delete everything
        # Create some old-looking log files
        (tmp_path / "test_old.log").write_text("old")
        (tmp_path / "other.log").write_text("other")
        removed = rot.cleanup_old()
        assert removed >= 1  # at least test_old.log removed

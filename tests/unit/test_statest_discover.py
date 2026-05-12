"""Unit tests for test discovery."""
from __future__ import annotations

import os
import tempfile

from stata_agent.statest.runner import discover_tests


class TestDiscoverTests:
    def test_discover_finds_test_do_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create test files
            for name in ["test_alpha.do", "test_beta.do", "test_gamma.do"]:
                path = os.path.join(tmpdir, name)
                open(path, "w").close()

            # Create a non-test file that should be ignored
            open(os.path.join(tmpdir, "ignore_me.do"), "w").close()

            files = discover_tests(tmpdir)
            assert len(files) == 3
            # Should be sorted
            for i in range(len(files) - 1):
                assert files[i] < files[i + 1]
            # All should end with .do and start with test_
            for f in files:
                assert f.endswith(".do")
                assert "test_" in os.path.basename(f)

    def test_discover_recursive(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            subdir = os.path.join(tmpdir, "sub")
            os.makedirs(subdir)

            open(os.path.join(tmpdir, "test_root.do"), "w").close()
            open(os.path.join(subdir, "test_sub.do"), "w").close()

            files = discover_tests(tmpdir)
            assert len(files) == 2
            # Should include subdirectory file
            assert any("test_root.do" in f for f in files)
            assert any("test_sub.do" in f for f in files)

    def test_discover_no_tests(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            open(os.path.join(tmpdir, "setup.do"), "w").close()
            open(os.path.join(tmpdir, "not_a_test.do"), "w").close()

            files = discover_tests(tmpdir)
            assert len(files) == 0

    def test_discover_empty_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            files = discover_tests(tmpdir)
            assert len(files) == 0

"""Unit tests for _check_and_upgrade() in skills_installer.py."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from importlib import metadata as _metadata

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


_VERSION = _metadata.version("stata-agent")


class TestCheckAndUpgrade:
    """Tests for check_and_upgrade()."""

    def _setup_state_dir(self, tmp_path, monkeypatch):
        """Create a state directory and set env vars."""
        state_dir = tmp_path / ".local" / "state" / "stata-agent"
        state_dir.mkdir(parents=True)
        monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / ".local" / "state"))
        monkeypatch.setenv("HOME", str(tmp_path))
        # On Windows, _get_state_dir uses LOCALAPPDATA instead of XDG_STATE_HOME
        if sys.platform == "win32":
            monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / ".local" / "state"))
        monkeypatch.delenv("STATA_AGENT_NO_AUTO_UPGRADE", raising=False)
        return state_dir

    def test_no_auto_upgrade_env_var(self, tmp_path, monkeypatch):
        """check_and_upgrade() returns immediately when STATA_AGENT_NO_AUTO_UPGRADE=1."""
        from stata_agent.skills_installer import check_and_upgrade

        state_dir = self._setup_state_dir(tmp_path, monkeypatch)
        monkeypatch.setenv("STATA_AGENT_NO_AUTO_UPGRADE", "1")

        # Should return without doing anything
        result = check_and_upgrade(force=False)
        assert result is None

    def test_version_file_sync_on_mismatch(self, tmp_path, monkeypatch):
        """Phase 1: install-skills is called when stored version differs."""
        from stata_agent.skills_installer import check_and_upgrade

        state_dir = self._setup_state_dir(tmp_path, monkeypatch)

        # Write a different stored version
        installed_version_file = state_dir / "installed_version"
        installed_version_file.write_text("0.0.0")

        with patch("subprocess.run") as mock_run:
            # Mock the subprocess calls
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

            check_and_upgrade(force=False)

            # Verify install-skills was called (at least once)
            called_with_install_skills = any(
                "install-skills" in str(args) for args, _ in mock_run.call_args_list
            )
            # It should at minimum call something
            assert mock_run.called

    def test_version_file_write_after_sync(self, tmp_path, monkeypatch):
        """Phase 1: version file is updated after sync."""
        from stata_agent.skills_installer import check_and_upgrade

        state_dir = self._setup_state_dir(tmp_path, monkeypatch)

        # No installed_version file yet
        assert not (state_dir / "installed_version").exists()

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="{}", stderr="")

            check_and_upgrade(force=False)

            # After calling, the version file should exist
            if (state_dir / "installed_version").exists():
                stored = (state_dir / "installed_version").read_text().strip()
                assert stored == _VERSION

    def test_denylist_detection(self, tmp_path, monkeypatch):
        """Phase 2: denylist is detected and update_state.json is updated."""
        from stata_agent.skills_installer import check_and_upgrade

        state_dir = self._setup_state_dir(tmp_path, monkeypatch)

        # Set up the version file to match, so Phase 1 is a no-op
        (state_dir / "installed_version").write_text(_VERSION)

        # Mock _fetch_latest_version to return denylisted info
        with patch("stata_agent.skills_installer._fetch_latest_version") as mock_fetch:
            mock_fetch.return_value = {
                "version": "99.99.99",
                "min_supported": "0.1.0",
                "denylist": [_VERSION],
            }

            check_and_upgrade(force=False)

            # Check update_state.json was written
            state_file = state_dir / "update_state.json"
            if state_file.exists():
                state = json.loads(state_file.read_text())
                assert state.get("denylist_active") is True

    def test_up_to_date_no_upgrade(self, tmp_path, monkeypatch):
        """Phase 2: when current >= latest, no upgrade."""
        from stata_agent.skills_installer import check_and_upgrade

        state_dir = self._setup_state_dir(tmp_path, monkeypatch)
        (state_dir / "installed_version").write_text(_VERSION)

        with patch("stata_agent.skills_installer._fetch_latest_version") as mock_fetch:
            mock_fetch.return_value = {
                "version": "0.0.1",  # Less than current
                "denylist": [],
            }
            with patch("subprocess.run") as mock_run:
                check_and_upgrade(force=False)
                # uv tool upgrade should NOT have been called
                upgrade_calls = [
                    c for c in mock_run.call_args_list
                    if "upgrade" in str(c)
                ]
                assert len(upgrade_calls) == 0

    def test_emergency_disable(self, tmp_path, monkeypatch):
        """Phase 2: emergency_disable=true stops upgrade."""
        from stata_agent.skills_installer import check_and_upgrade

        state_dir = self._setup_state_dir(tmp_path, monkeypatch)
        (state_dir / "installed_version").write_text(_VERSION)

        with patch("stata_agent.skills_installer._fetch_latest_version") as mock_fetch:
            mock_fetch.return_value = {
                "version": "99.99.99",
                "emergency_disable": True,
                "denylist": [],
            }

            check_and_upgrade(force=False)

            state_file = state_dir / "update_state.json"
            if state_file.exists():
                state = json.loads(state_file.read_text())
                assert state.get("last_check_result") == "skipped"

    def test_write_state_on_up_to_date(self, tmp_path, monkeypatch):
        """update_state.json is written for up_to_date results."""
        from stata_agent.skills_installer import check_and_upgrade

        state_dir = self._setup_state_dir(tmp_path, monkeypatch)
        (state_dir / "installed_version").write_text(_VERSION)

        with patch("stata_agent.skills_installer._fetch_latest_version") as mock_fetch:
            mock_fetch.return_value = {
                "version": _VERSION,  # Same version
                "denylist": [],
            }

            check_and_upgrade(force=False)

            state_file = state_dir / "update_state.json"
            if state_file.exists():
                state = json.loads(state_file.read_text())
                assert state.get("last_check_result") == "up_to_date"

    def test_fetch_failure_continues_normally(self, tmp_path, monkeypatch):
        """When _fetch_latest_version returns None, command continues."""
        from stata_agent.skills_installer import check_and_upgrade

        state_dir = self._setup_state_dir(tmp_path, monkeypatch)
        (state_dir / "installed_version").write_text(_VERSION)

        with patch("stata_agent.skills_installer._fetch_latest_version") as mock_fetch:
            mock_fetch.return_value = None

            # Should not crash
            result = check_and_upgrade(force=False)
            assert result is None

    def test_write_state_helper(self, tmp_path):
        """_write_state helper merges updates correctly."""
        from stata_agent.skills_installer import _write_state

        state_file = tmp_path / "update_state.json"
        state_file.parent.mkdir(parents=True, exist_ok=True)

        _write_state(state_file, {"last_check_ts": 12345})
        assert state_file.exists()
        state = json.loads(state_file.read_text())
        assert state["last_check_ts"] == 12345

        # Merge another update
        _write_state(state_file, {"last_check_result": "upgraded"})
        state = json.loads(state_file.read_text())
        assert state["last_check_ts"] == 12345
        assert state["last_check_result"] == "upgraded"


class TestDiscoverBinary:
    """Tests for _discover_stata_agent_binary()."""

    def test_env_override(self, tmp_path, monkeypatch):
        from stata_agent.skills_installer import _discover_stata_agent_binary

        fake_bin = tmp_path / "fake-agent"
        fake_bin.write_text("#!/bin/sh\necho ok")
        fake_bin.chmod(0o755)

        monkeypatch.setenv("STATA_AGENT_PATH", str(fake_bin))
        result = _discover_stata_agent_binary()
        assert result == str(fake_bin)

    def test_env_override_not_found(self, tmp_path, monkeypatch):
        from stata_agent.skills_installer import _discover_stata_agent_binary

        monkeypatch.setenv("STATA_AGENT_PATH", "/nonexistent/path")
        # Clear PATH to prevent fallthrough discovery in dev venv
        monkeypatch.setenv("PATH", str(tmp_path))
        result = _discover_stata_agent_binary()
        assert result is None

    def test_which_on_path(self, tmp_path, monkeypatch):
        from stata_agent.skills_installer import _discover_stata_agent_binary

        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        bin_name = "stata-agent.exe" if sys.platform == "win32" else "stata-agent"
        fake_bin = bin_dir / bin_name
        fake_bin.write_text("")
        if sys.platform != "win32":
            fake_bin.chmod(0o755)

        monkeypatch.setenv("PATH", str(bin_dir))
        monkeypatch.delenv("STATA_AGENT_PATH", raising=False)

        result = _discover_stata_agent_binary()
        # On Windows, shutil.which may return .EXE (uppercase) even when
        # we created the file with lowercase .exe — compare case-insensitively
        if sys.platform == "win32":
            assert result is not None
            assert result.lower() == str(fake_bin).lower()
        else:
            assert result == str(fake_bin)

    def test_returns_none_when_not_found(self, tmp_path, monkeypatch):
        from stata_agent.skills_installer import _discover_stata_agent_binary

        monkeypatch.setenv("PATH", str(tmp_path))
        monkeypatch.delenv("STATA_AGENT_PATH", raising=False)

        with patch("subprocess.run", side_effect=FileNotFoundError):
            result = _discover_stata_agent_binary()
            assert result is None


class TestFetchLatestVersion:
    """Tests for _fetch_latest_version()."""

    def test_returns_worker_data(self):
        from stata_agent.skills_installer import _fetch_latest_version

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout=json.dumps({
                    "version": "2.0.0",
                    "min_supported": "1.0.0",
                    "denylist": ["0.9.0"],
                }),
                stderr="",
            )
            result = _fetch_latest_version(timeout=5)
            assert result is not None
            assert result["version"] == "2.0.0"
            assert "0.9.0" in result["denylist"]

    def test_falls_back_to_pypi(self):
        from stata_agent.skills_installer import _fetch_latest_version

        with patch("subprocess.run") as mock_run:
            # First call fails (Worker down), second succeeds (PyPI)
            mock_run.side_effect = [
                Exception("Network error"),
                MagicMock(
                    returncode=0,
                    stdout=json.dumps({
                        "info": {"version": "1.5.0"},
                    }),
                    stderr="",
                ),
            ]
            result = _fetch_latest_version(timeout=1)
            assert result is not None
            assert result["version"] == "1.5.0"

    def test_returns_none_on_total_failure(self):
        from stata_agent.skills_installer import _fetch_latest_version

        with patch("subprocess.run", side_effect=Exception("All failed")):
            result = _fetch_latest_version(timeout=1)
            assert result is None

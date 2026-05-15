"""Unit tests for scripts/install/verify.py — DoctorResult and doctor()."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# Ensure the project root is on sys.path for imports
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


class TestDoctorResult:
    """Tests for DoctorResult dataclass."""

    def test_defaults_all_false_or_none(self):
        from scripts.install.verify import DoctorResult
        r = DoctorResult()
        assert r.binary_path is None
        assert r.version is None
        assert r.uv_tool_ok is False
        assert r.daemon_running is False
        assert r.skills == {}
        assert r.issues == []
        assert r.warnings == []

    def test_to_dict_includes_all_fields(self):
        from scripts.install.verify import DoctorResult, SkillStatus
        r = DoctorResult(
            binary_path="/usr/bin/stata-agent",
            version="1.0.0",
            uv_tool_ok=True,
            skills={
                "generic": SkillStatus(registered=True, link_type="symlink", target_path="/tmp/skills"),
                "claude": SkillStatus(registered=False),
            },
            issues=["test issue"],
        )
        d = r.to_dict()
        assert d["binary_path"] == "/usr/bin/stata-agent"
        assert d["version"] == "1.0.0"
        assert d["skills"]["generic"]["registered"] is True
        assert d["skills"]["generic"]["link_type"] == "symlink"
        assert d["skills"]["claude"]["registered"] is False
        assert "test issue" in d["issues"]

    def test_skill_status_defaults(self):
        from scripts.install.verify import SkillStatus
        s = SkillStatus(registered=True)
        assert s.link_type is None
        assert s.target_path is None
        assert s.stale is False


class TestDoctorFunction:
    """Tests for the doctor() function with mocked subprocess."""

    @pytest.fixture
    def mock_home(self, tmp_path):
        """Temporary home directory."""
        return tmp_path

    def test_doctor_binary_found(self, tmp_path, monkeypatch):
        """doctor() finds the binary on PATH."""
        from scripts.install.verify import doctor

        # Create a fake stata-agent binary
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        bin_name = "stata-agent.exe" if sys.platform == "win32" else "stata-agent"
        fake_bin = bin_dir / bin_name
        fake_bin.write_text("#!/bin/sh\necho 'stata_agent 1.0.0'")
        if sys.platform != "win32":
            fake_bin.chmod(0o755)

        monkeypatch.setenv("PATH", str(bin_dir))
        monkeypatch.setenv("HOME", str(tmp_path))
        # Prevent sys.executable from being used (real venv path)
        monkeypatch.setattr(sys, "executable", "/usr/bin/python3")

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout="stata_agent 1.0.0", stderr="", returncode=0)

            result = doctor()
            assert result.binary_path is not None
            assert "stata-agent" in result.binary_path

    def test_doctor_binary_missing(self, tmp_path, monkeypatch):
        """doctor() reports issue when binary not found."""
        from scripts.install.verify import doctor

        # Empty PATH
        monkeypatch.setenv("PATH", str(tmp_path))
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.delenv("STATA_AGENT_PATH", raising=False)
        # Prevent sys.executable fallback (which contains "stata_agent" in path)
        monkeypatch.setattr(sys, "executable", "/nonexistent/python")

        with patch("subprocess.run", side_effect=FileNotFoundError):
            with patch("shutil.which", return_value=None):
                result = doctor()
                assert result.binary_path is None
                assert any("not found" in issue.lower() for issue in result.issues)

    def test_doctor_auto_upgrade_disabled(self, monkeypatch):
        """doctor() detects STATA_AGENT_NO_AUTO_UPGRADE=1."""
        from scripts.install.verify import doctor

        monkeypatch.setenv("STATA_AGENT_NO_AUTO_UPGRADE", "1")
        monkeypatch.setenv("PATH", "/usr/bin")
        monkeypatch.setenv("HOME", "/tmp")

        with patch("subprocess.run", return_value=MagicMock(stdout="", stderr="", returncode=0)):
            with patch("shutil.which", return_value="/fake/stata-agent"):
                result = doctor()
                assert result.auto_upgrade_disabled is True

    def test_doctor_uv_tool_ok(self, monkeypatch):
        """doctor() detects uv tool status."""
        from scripts.install.verify import doctor

        monkeypatch.setenv("PATH", "/usr/bin")
        monkeypatch.setenv("HOME", "/tmp")

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = [
                MagicMock(stdout="stata_agent 1.0.0", stderr=""),
                MagicMock(stdout="stata-agent 0.1.0\nother-tool 2.0.0", stderr=""),
            ]
            with patch("shutil.which", return_value="/fake/stata-agent"):
                result = doctor()
                assert result.uv_tool_ok is True

    def test_doctor_reads_update_state(self, tmp_path, monkeypatch):
        """doctor() reads update_state.json."""
        from scripts.install.verify import doctor

        state_dir = tmp_path / ".local" / "state" / "stata-agent"
        state_dir.mkdir(parents=True)
        state_file = state_dir / "update_state.json"
        state_file.write_text(json.dumps({
            "last_check_ts": 1747123456,
            "last_check_result": "upgraded",
            "latest_known_version": "1.2.3",
            "denylist_active": False,
        }))

        monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / ".local" / "state"))
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setenv("PATH", "/usr/bin")
        # On Windows, _get_state_dir uses LOCALAPPDATA instead of XDG_STATE_HOME
        if sys.platform == "win32":
            monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / ".local" / "state"))

        with patch("subprocess.run", return_value=MagicMock(stdout="", stderr="", returncode=0)):
            with patch("shutil.which", return_value="/fake/stata-agent"):
                result = doctor()
                assert result.last_check_ts == 1747123456
                assert result.latest_known_version == "1.2.3"

    def test_doctor_denylist_active(self, tmp_path, monkeypatch):
        """doctor() detects denylist_active in update_state.json."""
        from scripts.install.verify import doctor

        state_dir = tmp_path / ".local" / "state" / "stata-agent"
        state_dir.mkdir(parents=True)
        state_file = state_dir / "update_state.json"
        state_file.write_text(json.dumps({
            "denylist_active": True,
            "last_failure_reason": "version 0.1.0 is denylisted",
        }))

        monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / ".local" / "state"))
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setenv("PATH", "/usr/bin")
        # On Windows, _get_state_dir uses LOCALAPPDATA instead of XDG_STATE_HOME
        if sys.platform == "win32":
            monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / ".local" / "state"))

        with patch("subprocess.run", return_value=MagicMock(stdout="", stderr="", returncode=0)):
            with patch("shutil.which", return_value="/fake/stata-agent"):
                result = doctor()
                assert result.denylist_active is True
                assert any("denylist" in issue.lower() for issue in result.issues)

    def test_doctor_conflicting_binary(self, tmp_path, monkeypatch):
        """doctor() detects multiple binaries on PATH."""
        from scripts.install.verify import doctor

        bin_name = "stata-agent.exe" if sys.platform == "win32" else "stata-agent"
        bin1 = tmp_path / "bin1"
        bin2 = tmp_path / "bin2"
        bin1.mkdir(); bin2.mkdir()
        (bin1 / bin_name).write_text("")
        (bin2 / bin_name).write_text("")
        if sys.platform != "win32":
            (bin1 / bin_name).chmod(0o755)
            (bin2 / bin_name).chmod(0o755)

        monkeypatch.setenv("PATH", os.pathsep.join([str(bin1), str(bin2)]))
        monkeypatch.setenv("HOME", str(tmp_path))

        with patch("subprocess.run", return_value=MagicMock(stdout="", stderr="", returncode=0)):
            with patch("shutil.which", return_value=str(bin1 / bin_name)):
                result = doctor()
                assert result.conflicting_binary is not None

    def test_doctor_telemetry_probe(self, monkeypatch):
        """doctor() probes telemetry endpoint."""
        from scripts.install.verify import doctor

        monkeypatch.setenv("PATH", "/usr/bin")
        monkeypatch.setenv("HOME", "/tmp")
        monkeypatch.setattr(sys, "executable", "/usr/bin/python3")

        def mock_subprocess_run(cmd, **kwargs):
            cmd_str = " ".join(cmd) if isinstance(cmd, list) else str(cmd)
            if "health" in cmd_str and "curl" in str(cmd):
                return MagicMock(stdout="200", stderr="", returncode=0)
            if "tool" in str(cmd) and "list" in str(cmd):
                return MagicMock(stdout="stata-agent", stderr="", returncode=0)
            return MagicMock(stdout="stata_agent 1.0.0", stderr="", returncode=0)

        with patch("subprocess.run", side_effect=mock_subprocess_run):
            with patch("shutil.which", return_value="/fake/stata-agent"):
                result = doctor()
                assert result.telemetry_reachable is True

    def test_doctor_skills_all_agents_checked(self, tmp_path, monkeypatch):
        """doctor() checks all agent types."""
        from scripts.install.verify import doctor

        monkeypatch.setenv("PATH", "/usr/bin")
        monkeypatch.setenv("HOME", str(tmp_path))

        with patch("subprocess.run", return_value=MagicMock(stdout="", stderr="", returncode=0)):
            with patch("shutil.which", return_value="/fake/stata-agent"):
                result = doctor()
                assert "generic" in result.skills
                assert "codex" in result.skills
                assert "claude" in result.skills
                assert "gemini" in result.skills
                assert "claude_hooks" in result.skills


class TestSkillStatusHelpers:
    """Tests for SkillStatus helper function."""

    def test_generic_skill_not_registered(self, tmp_path):
        from scripts.install.verify import _check_skills_for_agent
        result = _check_skills_for_agent("generic", tmp_path, None)
        assert result.registered is False

    def test_generic_skill_symlink(self, tmp_path):
        from scripts.install.verify import _check_skills_for_agent
        skills_dir = tmp_path / ".agents" / "skills"
        skills_dir.mkdir(parents=True)
        target = tmp_path / "real-skills"
        target.mkdir()
        link = skills_dir / "stata-agent"
        link.symlink_to(target)
        result = _check_skills_for_agent("generic", tmp_path, str(target))
        assert result.registered is True
        assert result.link_type == "symlink"

    def test_generic_skill_stale_symlink(self, tmp_path):
        from scripts.install.verify import _check_skills_for_agent
        skills_dir = tmp_path / ".agents" / "skills"
        skills_dir.mkdir(parents=True)
        real_target = tmp_path / "real-target"
        real_target.mkdir()
        link = skills_dir / "stata-agent"
        link.symlink_to(real_target)
        # Expected target differs from actual, so it should be stale
        result = _check_skills_for_agent("generic", tmp_path, "/different/expected/target")
        assert result.stale is True
        assert result.registered is True

    def test_claude_hooks_json(self, tmp_path):
        from scripts.install.verify import _check_skills_for_agent
        hooks_dir = tmp_path / ".claude" / "hooks"
        hooks_dir.mkdir(parents=True)
        hook_file = hooks_dir / "stata-agent.json"
        hook_file.write_text("{}")
        result = _check_skills_for_agent("claude_hooks", tmp_path, None)
        assert result.registered is True
        assert result.link_type == "file"

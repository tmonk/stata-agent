"""verify.py — single source of truth for installation health.

Implements doctor() → DoctorResult dataclass consumed by
`stata-agent doctor --json` and `stata-agent doctor` (human output).

This file is importable from tests and directly invoked by the CLI.
`scripts/install/setup_install.py` does NOT exist as a separate file.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Optional


@dataclass
class SkillStatus:
    """Per-agent skill registration status."""
    registered: bool
    link_type: Optional[str] = None  # "symlink" | "copy" | "claude_plugin" | None
    target_path: Optional[str] = None
    stale: bool = False


@dataclass
class DoctorResult:
    """Full installation health report."""

    # Binary
    binary_path: Optional[str] = None
    version: Optional[str] = None
    uv_tool_ok: bool = False

    # Stata itself
    stata_binary_path: Optional[str] = None
    stata_version: Optional[str] = None
    stata_edition: Optional[str] = None
    stata_licensed: Optional[bool] = None

    # Daemon
    daemon_socket_path: Optional[str] = None
    daemon_running: bool = False

    # Skills — per-agent status
    skills: dict[str, SkillStatus] = field(default_factory=dict)

    # Update state
    current_version: Optional[str] = None
    latest_known_version: Optional[str] = None
    last_check_ts: Optional[int] = None
    last_upgrade_ts: Optional[int] = None
    last_failure_reason: Optional[str] = None
    upgrade_lock_held: bool = False
    denylist_active: bool = False
    auto_upgrade_disabled: bool = False

    # Environment
    path_visible: bool = False
    conflicting_binary: Optional[str] = None

    # Telemetry
    telemetry_enabled: bool = True
    telemetry_reachable: Optional[bool] = None

    # Issues
    issues: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict with nested SkillStatus."""
        result: dict[str, Any] = {}
        for k, v in asdict(self).items():
            if k == "skills":
                result[k] = {name: asdict(s) for name, s in self.skills.items()}
            else:
                result[k] = v
        return result


def _get_state_dir() -> Path:
    """Get the stata-agent state directory."""
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        return base / "stata-agent" / "state"
    base = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state"))
    return base / "stata-agent"


def _get_cache_dir() -> Path:
    """Get the stata-agent cache directory."""
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        return base / "stata-agent" / "cache"
    return Path.home() / ".cache" / "stata-agent"


def _find_stata_agent_binary() -> Optional[str]:
    """Discover the stata-agent binary path."""
    # 1. Env override
    env_path = os.environ.get("STATA_AGENT_PATH")
    if env_path and Path(env_path).exists():
        return env_path

    # 2. Current executable
    exe = sys.executable
    if "stata-agent" in exe or "stata_agent" in exe:
        return exe

    # 3. On PATH
    which = shutil.which("stata-agent")
    if which:
        return which

    # 4. Discover uv tool bin directory
    try:
        result = subprocess.run(
            ["uv", "tool", "dir", "--bin"],
            capture_output=True, text=True, timeout=5,
        )
        bin_dir = result.stdout.strip()
        if bin_dir:
            candidate = Path(bin_dir) / "stata-agent"
            if candidate.exists():
                return str(candidate)
            if sys.platform == "win32":
                candidate_exe = Path(bin_dir) / "stata-agent.exe"
                if candidate_exe.exists():
                    return str(candidate_exe)
    except Exception:
        pass

    return None


def _read_update_state() -> dict[str, Any]:
    """Read update_state.json if it exists."""
    state_file = _get_state_dir() / "update_state.json"
    if not state_file.exists():
        return {}
    try:
        return json.loads(state_file.read_text())
    except Exception:
        return {}


def _check_skills_for_agent(
    agent: str,
    home: Path,
    expected_target: Optional[str],
) -> SkillStatus:
    """Check skill registration status for a specific agent."""
    if agent == "generic":
        link = home / ".agents" / "skills" / "stata-agent"
    elif agent == "codex":
        link = home / ".codex" / "skills" / "stata-agent"
    elif agent == "claude":
        link = home / ".claude" / "plugins" / "stata-agent"
    elif agent == "gemini":
        link = home / ".gemini" / "extensions" / "stata-agent"
    elif agent == "claude_hooks":
        hook_file = home / ".claude" / "hooks" / "stata-agent.json"
        return SkillStatus(
            registered=hook_file.exists(),
            link_type="file",
            target_path=str(hook_file) if hook_file.exists() else None,
        )
    else:
        return SkillStatus(registered=False)

    if not link.exists(follow_symlinks=False):
        return SkillStatus(registered=False)
    if link.is_symlink():
        if not link.exists():
            # Dangling symlink — stale
            return SkillStatus(
                registered=False,
                link_type="symlink",
                target_path=str(link),
                stale=True,
            )
        target = str(link.resolve())
        stale = expected_target is not None and expected_target != target
        return SkillStatus(
            registered=True,
            link_type="symlink",
            target_path=target,
            stale=stale,
        )
    return SkillStatus(
        registered=True,
        link_type="copy",
        target_path=str(link),
    )


def doctor(plugin_dir: Optional[str] = None) -> DoctorResult:
    """Run all health checks and return a DoctorResult.

    Args:
        plugin_dir: Path to the bundled plugin directory. If None,
                    resolves via importlib.resources if available.
    """
    from stata_agent import __version__

    result = DoctorResult()

    # --- Binary check ---
    binary = _find_stata_agent_binary()
    result.binary_path = binary
    result.current_version = __version__
    result.version = __version__
    result.auto_upgrade_disabled = bool(os.environ.get("STATA_AGENT_NO_AUTO_UPGRADE"))

    if not binary:
        result.issues.append("stata-agent binary not found on PATH")
    else:
        # Verify it's actually stata-agent, not Stata Corp
        try:
            version_out = subprocess.run(
                [binary, "--version"],
                capture_output=True, text=True, timeout=5,
            )
            if "stata_agent" not in version_out.stdout and "stata.agent" not in version_out.stderr:
                result.warnings.append(
                    f"Binary at {binary} may not be stata-agent (version output: {version_out.stdout.strip()})"
                )
        except Exception:
            result.warnings.append(f"Could not verify binary identity: {binary}")

    # --- PATH visibility ---
    result.path_visible = shutil.which("stata-agent") is not None

    # --- Conflicting binary ---
    which_results = []
    for p in os.environ.get("PATH", "").split(os.pathsep):
        candidate = Path(p) / ("stata-agent.exe" if sys.platform == "win32" else "stata-agent")
        if candidate.exists():
            which_results.append(str(candidate))
    if len(which_results) > 1:
        result.conflicting_binary = which_results[0]
        result.warnings.append(
            f"Multiple stata-agent binaries on PATH: {', '.join(which_results)}"
        )

    # --- uv tool ---
    try:
        tool_list = subprocess.run(
            ["uv", "tool", "list"],
            capture_output=True, text=True, timeout=10,
        )
        result.uv_tool_ok = "stata-agent" in tool_list.stdout
    except Exception:
        result.uv_tool_ok = False

    # --- Stata binary ---
    try:
        from stata_agent.discovery import find_stata_path
        path, edition = find_stata_path()
        result.stata_binary_path = path
        result.stata_edition = edition
        # Try to get version and license status
        try:
            vp = subprocess.run(
                [path, "-q", "-e", 'display "`c(stata_version)\'"'],
                capture_output=True, text=True, timeout=15,
                input="exit\n",
            )
            result.stata_version = vp.stdout.strip()
            result.stata_licensed = vp.returncode == 0
        except Exception:
            pass
    except Exception:
        pass  # Stata not available — not an error for the agent itself

    # --- Daemon ---
    cache_dir = _get_cache_dir()
    sessions_dir = cache_dir / "sessions"
    if sessions_dir.exists():
        sockets = list(sessions_dir.glob("*.sock"))
        if sockets:
            result.daemon_socket_path = str(sockets[0])
            # Try health check
            try:
                import socket
                sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                sock.settimeout(1)
                sock.connect(str(sockets[0]))
                sock.send(b'{"id":"health-1","method":"health","args":{}}\n')
                resp = sock.recv(1024)
                sock.close()
                if resp:
                    result.daemon_running = True
            except Exception:
                pass

    # --- Skills ---
    home = Path.home()
    if plugin_dir:
        expected = plugin_dir.rstrip("/")
    else:
        expected = None
    agents = ["generic", "codex", "claude", "gemini", "claude_hooks"]
    for agent in agents:
        result.skills[agent] = _check_skills_for_agent(agent, home, expected)

    # --- Update state ---
    state = _read_update_state()
    if state:
        result.last_check_ts = state.get("last_check_ts")
        result.last_upgrade_ts = state.get("last_upgrade_ts")
        result.last_failure_reason = state.get("last_failure_reason")
        result.latest_known_version = state.get("latest_known_version")
        result.denylist_active = state.get("denylist_active", False)
        result.upgrade_lock_held = state.get("upgrade_lock_held", False)

    # --- Telemetry ---
    result.telemetry_enabled = True  # Default; can be configured later
    try:
        probe = subprocess.run(
            ["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}",
             "https://stata-agent-install.tdmonk.com/health"],
            capture_output=True, text=True, timeout=5,
        )
        result.telemetry_reachable = probe.stdout.strip() == "200"
    except Exception:
        result.telemetry_reachable = False

    # --- Summary ---
    if not result.path_visible and result.binary_path:
        result.issues.append(
            "stata-agent is installed but not visible in this shell. "
            "Open a new terminal or add it to PATH."
        )

    if result.denylist_active:
        result.issues.append(
            f"Current version {__version__} is denylisted. Run 'stata-agent upgrade' to update."
        )

    return result

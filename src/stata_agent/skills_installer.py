"""skills_installer.py — install-skills and upgrade CLI subcommands.

Handles:
- Resolving the plugin directory via importlib.resources
- Rewriting {{VERSION}} in JSON manifests
- Creating symlinks (or copy fallback) for each detected AI agent
- Stale link detection and repair
- Uninstall (--uninstall, --purge)
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import time
from pathlib import Path
from typing import Optional

# Imported lazily to avoid circular imports



def get_plugin_dir() -> Path:
    """Resolve the bundled plugin directory via importlib.resources."""
    try:
        from importlib.resources import files
        plugin_dir = files("stata_agent") / "plugin"
        if plugin_dir.is_dir():
            return Path(str(plugin_dir))
    except Exception:
        pass

    # Fallback: try relative to this file (development mode)
    here = Path(__file__).resolve().parent
    plugin_dir = here / "plugin"
    if plugin_dir.is_dir():
        return plugin_dir

    # Last resort
    return here / "plugin"


def build_plugin_manifests(plugin_dir: Path, version: str) -> Path:
    """Rewrite {{VERSION}} in all JSON manifest files inside plugin_dir.

    Returns the path to a temp directory containing the rewritten files.
    The original plugin_dir is never mutated.
    """
    import tempfile

    tmp = Path(tempfile.mkdtemp(prefix="stata-agent-plugin-"))
    to_copy: list[tuple[Path, Path]] = []

    for json_file in plugin_dir.rglob("*.json"):
        rel = json_file.relative_to(plugin_dir)
        dest = tmp / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            content = json_file.read_text()
            if "{{VERSION}}" in content:
                content = content.replace("{{VERSION}}", version)
                dest.write_text(content)
                to_copy.append((json_file, dest))
            else:
                dest.write_text(content)
                to_copy.append((json_file, dest))
        except Exception:
            # Binary or unreadable — skip
            pass

    # Copy non-JSON files as-is
    for f in plugin_dir.rglob("*"):
        if f.suffix != ".json" and f.is_file():
            rel = f.relative_to(plugin_dir)
            dest = tmp / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            if not dest.exists():
                shutil.copy2(f, dest)

    return tmp


def _detect_agents() -> dict[str, bool]:
    """Detect which AI agents are installed on this machine.

    Returns a dict with keys: generic, codex, claude, gemini, claude_hooks
    and boolean values indicating whether each agent is available.
    """
    home = Path.home()
    agents: dict[str, bool] = {}

    # Generic (Cursor, Windsurf, Continue, Zed) — always supported
    agents["generic"] = True

    # Codex — check for ~/.codex directory
    agents["codex"] = (home / ".codex").is_dir()

    # Claude Code — check for claude CLI
    agents["claude"] = shutil.which("claude") is not None

    # Gemini — check for ~/.gemini directory
    agents["gemini"] = (home / ".gemini").is_dir()

    # Claude Code hooks — always attempt if ~/.claude exists
    agents["claude_hooks"] = (home / ".claude").is_dir()

    return agents


def _create_link_or_copy(
    source: Path,
    target: Path,
    force: bool = False,
) -> tuple[bool, str]:
    """Create a symlink from target → source. Falls back to copy if symlinks fail.

    Returns (success, link_type) where link_type is "symlink", "copy", or "skip".
    """
    # Already correct symlink?
    if target.is_symlink():
        resolved = target.resolve()
        if str(resolved) == str(source):
            return (True, "skip")
        # Stale — remove and re-link
        if force or not resolved.exists():
            target.unlink()
        else:
            return (True, "skip")

    # Already a correct copy? (approximate check)
    if target.is_dir() and not target.is_symlink():
        if force:
            shutil.rmtree(target)
        else:
            return (True, "skip")

    # Try symlink
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            target.unlink()
        target.symlink_to(source, target_is_directory=source.is_dir())
        return (True, "symlink")
    except OSError:
        pass  # Symlink denied — fall back to copy

    # Copy fallback
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            if target.is_dir():
                shutil.rmtree(target)
            else:
                target.unlink()
        if source.is_dir():
            shutil.copytree(source, target)
        else:
            shutil.copy2(source, target)
        return (True, "copy")
    except Exception as e:
        return (False, str(e))


def install_skills(
    plugin_dir: Optional[Path] = None,
    version: Optional[str] = None,
    agents_filter: Optional[list[str]] = None,
    dry_run: bool = False,
    repair: bool = False,
    verbose: bool = False,
) -> dict[str, list[str]]:
    """Install skills for all detected AI agents.

    Returns:
        dict mapping agent name to list of status messages, or empty list on success.
    """
    if plugin_dir is None:
        plugin_dir = get_plugin_dir()

    if version is None:
        try:
            from importlib.metadata import version as _v
            version = _v("stata-agent")
        except ImportError:
            version = "0.1.0"

    results: dict[str, list[str]] = {}
    home = Path.home()

    # Prepare versioned manifests
    if dry_run:
        final_dir = plugin_dir
    else:
        final_dir = build_plugin_manifests(plugin_dir, version)

    detected = _detect_agents()
    if agents_filter:
        detected = {k: v for k, v in detected.items() if k in agents_filter}

    # --- Generic / Cursor / Windsurf ---
    if detected.get("generic"):
        source = final_dir / "skills"
        target = home / ".agents" / "skills" / "stata-agent"
        ok, kind = _create_link_or_copy(source, target, force=repair)
        if dry_run:
            results["generic"] = [f"[dry-run] Would create {kind}: {target} -> {source}"]
        elif ok:
            if verbose:
                results.setdefault("generic", []).append(f"{kind}: {target} -> {source}")
        else:
            results.setdefault("generic", []).append(f"Failed: {kind}")

    # --- Codex ---
    if detected.get("codex"):
        source = final_dir / "skills"
        target = home / ".codex" / "skills" / "stata-agent"
        ok, kind = _create_link_or_copy(source, target, force=repair)
        if dry_run:
            results["codex"] = [f"[dry-run] Would create {kind}: {target} -> {source}"]
        elif ok:
            if verbose:
                results.setdefault("codex", []).append(f"{kind}: {target} -> {source}")
        else:
            results.setdefault("codex", []).append(f"Failed: {kind}")

    # --- Claude Code plugin ---
    if detected.get("claude"):
        try:
            src = final_dir / ".claude-plugin"
            cmd = ["claude", "plugin", "marketplace", "add", str(src)]
            if dry_run:
                results["claude"] = [f"[dry-run] Would run: {' '.join(cmd)}"]
            else:
                import subprocess
                subprocess.run(cmd, capture_output=not verbose, timeout=30)
                subprocess.run(
                    ["claude", "plugin", "install", "stata-agent"],
                    capture_output=not verbose, timeout=30,
                )
                if verbose:
                    results.setdefault("claude", []).append("claude plugin installed")
        except Exception as e:
            results.setdefault("claude", []).append(f"Failed: {e}")

    # --- Gemini ---
    if detected.get("gemini"):
        source = final_dir
        target = home / ".gemini" / "extensions" / "stata-agent"
        ok, kind = _create_link_or_copy(source, target, force=repair)
        if dry_run:
            results["gemini"] = [f"[dry-run] Would create {kind}: {target} -> {source}"]
        elif ok:
            if verbose:
                results.setdefault("gemini", []).append(f"{kind}: {target} -> {source}")
        else:
            results.setdefault("gemini", []).append(f"Failed: {kind}")

    # --- Claude Code hooks ---
    if detected.get("claude_hooks"):
        source = final_dir / "hooks" / "hooks.json"
        target = home / ".claude" / "hooks" / "stata-agent.json"
        if dry_run:
            results["claude_hooks"] = [f"[dry-run] Would write hooks to {target}"]
        else:
            ok, kind = _create_link_or_copy(source, target, force=repair)
            if ok:
                if verbose:
                    results.setdefault("claude_hooks", []).append(f"{kind}: {target}")
            else:
                results.setdefault("claude_hooks", []).append(f"Failed: {kind}")

    return results


def uninstall_skills(
    plugin_dir: Optional[Path] = None,
    purge: bool = False,
    dry_run: bool = False,
    verbose: bool = False,
) -> dict[str, list[str]]:
    """Remove skill links and copies for all agents.

    Args:
        purge: Also remove user state/config directories.
    """
    if plugin_dir is None:
        plugin_dir = get_plugin_dir()

    results: dict[str, list[str]] = {}
    home = Path.home()
    state_dir = _get_state_dir()

    # Map of agent → target paths to clean up
    cleanup_targets = [
        ("generic", home / ".agents" / "skills" / "stata-agent"),
        ("codex", home / ".codex" / "skills" / "stata-agent"),
        ("gemini", home / ".gemini" / "extensions" / "stata-agent"),
        ("claude_hooks", home / ".claude" / "hooks" / "stata-agent.json"),
    ]

    for agent, target in cleanup_targets:
        if target.exists() or target.is_symlink():
            if dry_run:
                results[agent] = [f"[dry-run] Would remove {target}"]
            else:
                try:
                    if target.is_symlink():
                        target.unlink()
                    elif target.is_dir():
                        # Only remove if it points to a stata-agent path
                        shutil.rmtree(target)
                    elif target.is_file():
                        target.unlink()
                    if verbose:
                        results.setdefault(agent, []).append(f"Removed {target}")
                except Exception as e:
                    results.setdefault(agent, []).append(f"Failed to remove {target}: {e}")

    if purge and not dry_run:
        # Remove state directory
        try:
            if state_dir.exists():
                shutil.rmtree(state_dir)
                if verbose:
                    results.setdefault("purge", []).append(f"Removed {state_dir}")
        except Exception as e:
            results.setdefault("purge", []).append(f"Failed to purge {state_dir}: {e}")

    return results


def _get_state_dir() -> Path:
    """Get the stata-agent state directory."""
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        return base / "stata-agent" / "state"
    base = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state"))
    return base / "stata-agent"


def _discover_stata_agent_binary() -> Optional[str]:
    """Discover the stata-agent binary path."""
    env_path = os.environ.get("STATA_AGENT_PATH")
    if env_path and Path(env_path).exists():
        return env_path

    which = shutil.which("stata-agent")
    if which:
        return which

    try:
        import subprocess
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


def _parse_version(v: str) -> tuple[int, ...]:
    """Parse a version string into a comparable tuple."""
    try:
        return tuple(int(x) for x in v.strip().split(".")[:3])
    except Exception:
        return (0, 0, 0)


def _fetch_latest_version(timeout: Optional[float] = 1.0) -> Optional[dict]:
    """Fetch latest version info from Worker /latest.json, falling back to PyPI."""
    import subprocess
    import json

    # Try Worker first
    try:
        result = subprocess.run(
            ["curl", "-s", "--max-time", str(int(timeout or 5)),
             "https://stata-agent-install.tdmonk.com/latest.json"],
            capture_output=True, text=True, timeout=(timeout or 5) + 1,
        )
        if result.returncode == 0 and result.stdout.strip():
            return json.loads(result.stdout)
    except Exception:
        pass

    # Fall back to PyPI JSON API
    try:
        result = subprocess.run(
            ["curl", "-s", "--max-time", "10",
             "https://pypi.org/pypi/stata-agent/json"],
            capture_output=True, text=True, timeout=12,
        )
        if result.returncode == 0 and result.stdout.strip():
            data = json.loads(result.stdout)
            latest = data.get("info", {}).get("version")
            if latest:
                return {"version": latest, "min_supported": "0.1.0", "denylist": []}
    except Exception:
        pass

    return None


def _write_state(state_file: Path, updates: dict) -> None:
    """Merge updates into the update_state.json file."""
    try:
        existing = {}
        if state_file.exists():
            existing = json.loads(state_file.read_text())
        existing.update(updates)
        state_file.parent.mkdir(parents=True, exist_ok=True)
        state_file.write_text(json.dumps(existing, indent=2))
    except Exception:
        pass


def check_and_upgrade(force: bool = False) -> None:
    """Two-phase update check. Called on every invocation except upgrade/install-skills."""
    if os.environ.get("STATA_AGENT_NO_AUTO_UPGRADE"):
        return

    try:
        from importlib.metadata import version as _meta_version
    except ImportError:
        return

    _current_version = _meta_version("stata-agent")

    state_dir = _get_state_dir()
    state_dir.mkdir(parents=True, exist_ok=True)
    installed_version_file = state_dir / "installed_version"
    lock_file = state_dir / "upgrade.lock"
    state_file = state_dir / "update_state.json"

    # Phase 1: version-file sync (~1 ms)
    try:
        stored = installed_version_file.read_text().strip()
    except Exception:
        stored = None
    if stored != _current_version:
        try:
            subprocess = __import__("subprocess")
            subprocess.run(
                [sys.executable, "-m", "stata_agent", "install-skills", "--quiet"],
                capture_output=True, timeout=30,
            )
        except Exception:
            pass
        try:
            installed_version_file.write_text(_current_version)
        except Exception:
            pass

    # Phase 2: version check (1 s timeout unless --force)
    timeout = None if force else 1.0
    latest_info = _fetch_latest_version(timeout=timeout)
    if latest_info is None:
        return

    latest = latest_info.get("version")
    denylist = latest_info.get("denylist", [])
    emergency_disable = latest_info.get("emergency_disable", False)

    if emergency_disable:
        _write_state(state_file, {
            "last_check_ts": int(time.time()),
            "last_check_result": "skipped",
            "last_failure_reason": "Emergency disable active on remote",
            "latest_known_version": latest,
        })
        return

    if _current_version in denylist:
        _write_state(state_file, {
            "last_check_ts": int(time.time()),
            "denylist_active": True,
            "last_failure_reason": f"Version {_current_version} is denylisted",
            "latest_known_version": latest,
        })

    if latest is None or _parse_version(latest) <= _parse_version(_current_version):
        _write_state(state_file, {
            "last_check_ts": int(time.time()),
            "last_check_result": "up_to_date",
            "latest_known_version": latest,
        })
        return

    # Try to acquire lock; skip upgrade if another process holds it
    lock_fd = None
    try:
        lock_fd = open(str(lock_file), "w")
        if sys.platform == "win32":
            import msvcrt
            msvcrt.locking(lock_fd.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (OSError, IOError):
        return  # Another process is upgrading; continue with current version

    try:
        subprocess = __import__("subprocess")
        subprocess.run(
            ["uv", "tool", "upgrade", "stata-agent"],
            check=True, capture_output=True, timeout=120,
        )
    except Exception as e:
        _write_state(state_file, {
            "last_check_ts": int(time.time()),
            "last_check_result": "failed",
            "last_failure_reason": str(e),
            "latest_known_version": latest,
        })
        return  # Upgrade failed — continue with current version
    finally:
        try:
            if lock_fd:
                lock_fd.close()
        except Exception:
            pass

    _write_state(state_file, {
        "last_check_ts": int(time.time()),
        "last_check_result": "upgraded",
        "previous_version": _current_version,
        "last_upgrade_ts": int(time.time()),
        "latest_known_version": latest,
    })

    new_bin = _discover_stata_agent_binary() or sys.argv[0]
    try:
        subprocess = __import__("subprocess")
        subprocess.run(
            [new_bin, "install-skills", "--quiet"],
            capture_output=True, timeout=30,
        )
    except Exception:
        pass

    if sys.platform == "win32":
        import subprocess as sp
        result = sp.run([new_bin] + sys.argv[1:])
        sys.exit(result.returncode)
    else:
        os.execv(new_bin, [new_bin] + sys.argv[1:])

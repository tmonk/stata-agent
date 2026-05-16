"""Tests for semantic-release versioning configuration.

Verifies that the [tool.semantic_release] settings in pyproject.toml
prevent accidental major version bumps (0.x.x → 1.0.0) when there are
no breaking changes in the commit history.

python-semantic-release v10 changed the default of ``allow_zero_version``
from ``true`` to ``false``. When ``false``, ANY first release from a 0.x.x
version is forced to 1.0.0 regardless of commit types. The project
explicitly sets ``allow_zero_version = true`` to opt out of this behaviour.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path


def _semantic_release_binary() -> str:
    """Return the path to the semantic-release CLI (or module invocation)."""
    # Prefer the module invocation since it's always available in the venv
    return f"{sys.executable} -m semantic_release"


def _run_semantic_release(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    """Run ``semantic-release --noop version --print *args`` and return result."""
    cmd = [sys.executable, "-m", "semantic_release", "--noop", "version", "--print", *args]
    return subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=30,
    )


def _init_temp_repo(
    path: Path,
    *,
    allow_zero_version: bool = True,
    major_on_zero: bool = True,
) -> None:
    """Initialise a minimal git repo with a semantic-release config at *path*.

    Sets up the same [tool.semantic_release] config values used by the real project.
    """
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=path, check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=path, check=True, capture_output=True,
    )

    # Add a dummy remote so semantic-release doesn't fail on remote check
    subprocess.run(
        ["git", "remote", "add", "origin", "https://github.com/test/test.git"],
        cwd=path, check=True, capture_output=True,
    )

    # Write pyproject.toml matching the project's semantic-release config
    config = textwrap.dedent(f"""\
        [tool.semantic_release]
        allow_zero_version = {str(allow_zero_version).lower()}
        branch = "main"
        commit_message = "chore(release): {{version}} [skip ci]"
        tag_format = "v{{version}}"
    """)
    (path / "pyproject.toml").write_text(config)


def _setup_zero_version_repo(
    repo_dir: Path,
    *,
    allow_zero_version: bool = True,
) -> None:
    """Set up a git repo starting at v0.1.0 with non-breaking commits."""
    _init_temp_repo(repo_dir, allow_zero_version=allow_zero_version)

    # Initial commit and tag v0.1.0
    subprocess.run(["git", "add", "."], cwd=repo_dir, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "chore: initial commit"],
        cwd=repo_dir, check=True, capture_output=True,
    )
    subprocess.run(["git", "tag", "v0.1.0"], cwd=repo_dir, check=True, capture_output=True)

    # Add non-breaking commits
    (repo_dir / "fix.txt").write_text("fix")
    subprocess.run(["git", "add", "."], cwd=repo_dir, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "fix: resolve edge case in data parsing"],
        cwd=repo_dir, check=True, capture_output=True,
    )

    (repo_dir / "ci.txt").write_text("ci change")
    subprocess.run(["git", "add", "."], cwd=repo_dir, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "ci: speed up CI pipeline"],
        cwd=repo_dir, check=True, capture_output=True,
    )

    (repo_dir / "chore.txt").write_text("chore")
    subprocess.run(["git", "add", "."], cwd=repo_dir, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "chore: update dependencies"],
        cwd=repo_dir, check=True, capture_output=True,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestSemanticReleaseVersioning:
    """Verify that semantic-release version calculation behaves as expected."""

    def test_allow_zero_version_true_keeps_0x(
        self, tmp_path: Path,
    ) -> None:
        """When allow_zero_version=true, 0.x.x stays in 0.x.x with non-breaking commits.

        This is the project's desired behaviour — no accidental 1.0.0.
        """
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        _setup_zero_version_repo(repo_dir, allow_zero_version=True)

        result = _run_semantic_release(repo_dir)
        assert result.returncode == 0, f"semantic-release failed: {result.stderr}"

        version = result.stdout.strip()
        print(f"[allow_zero_version=true] Computed version: {version}")

        assert version.startswith("0."), (
            f"Expected 0.x.x version but got {version!r}. "
            "With allow_zero_version=true and only fix/ci/chore commits, "
            "the version should stay in 0.x range."
        )

    def test_allow_zero_version_false_bumps_to_1x(
        self, tmp_path: Path,
    ) -> None:
        """When allow_zero_version=false (the v10 default), 0.x.x → 1.0.0.

        This documents the problematic default that the project opts out of.
        It should produce 1.0.0 even with only non-breaking commits.
        """
        repo_dir = tmp_path / "repo-false"
        repo_dir.mkdir()
        _setup_zero_version_repo(repo_dir, allow_zero_version=False)

        result = _run_semantic_release(repo_dir)
        assert result.returncode == 0, f"semantic-release failed: {result.stderr}"

        version = result.stdout.strip()
        print(f"[allow_zero_version=false] Computed version: {version}")

        # With allow_zero_version=false, PSR forces the first release to 1.0.0
        assert version.startswith("1."), (
            f"Expected 1.x.x version but got {version!r}. "
            "With allow_zero_version=false, the first release from 0.x.x "
            "should be forced to 1.0.0 per PSR v10+ defaults."
        )

    def test_breaking_change_still_bumps_major(
        self, tmp_path: Path,
    ) -> None:
        """Even with allow_zero_version=true, a breaking commit → 1.0.0.

        This ensures the config only prevents *accidental* major bumps,
        not legitimate ones.
        """
        repo_dir = tmp_path / "repo-breaking"
        repo_dir.mkdir()
        _init_temp_repo(repo_dir, allow_zero_version=True)

        # Initial commit and tag v0.1.0
        subprocess.run(["git", "add", "."], cwd=repo_dir, check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "chore: initial commit"],
            cwd=repo_dir, check=True, capture_output=True,
        )
        subprocess.run(["git", "tag", "v0.1.0"], cwd=repo_dir, check=True, capture_output=True)

        # Add a breaking change commit (feat! or with BREAKING CHANGE in body)
        (repo_dir / "breaking.txt").write_text("breaking change")
        subprocess.run(["git", "add", "."], cwd=repo_dir, check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "feat: redesign API\n\nBREAKING CHANGE: completely new interface"],
            cwd=repo_dir, check=True, capture_output=True,
        )

        result = _run_semantic_release(repo_dir)
        assert result.returncode == 0, f"semantic-release failed: {result.stderr}"

        version = result.stdout.strip()
        print(f"[breaking change] Computed version: {version}")

        assert version.startswith("1."), (
            f"Expected 1.x.x version for a breaking change but got {version!r}."
        )

    def test_actual_project_config_produces_0x(
        self, tmp_path: Path,
    ) -> None:
        """The project's actual pyproject.toml config produces 0.x.x from 0.x.x.

        This reads the verbatim [tool.semantic_release] section from the
        real pyproject.toml to ensure the project's own config works.
        """
        project_root = Path(__file__).resolve().parents[2]
        actual_config = (project_root / "pyproject.toml").read_text()

        repo_dir = tmp_path / "repo-project"
        repo_dir.mkdir()
        _init_temp_repo(repo_dir, allow_zero_version=True)

        # Overwrite with the project's actual semantic-release config section
        # Extract the [tool.semantic_release] section from the real pyproject.toml
        semantic_release_section = _extract_semantic_release_config(actual_config)
        if semantic_release_section:
            (repo_dir / "pyproject.toml").write_text(semantic_release_section)

        # Initial commit and tag v0.1.0
        subprocess.run(["git", "add", "."], cwd=repo_dir, check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "chore: initial commit"],
            cwd=repo_dir, check=True, capture_output=True,
        )
        subprocess.run(["git", "tag", "v0.1.0"], cwd=repo_dir, check=True, capture_output=True)

        # Add fix and ci commits (like the real project)
        (repo_dir / "fix.txt").write_text("fix")
        subprocess.run(["git", "add", "."], cwd=repo_dir, check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "fix: resolve edge case"],
            cwd=repo_dir, check=True, capture_output=True,
        )

        result = _run_semantic_release(repo_dir)
        assert result.returncode == 0, f"semantic-release failed: {result.stderr}"

        version = result.stdout.strip()
        print(f"[project config] Computed version: {version}")

        assert version.startswith("0."), (
            f"Expected 0.x.x version with the project's config but got {version!r}. "
            "Verify pyproject.toml [tool.semantic_release] has allow_zero_version=true."
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extract_semantic_release_config(pyproject_content: str) -> str | None:
    """Extract the [tool.semantic_release] section from pyproject.toml content."""
    lines = pyproject_content.splitlines()
    start = None
    end = None
    for i, line in enumerate(lines):
        if line.strip().startswith("[tool.semantic_release]"):
            start = i
        elif start is not None and line.strip().startswith("[") and i > start:
            end = i
            break
    if start is None:
        return None
    section = lines[start:end]
    return "\n".join(section)

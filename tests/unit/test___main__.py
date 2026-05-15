"""Unit tests for __main__.py — verifies the `python -m stata_agent` entry point."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


class TestMainModule:
    """Tests for the ``-m stata_agent`` entry point."""

    def test_main_module_runs_cli(self) -> None:
        """Running ``python -m stata_agent --help`` should delegate to CLI and exit."""
        result = subprocess.run(
            [sys.executable, "-m", "stata_agent", "--help"],
            capture_output=True,
            text=True,
            cwd=str(Path(__file__).resolve().parents[2]),
        )
        # argparse --help exits with 2 (usage error), but should still print help
        assert "usage:" in result.stdout.lower() or "usage:" in result.stderr.lower()

    def test_main_module_imports_cli(self) -> None:
        """Verify the __main__ module can be imported without error."""
        # Import as a module (not __main__) to test the import path
        import importlib
        spec = importlib.util.find_spec("stata_agent.__main__")
        assert spec is not None, "__main__ module spec not found"
        mod = importlib.import_module("stata_agent.__main__")
        # Verify it has the expected reference to cli.main
        assert hasattr(mod, "main") or "cli" in dir(mod)

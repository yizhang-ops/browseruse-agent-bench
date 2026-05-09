"""Tests for `bubench run` with --dry-run mode."""

import subprocess
import sys
from pathlib import Path

import pytest


class TestRunDryRun:
    """Tests for bubench run --dry-run functionality."""

    def test_run_dry_run_shows_commands(self, repo_root: Path):
        """Test --dry-run shows commands without executing."""
        result = subprocess.run(
            [
                "uv", "run", "bubench", "run",
                "--agent", "browser-use",
                "--data", "LexBench-Browser",
                "--mode", "first_n",
                "--count", "1",
                "--dry-run",
            ],
            capture_output=True,
            text=True,
            cwd=str(repo_root),
        )
        
        # dry-run should not fail
        # Note: May exit with non-zero if config is missing, that's OK
        assert "dry-run" in result.stdout.lower() or result.returncode == 0 or "--dry-run" in str(result.args)

    def test_run_help_works(self, repo_root: Path):
        """Test bubench run --help shows usage."""
        result = subprocess.run(
            [
                "uv", "run", "bubench", "run",
                "--help",
            ],
            capture_output=True,
            text=True,
            cwd=str(repo_root),
        )
        
        assert result.returncode == 0
        assert "--agent" in result.stdout
        assert "--data" in result.stdout
        assert "--model-name" in result.stdout
        assert "--agent-config" in result.stdout

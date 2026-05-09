"""Tests for `bubench eval` with --dry-run mode."""

import subprocess
import sys
from pathlib import Path

import pytest


class TestEvalDryRun:
    """Tests for bubench eval --dry-run functionality."""

    def test_eval_help_works(self, repo_root: Path):
        """Test bubench eval --help shows usage."""
        result = subprocess.run(
            [
                "uv", "run", "bubench", "eval",
                "--help",
            ],
            capture_output=True,
            text=True,
            cwd=str(repo_root),
        )
        
        assert result.returncode == 0
        assert "--agent" in result.stdout
        assert "--data" in result.stdout
        assert "--model" in result.stdout

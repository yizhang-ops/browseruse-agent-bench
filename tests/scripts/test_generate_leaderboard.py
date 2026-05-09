"""Tests for bubench leaderboard command."""

import subprocess
from pathlib import Path

import pytest


class TestGenerateLeaderboard:
    """Tests for leaderboard CLI functionality."""

    def test_generate_leaderboard_help(self, repo_root: Path):
        """Test bubench leaderboard --help works."""
        result = subprocess.run(
            [
                "uv", "run",
                "bubench",
                "leaderboard",
                "--help",
            ],
            capture_output=True,
            text=True,
            cwd=str(repo_root),
        )
        
        # Should show help or execute successfully
        assert result.returncode == 0 or "usage" in result.stdout.lower()

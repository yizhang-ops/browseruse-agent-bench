"""Tests for browseruse_bench.utils.utils module."""

import os
import tempfile
from pathlib import Path

import pytest

from browseruse_bench.utils import (
    check_uv_available,
    find_latest_tasks_dir,
    get_env_var,
    load_env_file,
)


class TestLoadEnvFile:
    """Tests for load_env_file function."""

    def test_load_env_file(self, tmp_path: Path):
        """Test loading .env file sets environment variables."""
        env_file = tmp_path / ".env"
        env_file.write_text("TEST_VAR_123=hello_world\n")

        load_env_file(env_file)

        assert os.environ.get("TEST_VAR_123") == "hello_world"
        # Cleanup
        del os.environ["TEST_VAR_123"]

    def test_load_nonexistent_env_file(self, tmp_path: Path):
        """Test loading non-existent env file doesn't raise."""
        load_env_file(tmp_path / "nonexistent.env")
        # Should not raise


class TestGetEnvVar:
    """Tests for get_env_var function."""

    def test_get_env_var_exists(self):
        """Test getting existing environment variable."""
        os.environ["TEST_GET_VAR"] = "test_value"
        
        result = get_env_var("TEST_GET_VAR")
        
        assert result == "test_value"
        del os.environ["TEST_GET_VAR"]

    def test_get_env_var_with_default(self):
        """Test getting non-existent var returns default."""
        result = get_env_var("NONEXISTENT_VAR_XYZ", default="fallback")
        assert result == "fallback"


class TestFindLatestTasksDir:
    """Tests for find_latest_tasks_dir function."""

    def test_find_latest_tasks_dir(self, tmp_path: Path):
        """Test finding latest tasks directory by timestamp."""
        # Create timestamp directories
        dir1 = tmp_path / "20260101_100000"
        dir2 = tmp_path / "20260102_100000"
        dir3 = tmp_path / "20260101_120000"
        
        for d in [dir1, dir2, dir3]:
            d.mkdir()
            (d / "tasks").mkdir()

        result = find_latest_tasks_dir(tmp_path)

        # Should return the latest by name (20260102)
        assert result is not None
        assert "20260102" in str(result)


class TestCheckUvAvailable:
    """Tests for check_uv_available function."""

    def test_check_uv_available_returns_bool(self):
        """Test that check_uv_available returns a boolean."""
        result = check_uv_available()
        assert isinstance(result, bool)

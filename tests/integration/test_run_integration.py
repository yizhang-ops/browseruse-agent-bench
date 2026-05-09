"""Integration tests for `bubench run`

These tests verify the run.py script works correctly with mock data,
without actually running browser agents.
"""

import json
from pathlib import Path

import pytest

from browseruse_bench.utils import (
    get_default_split,
    load_data_info,
)


class TestDataInfoLoading:
    """Test data_info.json loading logic."""

    def test_load_data_info_with_split(self, tmp_path: Path):
        """Test loading data_info with split structure."""
        data_info = {
            "default_split": "All",
            "split": {
                "All": "tasks_all.json",
                "subset": "tasks_subset.json"
            }
        }
        (tmp_path / "data_info.json").write_text(json.dumps(data_info))

        result = load_data_info(tmp_path)

        assert result["default_split"] == "All"
        assert "All" in result["split"]

    def test_get_default_split_uses_explicit_default(self, tmp_path: Path):
        """Test that explicit default_split takes precedence."""
        data_info = {
            "default_split": "subset",
            "split": {
                "All": "tasks_all.json",
                "subset": "tasks_subset.json",
            }
        }

        result = get_default_split(data_info)

        assert result == "subset"

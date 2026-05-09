"""Tests for browseruse_bench.utils.stats_utils module."""

import pytest

from browseruse_bench.utils import filter_tasks_by_label, generate_evaluation_summary


class TestFilterTasksByLabel:
    """Tests for filter_tasks_by_label function."""

    @pytest.fixture
    def sample_results(self):
        return [
            {"task_id": "1", "predicted_label": 1},  # success = 1
            {"task_id": "2", "predicted_label": 0},  # failed = 0
            {"task_id": "3", "predicted_label": 1},
            {"task_id": "4", "predicted_label": 0},
        ]

    def test_filter_success_tasks(self, sample_results):
        """Test filtering success tasks."""
        result = filter_tasks_by_label(sample_results, key="predicted_label", val=1)
        assert len(result) == 2
        assert all(r["predicted_label"] == 1 for r in result)

    def test_filter_failed_tasks(self, sample_results):
        """Test filtering failed tasks."""
        result = filter_tasks_by_label(sample_results, key="predicted_label", val=0)
        assert len(result) == 2
        assert all(r["predicted_label"] == 0 for r in result)

    def test_filter_empty_list(self):
        """Test filtering empty list returns empty."""
        result = filter_tasks_by_label([], key="predicted_label", val=1)
        assert result == []

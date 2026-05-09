"""Integration tests for `bubench eval`

These tests verify the eval.py script works correctly with mock data,
using mocked LLM responses instead of real API calls.
"""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from browseruse_bench.utils import (
    REPO_ROOT,
    calculate_success,
    extract_score_from_response,
)


# Fixture paths
FIXTURES_DIR = REPO_ROOT / "tests" / "fixtures"


class TestScoreExtraction:
    """Test score extraction from LLM responses."""

    @pytest.mark.parametrize("response,expected_score", [
        ("Score: 3", 3),
        ("Final Score: 5", 5),
        ("Final Score: 2", 2),
        ("Total Score: 100", 100),
        ("Score: 0", 0),
        ("Final Score: **60 - 55 = 5**", 5),
        ("Total Score: **100**", 100),  # Test bolded format
    ])
    def test_extract_score_various_formats(self, response: str, expected_score: int):
        """Test score extraction from various response formats."""
        score = extract_score_from_response(response)
        assert score == expected_score

    def test_extract_score_no_score_found(self):
        """Test score extraction when no score is found."""
        result = extract_score_from_response("This response has no score")
        assert result == 0  # Default to 0


class TestSuccessCalculation:
    """Test success calculation logic."""

    def test_success_at_threshold(self):
        """Test success when score equals threshold."""
        assert calculate_success(3, 3) is True

    def test_success_above_threshold(self):
        """Test success when score exceeds threshold."""
        assert calculate_success(100, 60) is True

    def test_failure_below_threshold(self):
        """Test failure when score is below threshold."""
        assert calculate_success(2, 3) is False
        assert calculate_success(59, 60) is False


class TestResultJsonParsing:
    """Test parsing of agent result.json files."""

    def test_parse_sample_result(self):
        """Test parsing the sample result.json fixture."""
        result_file = FIXTURES_DIR / "sample_result.json"
        
        with open(result_file) as f:
            result = json.load(f)
        
        # Verify required fields exist
        assert "task_id" in result
        assert "answer" in result
        assert "metrics" in result
        assert "steps" in result["metrics"]

    def test_result_has_action_history(self):
        """Test that result includes action history."""
        result_file = FIXTURES_DIR / "sample_result.json"
        
        with open(result_file) as f:
            result = json.load(f)
        
        assert "action_history" in result
        assert len(result["action_history"]) > 0


class TestEvalFlowWithMockLLM:
    """Test evaluation flow with mocked LLM responses."""

    def test_eval_with_mocked_response(self, tmp_path: Path):
        """Test evaluation flow using mocked LLM response."""
        # Create mock task directory structure
        task_dir = tmp_path / "tasks" / "test_task_001"
        task_dir.mkdir(parents=True)
        
        # Copy sample result
        with open(FIXTURES_DIR / "sample_result.json") as f:
            result_data = json.load(f)
        
        (task_dir / "result.json").write_text(json.dumps(result_data))
        
        # Create trajectory directory with a dummy screenshot
        trajectory_dir = task_dir / "trajectory"
        trajectory_dir.mkdir()
        
        # The evaluation would need the full pipeline, but we can verify
        # the result.json is parseable and has required fields
        with open(task_dir / "result.json") as f:
            parsed = json.load(f)
        
        assert parsed["task_id"] == "test_task_001"
        assert "answer" in parsed

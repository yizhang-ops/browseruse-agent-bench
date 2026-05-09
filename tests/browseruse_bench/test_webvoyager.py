"""Tests for WebVoyager benchmark integration."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest

from browseruse_bench.utils import load_tasks


class TestLoadTasksWebVoyagerFields:
    """Tests that load_tasks() handles WebVoyager's ques and web field names."""

    def test_load_tasks_webvoyager_ques_field(self, tmp_path: Path):
        """WebVoyager tasks use 'ques' for the task text — load_tasks must handle it."""
        tasks_data = [
            {"id": "Amazon--0", "web_name": "Amazon", "ques": "Find the cheapest laptop.", "web": "https://www.amazon.com"},
        ]
        tasks_file = tmp_path / "task.jsonl"
        tasks_file.write_text(json.dumps(tasks_data[0]) + "\n")

        tasks = load_tasks(str(tasks_file))

        assert len(tasks) == 1
        assert tasks[0]["task_text"] == "Find the cheapest laptop."

    def test_load_tasks_webvoyager_web_field(self, tmp_path: Path):
        """WebVoyager tasks use 'web' for the starting URL — load_tasks must handle it."""
        tasks_data = [
            {"id": "Amazon--0", "web_name": "Amazon", "ques": "Find something.", "web": "https://www.amazon.com"},
        ]
        tasks_file = tmp_path / "task.jsonl"
        tasks_file.write_text(json.dumps(tasks_data[0]) + "\n")

        tasks = load_tasks(str(tasks_file))

        assert tasks[0]["url"] == "https://www.amazon.com"

    def test_load_tasks_webvoyager_id_becomes_task_id(self, tmp_path: Path):
        """WebVoyager uses 'id' string field — mapped to task_id."""
        tasks_file = tmp_path / "task.jsonl"
        tasks_file.write_text(json.dumps(
            {"id": "Google--5", "web_name": "Google", "ques": "Search something.", "web": "https://www.google.com"}
        ) + "\n")

        tasks = load_tasks(str(tasks_file))

        assert tasks[0]["task_id"] == "Google--5"

    def test_load_tasks_existing_fields_take_priority_over_ques(self, tmp_path: Path):
        """When both 'task' and 'ques' exist, 'task' wins (existing priority order)."""
        tasks_file = tmp_path / "task.jsonl"
        tasks_file.write_text(json.dumps(
            {"task_id": "t1", "task": "High priority task", "ques": "Low priority", "web": "https://example.com"}
        ) + "\n")

        tasks = load_tasks(str(tasks_file))

        assert tasks[0]["task_text"] == "High priority task"

    def test_load_tasks_existing_url_fields_take_priority_over_web(self, tmp_path: Path):
        """When both 'url' and 'web' exist, 'url' wins."""
        tasks_file = tmp_path / "task.jsonl"
        tasks_file.write_text(json.dumps(
            {"task_id": "t1", "task": "Do it", "url": "https://priority.com", "web": "https://fallback.com"}
        ) + "\n")

        tasks = load_tasks(str(tasks_file))

        assert tasks[0]["url"] == "https://priority.com"


class TestWebVoyagerRegistry:
    """Tests that WebVoyager evaluator is registered."""

    def test_webvoyager_in_list_evaluators(self):
        from browseruse_bench.eval.registry import list_evaluators
        assert "WebVoyager" in list_evaluators()

    def test_webvoyager_get_evaluator_class(self):
        from browseruse_bench.eval.registry import get_evaluator_class
        cls = get_evaluator_class("WebVoyager")
        from browseruse_bench.eval.base import BaseEvaluator
        assert issubclass(cls, BaseEvaluator)


class TestGradeScreenshot:
    """Tests for the WebVoyager screenshot grader."""

    def _make_mock_model(self, response_text: str) -> MagicMock:
        model = MagicMock()
        model.generate.return_value = response_text
        model.last_usage = None
        return model

    def test_grade_success_response_returns_is_correct_true(self, tmp_path: Path):
        """Model responding SUCCESS means task was completed successfully."""
        from browseruse_bench.eval.webvoyager.grader import grade_screenshot
        model = self._make_mock_model("The agent found the cheapest laptop. SUCCESS")

        result = grade_screenshot(
            task="Find the cheapest laptop.",
            answer="The cheapest laptop is $299.",
            screenshot_paths=[],
            model=model,
        )

        assert result["is_correct"] is True

    def test_grade_not_success_response_returns_is_correct_false(self, tmp_path: Path):
        """Model responding NOT SUCCESS means task was not completed."""
        from browseruse_bench.eval.webvoyager.grader import grade_screenshot
        model = self._make_mock_model("The agent failed to find the correct answer. NOT SUCCESS")

        result = grade_screenshot(
            task="Find the cheapest laptop.",
            answer="I could not find it.",
            screenshot_paths=[],
            model=model,
        )

        assert result["is_correct"] is False

    def test_grade_not_success_takes_priority_over_success(self, tmp_path: Path):
        """NOT SUCCESS must be checked before SUCCESS to avoid false positives."""
        from browseruse_bench.eval.webvoyager.grader import grade_screenshot
        model = self._make_mock_model("This is NOT SUCCESS even though it contains SUCCESS.")

        result = grade_screenshot(
            task="Search for something.",
            answer="Done.",
            screenshot_paths=[],
            model=model,
        )

        assert result["is_correct"] is False

    def test_grade_ambiguous_response_returns_is_correct_false(self, tmp_path: Path):
        """When response contains neither YES nor NO, default to failure."""
        from browseruse_bench.eval.webvoyager.grader import grade_screenshot
        model = self._make_mock_model("I cannot determine from the screenshots.")

        result = grade_screenshot(
            task="Search for something.",
            answer="",
            screenshot_paths=[],
            model=model,
        )

        assert result["is_correct"] is False

    def test_grade_returns_response_text(self, tmp_path: Path):
        """Result dict includes the raw model response."""
        from browseruse_bench.eval.webvoyager.grader import grade_screenshot
        model = self._make_mock_model("Task done. SUCCESS")

        result = grade_screenshot(
            task="Do something.",
            answer="Done.",
            screenshot_paths=[],
            model=model,
        )

        assert result["response"] == "Task done. SUCCESS"


class TestWebVoyagerEvaluatorLoadTasks:
    """Tests for WebVoyagerEvaluator.load_tasks()."""

    def _make_task_file(self, tmp_path: Path, tasks: List[Dict[str, Any]]) -> Path:
        tasks_file = tmp_path / "task.jsonl"
        tasks_file.write_text("\n".join(json.dumps(t) for t in tasks) + "\n")
        return tasks_file

    def test_load_tasks_maps_id_to_task_id(self, tmp_path: Path):
        """Evaluator maps WebVoyager 'id' → task_id."""
        from browseruse_bench.eval.base import EvaluatorArgs
        from browseruse_bench.eval.webvoyager.evaluator import WebVoyagerEvaluator

        task_file = self._make_task_file(tmp_path, [
            {"id": "Amazon--0", "web_name": "Amazon", "ques": "Find a laptop.", "web": "https://www.amazon.com"},
        ])

        args = EvaluatorArgs(
            benchmark="WebVoyager", model="gpt-4o", api_key="test",
            base_url=None, trajectories_dir=tmp_path, output_path=tmp_path,
            score_threshold=None, num_worker=1, temperature=None,
            split="All", data_source="local", mode="WebVoyager_eval",
        )
        ev = WebVoyagerEvaluator(args, model=None)

        with patch(
            "browseruse_bench.eval.webvoyager.evaluator.REPO_ROOT",
            tmp_path,
        ), patch(
            "browseruse_bench.eval.webvoyager.evaluator._TASKS_FILE_PATH",
            task_file,
        ):
            tasks = ev.load_tasks()

        assert "Amazon--0" in tasks

    def test_load_tasks_stores_ques_as_query(self, tmp_path: Path):
        """Evaluator stores the 'ques' value so evaluate_one can use it as task description."""
        from browseruse_bench.eval.base import EvaluatorArgs
        from browseruse_bench.eval.webvoyager.evaluator import WebVoyagerEvaluator

        task_file = self._make_task_file(tmp_path, [
            {"id": "Google--1", "web_name": "Google", "ques": "Search for Claude.", "web": "https://www.google.com"},
        ])

        args = EvaluatorArgs(
            benchmark="WebVoyager", model="gpt-4o", api_key="test",
            base_url=None, trajectories_dir=tmp_path, output_path=tmp_path,
            score_threshold=None, num_worker=1, temperature=None,
            split="All", data_source="local", mode="WebVoyager_eval",
        )
        ev = WebVoyagerEvaluator(args, model=None)

        with patch(
            "browseruse_bench.eval.webvoyager.evaluator._TASKS_FILE_PATH",
            task_file,
        ):
            tasks = ev.load_tasks()

        task = tasks["Google--1"]
        assert task.get("ques") == "Search for Claude."

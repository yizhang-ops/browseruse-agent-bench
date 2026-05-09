"""Regression tests for LexBench missing-evaluation coverage policy."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from browseruse_bench.eval.lexbench_browser.evaluator import (
    LexBenchBrowserEvaluator,
    _is_synthetic_not_evaluated_record,
)


def _make_evaluator(tmp_path: Path, task_dirs: list[str] | None = None) -> LexBenchBrowserEvaluator:
    traj_dir = tmp_path / "tasks"
    traj_dir.mkdir()
    for tid in (task_dirs or []):
        (traj_dir / tid).mkdir()

    args = MagicMock()
    args.output_path = tmp_path
    args.trajectories_dir = traj_dir
    args.model = "test-model"
    args.extra = {"eval_strategy": "visual_judge"}
    evaluator = LexBenchBrowserEvaluator.__new__(LexBenchBrowserEvaluator)
    evaluator.args = args
    evaluator.model = None
    evaluator._expected_task_ids = []
    evaluator._dataset_name = "tasks_all"
    return evaluator


def test_ensure_full_results_coverage_adds_missing_failures(tmp_path: Path) -> None:
    """Tasks attempted but not evaluated are backfilled as synthetic failures."""
    # Directories 1, 2, 3 exist → all three were attempted.
    evaluator = _make_evaluator(tmp_path, task_dirs=["1", "2", "3"])

    results_path = evaluator.results_path()
    results_path.write_text(
        json.dumps({
            "task_id": "1",
            "task": "existing-task",
            "predicted_label": 1,
            "evaluation_details": {"score": 95},
        }, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    evaluator._expected_task_ids = ["1", "2", "3"]
    evaluator.load_tasks = MagicMock(return_value={
        "1": {"task_id": "1", "query": "Task 1"},
        "2": {"task_id": "2", "query": "Task 2"},
        "3": {"task_id": "3", "query": "Task 3"},
    })

    records = evaluator._load_all_records()
    evaluator.post_eval_hook(records)

    saved = [
        json.loads(line)
        for line in results_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(saved) == 3

    by_task = {r["task_id"]: r for r in saved}
    assert by_task["1"]["predicted_label"] == 1

    task2 = by_task["2"]
    assert task2["predicted_label"] == 0
    assert task2["failure_category"] == "not_evaluated"
    details = task2["evaluation_details"]["benchmark_details"]
    assert details["is_synthetic_failure"] is True
    assert details["missing_reason"] == "not_evaluated"

    task3 = by_task["3"]
    assert task3["predicted_label"] == 0
    assert task3["evaluation_details"]["benchmark_details"]["missing_reason"] == "not_evaluated"


def test_post_eval_hook_ignores_tasks_not_in_trajectories_dir(tmp_path: Path) -> None:
    """Tasks in _expected_task_ids but with no trajectory dir are not backfilled."""
    # Only task 1 was run (has a dir); tasks 2 and 3 were never attempted.
    evaluator = _make_evaluator(tmp_path, task_dirs=["1"])

    results_path = evaluator.results_path()
    results_path.write_text(
        json.dumps({
            "task_id": "1",
            "task": "existing-task",
            "predicted_label": 1,
            "evaluation_details": {"score": 95},
        }, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    # Dataset has 3 tasks, but only 1 was run.
    evaluator._expected_task_ids = ["1", "2", "3"]
    evaluator.load_tasks = MagicMock(return_value={
        "1": {"task_id": "1", "query": "Task 1"},
        "2": {"task_id": "2", "query": "Task 2"},
        "3": {"task_id": "3", "query": "Task 3"},
    })

    records = evaluator._load_all_records()
    evaluator.post_eval_hook(records)

    saved = [
        json.loads(line)
        for line in results_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    # Only task 1 should be present — 2 and 3 were never run.
    assert len(saved) == 1
    assert saved[0]["task_id"] == "1"
    assert saved[0]["predicted_label"] == 1


def test_load_already_evaluated_skips_synthetic_not_evaluated_records(tmp_path: Path) -> None:
    """Synthetic failure placeholders should not block future real evaluations."""
    evaluator = _make_evaluator(tmp_path)

    results_path = evaluator.results_path()
    results_path.write_text(
        "\n".join([
            json.dumps({
                "task_id": "real-task",
                "predicted_label": 1,
                "evaluation_details": {"score": 100},
            }, ensure_ascii=False),
            json.dumps({
                "task_id": "missing-task",
                "predicted_label": 0,
                "failure_category": "not_evaluated",
                "evaluation_details": {
                    "benchmark_details": {
                        "is_synthetic_failure": True,
                        "missing_reason": "not_evaluated",
                    },
                },
            }, ensure_ascii=False),
        ]) + "\n",
        encoding="utf-8",
    )

    already_done = evaluator._resume_skip_set()
    assert already_done == {"real-task"}


def test_is_synthetic_not_evaluated_record() -> None:
    synthetic = {
        "task_id": "t1",
        "predicted_label": 0,
        "failure_category": "not_evaluated",
    }
    assert _is_synthetic_not_evaluated_record(synthetic) is True

    real = {"task_id": "t2", "predicted_label": 1, "failure_category": "not_evaluated"}
    assert _is_synthetic_not_evaluated_record(real) is False

    other_failure = {"task_id": "t3", "predicted_label": 0, "failure_category": "agent_error"}
    assert _is_synthetic_not_evaluated_record(other_failure) is False

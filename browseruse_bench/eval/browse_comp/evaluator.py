"""BrowseComp-style evaluators: text grading with short final answers."""
from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, ClassVar

from browseruse_bench.eval.base import BaseEvaluator
from browseruse_bench.eval.browse_comp.grader import (
    grade_response,
    load_grader_model,
)
from browseruse_bench.schemas import (
    AgentMetrics,
    AgentResultRef,
    AgentUsage,
    EvalDetails,
    EvalResult,
    EvalUsage,
)
from browseruse_bench.utils import (
    REPO_ROOT,
    DataSource,
    load_data_info,
    load_dataset_file,
    load_task_file,
)
from browseruse_bench.utils.browsecomp_core import (
    BrowseCompFamilyConfig,
    get_browsecomp_family_config,
    normalize_browsecomp_family_record,
)

logger = logging.getLogger(__name__)


def _resolve_split_entry(splits: dict[str, Any], split: str) -> str:
    if split not in splits:
        available = ", ".join(sorted(splits))
        raise ValueError(f"Unknown split '{split}'. Available: {available}")
    value = splits[split]
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for key in ("path", "file", "filename"):
            candidate = value.get(key)
            if isinstance(candidate, str) and candidate:
                return candidate
    raise ValueError(f"Invalid split entry for '{split}'")


def _resolve_tasks_file(
    benchmark: str,
    split: str,
    data_source: str,
    force_download: bool,
) -> Path:
    benchmark_path = REPO_ROOT / "browseruse_bench" / "data" / benchmark
    data_info = load_data_info(benchmark_path)
    tasks_filename = _resolve_split_entry(data_info.get("split", {}), split)
    local_path = benchmark_path / tasks_filename
    return load_dataset_file(
        local_path=local_path,
        data_info=data_info,
        data_source=data_source,
        force_download=force_download,
        split=split,
        benchmark_name=benchmark,
    )


class BrowseCompFamilyEvaluator(BaseEvaluator):
    name: ClassVar[str] = "BrowseComp"
    default_mode: ClassVar[str] = "BrowseComp_grader_eval"

    def __init__(self, args, model):
        # BrowseComp grade_response expects a callable grader (GraderModel.__call__),
        # not the generic EvaluationModel.generate() interface.
        super().__init__(args, model)
        self._grader = load_grader_model(
            args.model, args.api_key, args.base_url, temperature=args.temperature,
        )
        self._tasks_json: Path | None = None
        self._dataset_name: str | None = None

    def results_filename(self) -> str:
        return f"{self.name}_grader_eval_{self.args.model}_results.json"

    def summary_filename(self) -> str:
        return f"{self.name}_grader_eval_{self.args.model}_summary.json"

    @property
    def family_config(self) -> BrowseCompFamilyConfig:
        config = get_browsecomp_family_config(self.name)
        if config is None:
            raise ValueError(f"No BrowseComp-family config registered for {self.name}")
        return config

    def load_tasks(self) -> dict[str, dict[str, Any]]:
        self._tasks_json = _resolve_tasks_file(
            self.name,
            self.args.split,
            self.args.data_source or DataSource.LOCAL,
            self.args.extra.get("force_download", False),
        )
        self._dataset_name = self._tasks_json.stem
        tasks: dict[str, dict[str, Any]] = {}
        for index, raw_task in enumerate(load_task_file(self._tasks_json)):
            task = normalize_browsecomp_family_record(raw_task, self.family_config, index=index)
            task_id = str(task["task_id"])
            if task_id in tasks:
                logger.warning("Duplicate task_id, keeping first: %s", task_id)
                continue
            tasks[task_id] = task
        logger.info("Loaded %d %s tasks from %s", len(tasks), self.name, self._tasks_json)
        if not tasks:
            raise ValueError(f"No valid tasks found in {self._tasks_json}")
        return tasks

    def evaluate_one(self, task_id, task, agent_result, trajectory_dir):
        question = task["task_text"]
        correct_answer = task["correct_answer"]
        agent_response = agent_result.get("answer") or agent_result.get("response", "")

        grading = grade_response(question, correct_answer, agent_response, self._grader)

        raw_usage = grading.get("usage")
        eval_usage = None
        if isinstance(raw_usage, dict):
            eval_usage = EvalUsage(**raw_usage)
        elif raw_usage is not None and hasattr(raw_usage, "model_dump"):
            eval_usage = EvalUsage(**raw_usage.model_dump())

        agent_metrics = None
        raw_metrics = agent_result.get("metrics")
        if isinstance(raw_metrics, dict):
            usage_data = raw_metrics.get("usage")
            agent_metrics = AgentMetrics(
                ttft_ms=raw_metrics.get("ttft_ms"),
                end_to_end_ms=raw_metrics.get("end_to_end_ms", 0),
                steps=raw_metrics.get("steps", 0),
                usage=AgentUsage(**usage_data) if isinstance(usage_data, dict) and usage_data else None,
            )

        eval_details = EvalDetails(
            user_prompt=grading.get("user_prompt"),
            response=grading.get("response") or grading.get("grader_response", ""),
            is_correct=grading.get("is_correct"),
            reasoning=grading.get("reasoning") or grading.get("grader_response"),
            eval_usage=eval_usage,
            agent_metrics=agent_metrics,
        )

        agent_timestamp = agent_result.get("timestamp") or datetime.now(UTC)
        agent_result_ref = AgentResultRef(
            task_id=task_id,
            timestamp=agent_timestamp,
            result_dir=str(trajectory_dir),
            model_id=agent_result.get("model_id") or "",
            browser_id=agent_result.get("browser_id") or "",
        )

        is_correct = bool(grading.get("is_correct"))
        status = "PASS" if is_correct else "FAIL"
        logger.info("%s %s", status, task_id)

        return EvalResult(
            task_id=task_id,
            task=question,
            timestamp=datetime.now(UTC),
            agent_result_ref=agent_result_ref,
            predicted_label=1 if is_correct else 0,
            model_id=agent_result.get("model_id") or "",
            browser_id=agent_result.get("browser_id") or "",
            evaluation_details=eval_details,
            correct_answer=correct_answer,
            agent_response=agent_response,
        )

    def _generate_summary(self, records: list[dict[str, Any]]) -> None:
        super()._generate_summary(records)
        path = self.summary_path()
        if not path.exists():
            return
        with open(path, encoding="utf-8") as fh:
            summary = json.load(fh)
        total = len(records)
        correct = sum(
            1 for r in records
            if (r.get("evaluation_details") or {}).get("is_correct")
        )
        accuracy = correct / total if total > 0 else 0
        summary["browsecomp_metrics"] = {
            "benchmark": self.name,
            "accuracy": accuracy,
            "correct": correct,
            "total": total,
        }
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(summary, fh, ensure_ascii=False, indent=2)
        logger.info("%s results: %d/%d = %.2f%%", self.name, correct, total, accuracy * 100)


class BrowseCompEvaluator(BrowseCompFamilyEvaluator):
    name: ClassVar[str] = "BrowseComp"
    default_mode: ClassVar[str] = "BrowseComp_grader_eval"


class LiveBrowseCompEvaluator(BrowseCompFamilyEvaluator):
    name: ClassVar[str] = "LiveBrowseComp"
    default_mode: ClassVar[str] = "LiveBrowseComp_grader_eval"


class BrowseCompZHEvaluator(BrowseCompFamilyEvaluator):
    name: ClassVar[str] = "BrowseComp-ZH"
    default_mode: ClassVar[str] = "BrowseComp-ZH_grader_eval"

"""Cost calculation, JSONL normalization, and summary generation."""
from __future__ import annotations

import json
import logging
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

logger = logging.getLogger(__name__)


def calculate_evaluation_cost(usage_dict: Any) -> Optional[Dict[str, Any]]:
    """Calculate total cost based on usage and pricing.

    Pricing (per million tokens):
    - Input: ￥10 / M tokens
    - Output: ￥40 / M tokens
    - Cached: ￥2.5 / M tokens
    """
    if not usage_dict:
        return None

    if not isinstance(usage_dict, dict):
        if hasattr(usage_dict, "__dict__"):
            usage_dict = usage_dict.__dict__
        elif hasattr(usage_dict, "model_dump"):
            usage_dict = usage_dict.model_dump()
        else:
            return None

    prompt_tokens = usage_dict.get("prompt_tokens", 0)
    completion_tokens = usage_dict.get("completion_tokens", 0)

    cached_tokens = 0
    prompt_details = usage_dict.get("prompt_tokens_details", {})
    if isinstance(prompt_details, dict):
        cached_tokens = prompt_details.get("cached_tokens", 0)

    PRICE_INPUT = 10
    PRICE_OUTPUT = 40
    PRICE_CACHED = 2.5

    non_cached_prompt = max(0, prompt_tokens - cached_tokens)

    input_cost = (non_cached_prompt / 1_000_000) * PRICE_INPUT
    output_cost = (completion_tokens / 1_000_000) * PRICE_OUTPUT
    cached_cost = (cached_tokens / 1_000_000) * PRICE_CACHED

    total_cost = input_cost + output_cost + cached_cost

    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "cached_tokens": cached_tokens,
        "non_cached_prompt": non_cached_prompt,
        "costs": {
            "input": input_cost,
            "output": output_cost,
            "cached": cached_cost,
            "total": total_cost,
        },
    }


def aggregate_evaluation_costs(usage_list: List[Any]) -> Dict[str, Any]:
    """Aggregate costs from multiple usage dictionaries."""
    total_prompt = 0
    total_completion = 0
    total_cached = 0
    total_input_cost = 0.0
    total_output_cost = 0.0
    total_cached_cost = 0.0

    for usage in usage_list:
        if usage is None:
            continue
        cost_info = calculate_evaluation_cost(usage)
        if cost_info:
            total_prompt += cost_info["prompt_tokens"]
            total_completion += cost_info["completion_tokens"]
            total_cached += cost_info["cached_tokens"]
            total_input_cost += cost_info["costs"]["input"]
            total_output_cost += cost_info["costs"]["output"]
            total_cached_cost += cost_info["costs"]["cached"]

    total_cost = total_input_cost + total_output_cost + total_cached_cost

    return {
        "total_prompt_tokens": total_prompt,
        "total_completion_tokens": total_completion,
        "total_cached_tokens": total_cached,
        "total_non_cached_prompt": max(0, total_prompt - total_cached),
        "costs": {
            "input": total_input_cost,
            "output": total_output_cost,
            "cached": total_cached_cost,
            "total": total_cost,
        },
    }


def _parse_consecutive_json_objects(text: str) -> List[Any]:
    """Parse consecutive JSON objects from text (even without commas/brackets)."""
    decoder = json.JSONDecoder()
    idx = 0
    length = len(text)
    records: List[Any] = []

    while idx < length:
        while idx < length and text[idx].isspace():
            idx += 1
        if idx >= length:
            break
        try:
            obj, end = decoder.raw_decode(text, idx)
        except json.JSONDecodeError:
            return []
        records.append(obj)
        idx = end
    return records


def _convert_json_to_jsonl(results_file: Path) -> Optional[Path]:
    """Convert JSON/JSONL/messy multi-line JSON into a temporary JSONL file."""
    try:
        text = results_file.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        logger.warning("   [WARNING] Failed to read evaluation result file %s: %s", results_file, exc)
        return None

    stripped = text.lstrip()
    if not stripped:
        return None

    parsed: Optional[List[Any]] = None

    try:
        data = json.loads(text)
        if isinstance(data, dict):
            parsed = [data]
        elif isinstance(data, list):
            parsed = data
    except json.JSONDecodeError:
        parsed = _parse_consecutive_json_objects(text)

    if not parsed:
        return None

    temp_path = results_file.with_name(results_file.name + ".jsonl.tmp")
    with open(temp_path, "w", encoding="utf-8") as tmp:
        for item in parsed:
            json.dump(item, tmp, ensure_ascii=False)
            tmp.write("\n")

    return temp_path


@contextmanager
def normalized_results_file(results_file: Path) -> Iterator[Path]:
    """Yield a path that is guaranteed to be JSONL-like, cleaning up temp files."""
    temp_path = _convert_json_to_jsonl(results_file)
    try:
        yield temp_path or results_file
    finally:
        if temp_path and temp_path.exists():
            try:
                temp_path.unlink()
            except OSError as exc:
                logger.warning(f"   [WARNING] Failed to delete temp file {temp_path}: {exc}")


def generate_evaluation_summary(
    results: List[Dict[str, Any]],
    total: int,
    metrics: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Generate evaluation summary.

    Args:
        results: List of evaluation results.
        total: Total number of tasks.
        metrics: List of metrics to calculate, default is ["ttft_ms", "end_to_end_ms", "steps"].

    Returns:
        Dict[str, Any]: Summary dictionary containing overall stats, metric stats, and task list.
    """
    # Lazy import: importing browseruse_bench.utils.stats triggers utils/__init__.py
    # which itself re-exports from this module, so we defer to call time.
    from browseruse_bench.utils.stats import (
        calculate_all_metrics_stats,
        calculate_failure_category_stats,
        filter_tasks_by_label,
    )

    if metrics is None:
        metrics = ["ttft_ms", "end_to_end_ms", "steps"]
    success = filter_tasks_by_label(results, "predicted_label", 1)
    failed = filter_tasks_by_label(results, "predicted_label", 0)
    n = len(results)

    return {
        "overall_statistics": {
            "total_tasks": total,
            "evaluated_tasks": n,
            "successful_tasks": len(success),
            "failed_tasks": len(failed),
            "success_rate": round(len(success) / n * 100, 2) if n > 0 else 0,
            "failure_rate": round(len(failed) / n * 100, 2) if n > 0 else 0,
        },
        "metrics_statistics": calculate_all_metrics_stats(results, metrics),
        "successful_tasks_metrics": calculate_all_metrics_stats(success, metrics),
        "failed_tasks_metrics": calculate_all_metrics_stats(failed, metrics),
        "failure_category_statistics": calculate_failure_category_stats(results),
        "task_list": {
            "successful_task_ids": [r.get("task_id") for r in success if "task_id" in r],
            "failed_task_ids": [r.get("task_id") for r in failed if "task_id" in r],
        },
    }

#!/usr/bin/env python3
"""Generate Leaderboard HTML Report.

Generates a Leaderboard HTML page containing performance comparisons of all Agents from evaluation results.
Supports switching between multiple Benchmarks.
"""
from __future__ import annotations

import argparse
import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from browseruse_bench.utils import (
    EXPERIMENTS_DIR,
    REPO_ROOT,
    load_config_file,
    load_env_file,
    normalized_results_file,
    resolve_agent_inline_config,
    setup_logger,
)

# Load environment variables from .env file early.
load_env_file(REPO_ROOT / ".env")

# Set up logger
logger = setup_logger("leaderboard")


class LeaderboardError(RuntimeError):
    """Raised when leaderboard generation fails."""


def _load_leaderboard_config() -> Dict[str, Any]:
    try:
        config = load_config_file(REPO_ROOT / "config.yaml")
    except (OSError, ValueError, TypeError) as exc:
        logger.warning("Failed to load config.yaml: %s", exc)
        return {}
    if isinstance(config, dict):
        leaderboard_config = config.get("leaderboard")
        if isinstance(leaderboard_config, dict):
            return leaderboard_config
    return {}


def _parse_float_env(name: str) -> Optional[float]:
    raw = os.getenv(name)
    if raw is None:
        return None
    try:
        return float(raw)
    except ValueError:
        logger.warning("Invalid %s value: %s", name, raw)
        return None


def get_default_timeout_seconds() -> float:
    env_value = _parse_float_env("LEADERBOARD_TIMEOUT_SECONDS")
    if env_value is not None:
        return env_value
    config = _load_leaderboard_config()
    value = config.get("default_timeout_seconds")
    if isinstance(value, (int, float)):
        return float(value)
    logger.warning("Leaderboard timeout not configured; defaulting to 300 seconds.")
    return 300.0


def get_regenerate_timeout_seconds() -> float:
    env_value = _parse_float_env("LEADERBOARD_REGENERATE_TIMEOUT_SECONDS")
    if env_value is not None:
        return env_value
    config = _load_leaderboard_config()
    value = config.get("regenerate_timeout_seconds")
    if isinstance(value, (int, float)):
        return float(value)
    return get_default_timeout_seconds()


def get_agent_default_config(agent_name: str) -> Dict[str, str]:
    """Attempt to load default model/browser for an agent from root config.yaml.

    Used by the leaderboard as the last fallback when a particular run's
    artifacts didn't record ``model_id`` / ``browser_id`` (e.g. older
    Agent-TARS runs wrote empty strings) and we couldn't recover them from
    the on-disk layout either. Resolution goes through
    :func:`resolve_agent_inline_config`, which already merges
    ``agents.<name>.browser`` and the active model block.
    """
    defaults = {"model": "Unknown", "browser": "Unknown"}
    config_path = REPO_ROOT / "config.yaml"
    if not config_path.exists():
        return defaults

    try:
        root_config = load_config_file(config_path)
        inline = resolve_agent_inline_config(agent_name, root_config) or {}
        if inline.get("model_id"):
            defaults["model"] = str(inline.get("model_id"))
        if inline.get("browser_id"):
            defaults["browser"] = str(inline.get("browser_id"))
    except (OSError, ValueError, TypeError) as exc:
        logger.warning("Failed to load agent config from %s: %s", config_path, exc)

    return defaults

def collect_all_benchmarks_data(default_timeout_seconds: float) -> Dict[str, List[Dict[str, Any]]]:
    """Collect data from all benchmarks."""
    experiments_dir = REPO_ROOT / EXPERIMENTS_DIR

    # Ensure experiments directory exists
    experiments_dir.mkdir(parents=True, exist_ok=True)

    # Check if any directory exists (including remote-synced data)
    benchmark_dirs = list(experiments_dir.iterdir())
    if not benchmark_dirs:
        logger.warning("Local experiments directory is empty.")
        return {}

    all_data = {}

    # Scan all benchmarks
    for benchmark_dir in benchmark_dirs:
        if not benchmark_dir.is_dir() or benchmark_dir.name.startswith('.'):
            continue

        benchmark_name = benchmark_dir.name
        logger.info(f"[STATS] Processing Benchmark: {benchmark_name}")

        leaderboard_data = []

        # Scan current structure: split -> agent -> timestamp
        for split_dir in benchmark_dir.iterdir():
            if not split_dir.is_dir() or split_dir.name.startswith('.'):
                continue

            split_name = split_dir.name
            version_name = "current"
            logger.info(f"   [INFO] Split: {split_name}")

            # Scan all agents under this split
            for agent_dir in split_dir.iterdir():
                if not agent_dir.is_dir() or agent_dir.name.startswith('.'):
                    continue

                agent_name = agent_dir.name

                try:
                    # Layout: agent / model_id / timestamp
                    for model_dir in agent_dir.iterdir():
                        if not model_dir.is_dir() or model_dir.name.startswith('.'):
                            continue
                        timestamp_dirs = [
                            d for d in model_dir.iterdir()
                            if d.is_dir() and re.match(r'^\d{8}_\d{6}$', d.name)
                        ]
                        if not timestamp_dirs:
                            continue

                        for ts in sorted(timestamp_dirs, key=lambda x: x.name, reverse=True):
                            tasks_dir_probe = ts / "tasks"
                            eval_result_dir_probe = ts / "tasks_eval_result"
                            timestamp_dir_name = ts.name
                            if len(timestamp_dir_name) >= 8 and timestamp_dir_name[0].isdigit():
                                eval_date = f"{timestamp_dir_name[0:4]}-{timestamp_dir_name[4:6]}-{timestamp_dir_name[6:8]}"
                            else:
                                eval_date = "Unknown"

                            logger.info(f"         [INFO] Reading: {agent_name} ({ts.name})")

                            # First try to find evaluation result file locally
                            primary_results = sorted(eval_result_dir_probe.glob("*_results.json"))
                            auto_results = sorted(eval_result_dir_probe.glob("*_auto_eval_results.json"))
                            results_file_path = primary_results[0] if primary_results else (auto_results[0] if auto_results else None)

                            if not results_file_path:
                                logger.warning(f"            [WARNING] {ts.name} did not find *_results.json, skipping")
                                continue
                            try:
                                results_rel_path = results_file_path.relative_to(experiments_dir)
                            except (OSError, ValueError) as exc:
                                logger.warning(
                                    "Failed to get relative path for results file %s: %s",
                                    results_file_path,
                                    exc,
                                )
                                results_rel_path = None
                            try:
                                trajectories_rel_root = tasks_dir_probe.relative_to(experiments_dir)
                            except (OSError, ValueError) as exc:
                                logger.warning(
                                    "Failed to get relative path for trajectories dir %s: %s",
                                    tasks_dir_probe,
                                    exc,
                                )
                                trajectories_rel_root = None

                            failure_details: Dict[str, List[Dict[str, Any]]] = {}
                            failure_counts: Dict[str, int] = {}
                            success_details: List[Dict[str, Any]] = []
                            agent_model_id: Optional[str] = None
                            agent_browser_id: Optional[str] = None
                            agent_config_info: Dict[str, Any] = {}
                            DEFAULT_TIMEOUT_SECONDS = default_timeout_seconds
                            task_artifacts_cache: Dict[str, Dict[str, Any]] = {}
                            total_tasks = 0
                            success_count = 0
                            failure_count = 0
                            steps_sum = 0.0
                            steps_count = 0
                            e2e_sum = 0.0
                            e2e_count = 0
                            ttft_sum = 0.0
                            ttft_count = 0
                            success_tokens_sum = 0.0
                            success_tokens_count = 0
                            success_cost_sum = 0.0
                            success_cost_count = 0
                            score_sum = 0.0
                            score_count = 0

                            def parse_timeout_seconds(value: Any) -> Optional[float]:
                                if value is None:
                                    return None
                                if isinstance(value, (int, float)):
                                    return float(value)
                                if isinstance(value, str):
                                    cleaned = value.strip().lower()
                                    if cleaned.endswith("s"):
                                        cleaned = cleaned[:-1]
                                    try:
                                        return float(cleaned)
                                    except ValueError:
                                        return None
                                return None

                            def extract_task_metrics(metrics_block: Any) -> Dict[str, Any]:
                                metrics_info: Dict[str, Any] = {}
                                if not isinstance(metrics_block, dict):
                                    return metrics_info
                                if isinstance(metrics_block.get("ttft_seconds"), (int, float)):
                                    metrics_info["ttft_seconds"] = float(metrics_block["ttft_seconds"])
                                ttft_ms = metrics_block.get("ttft_ms")
                                if isinstance(ttft_ms, (int, float)):
                                    metrics_info["ttft_seconds"] = ttft_ms / 1000.0
                                if isinstance(metrics_block.get("e2e_seconds"), (int, float)):
                                    metrics_info["e2e_seconds"] = float(metrics_block["e2e_seconds"])
                                e2e_ms = metrics_block.get("end_to_end_ms")
                                if isinstance(e2e_ms, (int, float)):
                                    metrics_info["e2e_seconds"] = e2e_ms / 1000.0
                                steps_val = metrics_block.get("steps")
                                if isinstance(steps_val, (int, float)):
                                    metrics_info["steps"] = float(steps_val)
                                usage_block = metrics_block.get("usage") or {}
                                if isinstance(usage_block, dict):
                                    total_tokens = usage_block.get("total_tokens")
                                    if isinstance(total_tokens, (int, float)):
                                        metrics_info["total_tokens"] = total_tokens
                                    total_cost = usage_block.get("total_cost")
                                    if isinstance(total_cost, (int, float)):
                                        metrics_info["total_cost"] = total_cost
                                timeout_val = metrics_block.get("timeout_seconds") or metrics_block.get("timeout")
                                timeout_seconds = parse_timeout_seconds(timeout_val)
                                if timeout_seconds is not None:
                                    metrics_info["timeout_seconds"] = timeout_seconds
                                return metrics_info

                            def normalize_config(config_block: Any) -> Dict[str, Any]:
                                config: Dict[str, Any] = {}
                                if isinstance(config_block, dict):
                                    for key, value in config_block.items():
                                        if value in (None, "", []):
                                            continue
                                        config[key] = value
                                return config

                            def get_task_artifacts(task_id: str) -> Dict[str, Any]:
                                if not task_id:
                                    return {
                                        "trajectory_path": "",
                                        "trajectory_images": [],
                                        "actions": [],
                                        "metrics": {},
                                        "config": {},
                                        "model_id": None,
                                        "browser_id": None,
                                    }
                                if task_id in task_artifacts_cache:
                                    return task_artifacts_cache[task_id]

                                trajectory_path = ""
                                trajectory_images: List[str] = []
                                actions: List[Any] = []
                                fallback_metrics: Dict[str, Any] = {}
                                fallback_config: Dict[str, Any] = {}
                                fallback_model: Optional[str] = None
                                fallback_browser: Optional[str] = None

                                if trajectories_rel_root is not None:
                                    trajectory_path = f"{trajectories_rel_root.as_posix()}/{task_id}/trajectory/"
                                    trajectory_dir = experiments_dir / trajectory_path
                                    if trajectory_dir.exists() and trajectory_dir.is_dir():
                                        image_files = [
                                            f for f in os.listdir(trajectory_dir)
                                            if f.lower().endswith((".png", ".jpg", ".jpeg", ".webp", ".gif"))
                                        ]

                                        def _sort_key(name: str) -> Any:
                                            nums = re.findall(r"\d+", name)
                                            return int(nums[0]) if nums else name

                                        image_files.sort(key=_sort_key)
                                        trajectory_images = [
                                            f"{trajectory_path}{fname}" for fname in image_files
                                        ]

                                    result_json_path = experiments_dir / trajectories_rel_root / task_id / "result.json"
                                    if result_json_path.exists():
                                        try:
                                            with open(result_json_path, "r", encoding="utf-8") as rjf:
                                                rj = json.load(rjf)
                                            actions = rj.get("action_history", []) or []
                                            metrics_block = rj.get("metrics") or {}
                                            fallback_metrics = extract_task_metrics(metrics_block)
                                            config_block = rj.get("config") or {}
                                            fallback_config = normalize_config(config_block)
                                            fallback_model = rj.get("model_id")
                                            fallback_browser = rj.get("browser_id")
                                        except (OSError, ValueError, json.JSONDecodeError) as exc:
                                            logger.warning(
                                                "Failed to read result JSON %s: %s",
                                                result_json_path,
                                                exc,
                                            )
                                            actions = []

                                artifact = {
                                    "trajectory_path": trajectory_path,
                                    "trajectory_images": trajectory_images,
                                    "actions": actions,
                                    "metrics": fallback_metrics,
                                    "config": fallback_config,
                                    "model_id": fallback_model.strip() if isinstance(fallback_model, str) and fallback_model.strip() else None,
                                    "browser_id": fallback_browser.strip() if isinstance(fallback_browser, str) and fallback_browser.strip() else None,
                                }
                                task_artifacts_cache[task_id] = artifact
                                return artifact

                            def process_eval_record(obj: Dict[str, Any]):
                                nonlocal agent_model_id, agent_browser_id, agent_config_info
                                nonlocal total_tasks, success_count, failure_count
                                nonlocal steps_sum, steps_count, e2e_sum, e2e_count
                                nonlocal ttft_sum, ttft_count, success_tokens_sum, success_tokens_count
                                nonlocal success_cost_sum, success_cost_count, score_sum, score_count
                                if not isinstance(obj, dict):
                                    return

                                predicted = obj.get("predicted_label")
                                if predicted is None and isinstance(obj.get("evaluation_details"), dict):
                                    predicted = obj["evaluation_details"].get("predicted_label")
                                status = "success" if str(predicted) == "1" else "failure"

                                def pick_identity(current: Optional[str], candidate: Any) -> Optional[str]:
                                    if current:
                                        return current
                                    if isinstance(candidate, str):
                                        trimmed = candidate.strip()
                                        if trimmed:
                                            return trimmed
                                    return current

                                agent_model_id = pick_identity(agent_model_id, obj.get("model_id"))
                                agent_browser_id = pick_identity(agent_browser_id, obj.get("browser_id"))
                                ev = obj.get("evaluation_details") or {}
                                if isinstance(ev, dict):
                                    agent_model_id = pick_identity(agent_model_id, ev.get("model_id"))
                                    agent_browser_id = pick_identity(agent_browser_id, ev.get("browser_id"))

                                fc: Optional[str] = None
                                if status == "failure":
                                    if isinstance(obj.get("failure_category"), str):
                                        fc = obj["failure_category"]
                                    elif isinstance(ev, dict):
                                        if isinstance(ev.get("failure_category"), str):
                                            fc = ev["failure_category"]
                                        else:
                                            fc = (ev.get("failure_classification", {}) or {}).get("category")
                                    if not fc:
                                        fc = "Uncategorized"
                                else:
                                    fc = "Success"

                                task_id = str(obj.get("task_id", ""))
                                task_desc = obj.get("task", "")
                                eval_resp = (
                                    ev.get("grader_response")
                                    or ev.get("evaluator_response")
                                    or ev.get("response")
                                    or ""
                                )
                                failure_classification = ev.get("failure_classification", {}) or {}
                                classification_reasoning = (
                                    failure_classification.get("reasoning")
                                    or ev.get("grader_reasoning")
                                    or ""
                                )

                                artifacts = get_task_artifacts(task_id)
                                trajectory_path = artifacts["trajectory_path"]
                                trajectory_images = artifacts["trajectory_images"]
                                fallback_actions = artifacts["actions"]
                                fallback_metrics = artifacts["metrics"] or {}
                                fallback_config = artifacts["config"] or {}
                                agent_model_id = pick_identity(agent_model_id, artifacts.get("model_id"))
                                agent_browser_id = pick_identity(agent_browser_id, artifacts.get("browser_id"))

                                normalized_record_metrics = extract_task_metrics(obj.get("metrics") or {})
                                task_metrics = {**fallback_metrics, **normalized_record_metrics}

                                record_config = normalize_config(obj.get("config"))
                                merged_config = {**fallback_config, **record_config}
                                for key, value in merged_config.items():
                                    agent_config_info[key] = value

                                timeout_candidate = parse_timeout_seconds(
                                    merged_config.get("timeout_seconds") or merged_config.get("timeout")
                                )
                                if timeout_candidate is None:
                                    timeout_candidate = parse_timeout_seconds(agent_config_info.get("timeout_seconds"))
                                if timeout_candidate is None:
                                    timeout_candidate = DEFAULT_TIMEOUT_SECONDS
                                task_metrics.setdefault("timeout_seconds", timeout_candidate)
                                agent_config_info["timeout_seconds"] = timeout_candidate

                                action_history = obj.get("action_history") or fallback_actions or []

                                normalized_metrics = task_metrics

                                rec = {
                                    "task_id": task_id,
                                    "task": task_desc,
                                    "failure_category": fc if status == "failure" else None,
                                    "status": status,
                                    "evaluation_response": eval_resp,
                                    "classification_reasoning": classification_reasoning,
                                    "trajectory_path": trajectory_path,
                                    "trajectory_images": trajectory_images,
                                    "action_history": action_history,
                                    "metrics": normalized_metrics,
                                    "evaluation_details": ev,
                                }

                                if status == "failure":
                                    failure_details.setdefault(fc, []).append(rec)
                                    failure_counts[fc] = failure_counts.get(fc, 0) + 1
                                else:
                                    success_details.append(rec)

                                total_tasks += 1
                                if status == "success":
                                    success_count += 1
                                else:
                                    failure_count += 1

                                if "steps" in normalized_metrics:
                                    steps_sum += float(normalized_metrics["steps"])
                                    steps_count += 1
                                if "e2e_seconds" in normalized_metrics:
                                    e2e_sum += float(normalized_metrics["e2e_seconds"])
                                    e2e_count += 1
                                if "ttft_seconds" in normalized_metrics:
                                    ttft_sum += float(normalized_metrics["ttft_seconds"])
                                    ttft_count += 1
                                if status == "success":
                                    if "total_tokens" in normalized_metrics:
                                        success_tokens_sum += float(normalized_metrics["total_tokens"])
                                        success_tokens_count += 1
                                    if "total_cost" in normalized_metrics:
                                        success_cost_sum += float(normalized_metrics["total_cost"])
                                        success_cost_count += 1

                                score_candidate = None
                                def _extract_score(container: Any) -> Optional[float]:
                                    if isinstance(container, dict):
                                        raw = container.get("score")
                                        if isinstance(raw, (int, float)):
                                            return float(raw)
                                    return None
                                score_candidate = _extract_score(ev)
                                if score_candidate is None and isinstance(ev, dict):
                                    nested_details = ev.get("evaluation_details")
                                    score_candidate = _extract_score(nested_details)
                                if score_candidate is None:
                                    score_candidate = _extract_score(obj)
                                if score_candidate is None and isinstance(obj.get("metrics"), dict):
                                    score_candidate = _extract_score(obj["metrics"])
                                if score_candidate is not None:
                                    score_sum += score_candidate
                                    score_count += 1

                            parsed_from_lines = False
                            if results_file_path and results_file_path.exists():
                                try:
                                    with normalized_results_file(results_file_path) as prepared_file:
                                        with open(prepared_file, "r", encoding="utf-8") as rf:
                                            for line in rf:
                                                line = line.strip()
                                                if not line:
                                                    continue
                                                try:
                                                    obj = json.loads(line)
                                                except json.JSONDecodeError:
                                                    continue
                                                process_eval_record(obj)
                                                parsed_from_lines = True

                                    if not parsed_from_lines:
                                        with open(results_file_path, "r", encoding="utf-8") as rf:
                                            content = rf.read()

                                        obj_strings = re.findall(r"\{[\s\S]*?\}(?=\s*\{|\s*\Z)", content)

                                        for obj_str in obj_strings:
                                            try:
                                                obj = json.loads(obj_str)
                                            except json.JSONDecodeError:
                                                continue
                                            process_eval_record(obj)

                                except (OSError, ValueError, json.JSONDecodeError) as exc:
                                    logger.warning(
                                        "   [WARNING] Failed to parse %s: %s",
                                        results_file_path,
                                        exc,
                                    )

                            if total_tasks == 0:
                                continue

                            success_rate = (success_count / total_tasks) * 100 if total_tasks else 0
                            avg_steps = steps_sum / steps_count if steps_count else 0
                            avg_e2e_time = e2e_sum / e2e_count if e2e_count else 0
                            avg_ttft = ttft_sum / ttft_count if ttft_count else 0
                            avg_tokens = success_tokens_sum / success_tokens_count if success_tokens_count else 0
                            avg_cost = success_cost_sum / success_cost_count if success_cost_count else None
                            avg_score = score_sum / score_count if score_count else None

                            config_defaults = get_agent_default_config(agent_name)

                            # Fallbacks when the run artifacts did not record
                            # model_id / browser_id (e.g. Agent-TARS writes empty
                            # strings). The on-disk layout is
                            # <benchmark>/<split>/<agent>/<model>/<timestamp>/,
                            # so model_dir.name is a reliable directory-based
                            # fallback for the model. For browser we also look
                            # into the aggregated config (BROWSER_ID / browser_id).
                            def _clean(value: Any) -> Optional[str]:
                                if isinstance(value, str):
                                    trimmed = value.strip()
                                    if trimmed:
                                        return trimmed
                                return None

                            model_dir_fallback = _clean(model_dir.name)
                            config_model_fallback = _clean(config_defaults.get("model")) \
                                if config_defaults.get("model") != "Unknown" else None
                            config_browser_fallback = _clean(config_defaults.get("browser")) \
                                if config_defaults.get("browser") != "Unknown" else None
                            agent_config_browser_fallback = (
                                _clean(agent_config_info.get("browser_id"))
                                or _clean(agent_config_info.get("BROWSER_ID"))
                            )
                            agent_config_model_fallback = (
                                _clean(agent_config_info.get("model_id"))
                                or _clean(agent_config_info.get("MODEL_ID"))
                            )

                            model_name = (
                                agent_model_id
                                or agent_config_model_fallback
                                or model_dir_fallback
                                or config_model_fallback
                                or "Unknown"
                            )
                            browser_name = (
                                agent_browser_id
                                or agent_config_browser_fallback
                                or config_browser_fallback
                                or "Unknown"
                            )

                            metrics = {
                                "agent": agent_name,
                                "model": model_name,
                                "browser": browser_name,
                                "success_rate": success_rate,
                                "avg_steps": avg_steps,
                                "avg_e2e_time": avg_e2e_time,
                                "avg_ttft": avg_ttft,
                                "avg_tokens": avg_tokens,
                                "avg_cost": avg_cost,
                                "total_tasks": total_tasks,
                                "successful_tasks": success_count,
                                "failed_tasks": failure_count,
                                "eval_date": eval_date,
                                "avg_score": avg_score,
                                "failure_categories": failure_counts or {cat: len(details) for cat, details in failure_details.items()},
                                "failure_details": failure_details,
                                "success_details": success_details,
                                "benchmark": benchmark_name,
                                "version": version_name,  # Add version field
                                "split": split_name,
                            }

                            if results_rel_path is not None:
                                metrics["results_rel_path"] = results_rel_path.as_posix()
                            if trajectories_rel_root is not None:
                                metrics["trajectories_rel_root"] = trajectories_rel_root.as_posix()
                            if agent_config_info:
                                metrics["config"] = agent_config_info

                            leaderboard_data.append(metrics)

                except (OSError, ValueError, TypeError) as exc:
                    logger.error("   [FAILED] Error processing %s: %s", agent_name, exc)
                    continue

        if leaderboard_data:
            all_data[benchmark_name] = leaderboard_data
            logger.info(f"   [STATS] {benchmark_name}: Collected data from {len(leaderboard_data)} Agent(s)")

    return all_data

def clean_for_json(data: Any, max_string_length: int = 1000) -> Any:
    """Clean data for safe embedding in JSON.

    - Truncate overly long strings
    - Remove or simplify HTML content
    - Ensure all strings can be safely embedded in JSON
    """
    if isinstance(data, dict):
        return {k: clean_for_json(v, max_string_length) for k, v in data.items()}
    elif isinstance(data, list):
        # Keep only first 100 items for lists to avoid oversize data
        return [clean_for_json(item, max_string_length) for item in data[:100]]
    elif isinstance(data, str):
        # Remove HTML tags
        if '<html' in data.lower() or '<div' in data.lower():
            data = '[HTML Content]'
        # Truncate long strings
        if len(data) > max_string_length:
            data = data[:max_string_length] + '...'
        return data
    else:
        return data

def generate_html(all_benchmarks_data: Dict[str, List[Dict[str, Any]]], output_path: Path):
    """Generate HTML leaderboard supporting multiple benchmarks."""

    # Generate table data for each benchmark and clean data
    benchmarks_json = {}
    for benchmark_name, leaderboard_data in all_benchmarks_data.items():
        sorted_data = sorted(leaderboard_data, key=lambda x: x["success_rate"], reverse=True)
        # Clean data for each agent
        cleaned_data = []
        for agent_data in sorted_data:
            # Create copy and clean
            cleaned_agent = clean_for_json(agent_data)
            cleaned_data.append(cleaned_agent)
        benchmarks_json[benchmark_name] = cleaned_data

    # Load HTML template from external file
    template_path = REPO_ROOT / "browseruse_bench" / "leaderboard" / "templates" / "leaderboard_template.html"
    if not template_path.exists():
        raise FileNotFoundError(f"Template file not found: {template_path}")

    html_template = template_path.read_text(encoding='utf-8')

    # Fill template - simple string replacement to avoid format() conflict with JS curlies.
    # ensure_ascii=True keeps the embedded JSON parser-safe across special chars.
    # The Benchmark column is now driven by the in-page filter dropdown built
    # client-side from `benchmarksData`, so no toolbar option list is emitted.
    benchmarks_json_str = json.dumps(benchmarks_json, ensure_ascii=True, indent=4)

    html_content = html_template.replace(
        "{{ BENCHMARKS_JSON }}", benchmarks_json_str
    ).replace(
        "{{TIMESTAMP}}", datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    )

    # Write to file
    output_path.write_text(html_content, encoding='utf-8')
    logger.info(f"[SUCCESS] Leaderboard generated: {output_path}")


def generate_leaderboard(output_name: str, output_dir: Optional[Path]) -> Path:
    logger.info("Starting collection of all Benchmark data...")

    default_timeout_seconds = get_default_timeout_seconds()
    all_benchmarks_data = collect_all_benchmarks_data(default_timeout_seconds)

    if not all_benchmarks_data:
        raise LeaderboardError("No assessment results found")

    # Determine output path
    if output_dir is None:
        output_dir = REPO_ROOT / "experiments"

    output_path = output_dir / output_name

    # Generate HTML
    generate_html(all_benchmarks_data, output_path)

    logger.info("Done! Collected data from %s Benchmark(s)", len(all_benchmarks_data))
    logger.info("   Please open in browser:")
    logger.info("   file://%s", output_path)

    return output_path


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Generate Leaderboard HTML Report")
    parser.add_argument("--output-name", default="leaderboard.html", help="Output filename")
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Output directory (default: experiments/)",
    )

    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code) if isinstance(exc.code, int) else 1

    try:
        output_dir = Path(args.output_dir) if args.output_dir else None
        generate_leaderboard(args.output_name, output_dir)
    except (LeaderboardError, FileNotFoundError, OSError, ValueError) as exc:
        logger.error("[FAILED] %s", exc)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Lexmount-Browser core evaluation logic"""
from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any

try:
    from PIL import Image
except ImportError:
    Image = None

from browseruse_bench.schemas.prompt import PromptRef
from browseruse_bench.utils import (
    encode_image,
    load_eval_config,
    load_prompt,
    make_template_prompt,
    make_text_prompt,
)

logger = logging.getLogger(__name__)

# Load eval configuration (returns {} if file missing — all .get() have fallbacks)
_EVAL_CFG = load_eval_config("LexBench-Browser")

_PROMPT_DIR = _EVAL_CFG.get("prompt_dir", "browseruse_bench/eval/lexbench_browser/prompts")


def detect_language(task_data: dict[str, Any]) -> str:
    """Detect language of the task.

    Detection strategy:
    1. If task_data has an explicit 'language' field, use it directly.
    2. If query contains Chinese characters -> use Chinese.
    3. If query is mainly English (English chars > 50%) -> use English.
    4. Default to Chinese (project default language).

    Args:
        task_data: Task configuration data

    Returns:
        'en' for English, 'zh' for Chinese (default)
    """
    # 1. UI language override from runtime env (if provided)
    env_lang = (
        os.getenv("KB_UI_LANGUAGE")
        or os.getenv("UI_LANGUAGE")
        or os.getenv("EVAL_OUTPUT_LANGUAGE")
        or ""
    ).strip().lower()
    if env_lang.startswith("en"):
        return "en"
    if env_lang.startswith("zh"):
        return "zh"
    if env_lang in ("en", "zh"):
        return env_lang

    # 2. Explicit language field takes next priority
    explicit_lang = task_data.get("language", "")
    if explicit_lang in ("en", "zh"):
        return explicit_lang

    query = task_data.get("query", "")

    # 3. If contains Chinese characters, use Chinese directly
    if re.search(r'[\u4e00-\u9fff]', query):
        return 'zh'

    # 4. Check if mainly English
    english_char_count = len(re.findall(r'[a-zA-Z]', query))
    total_chars = len(query.strip())

    if total_chars > 0 and english_char_count / total_chars > 0.5 and re.search(r'[a-zA-Z]{2,}', query):
        return 'en'

    # 5. Default to Chinese
    return 'zh'


def get_evaluation_template(language: str = 'zh') -> tuple[str, PromptRef]:
    """Get standard evaluation template.

    Returns:
        ``(template_content, PromptRef)``
    """
    suffix = "en" if language == "en" else "zh"
    return load_prompt(f"{_PROMPT_DIR}/eval_stepwise_{suffix}.txt")


def get_reverse_evaluation_template(language: str = 'zh') -> tuple[str, PromptRef]:
    """Get reverse evaluation template for dark industry tasks.

    Returns:
        ``(template_content, PromptRef)``
    """
    suffix = "en" if language == "en" else "zh"
    return load_prompt(f"{_PROMPT_DIR}/eval_reverse_stepwise_{suffix}.txt")


def get_final_result_evaluation_template(language: str = 'zh') -> tuple[str, PromptRef]:
    """Get final result evaluation template.

    Returns:
        ``(template_content, PromptRef)``
    """
    suffix = "en" if language == "en" else "zh"
    return load_prompt(f"{_PROMPT_DIR}/eval_final_{suffix}.txt")


def get_reverse_final_result_evaluation_template(language: str = 'zh') -> tuple[str, PromptRef]:
    """Get reverse final result evaluation template for dark industry tasks.

    Returns:
        ``(template_content, PromptRef)``
    """
    suffix = "en" if language == "en" else "zh"
    return load_prompt(f"{_PROMPT_DIR}/eval_reverse_final_{suffix}.txt")


def _format_penalty_number(value: float) -> str:
    """Format penalty number without trailing .0 when possible."""
    if value.is_integer():
        return str(int(value))
    return str(value)


def _format_penalty_value(value: Any, language: str) -> str:
    """Format penalty value for prompt display.

    Returns a string with negative sign, e.g. "-5" or "-至少3到最多45".
    """
    try:
        return f"-{_format_penalty_number(abs(float(value)))}"
    except (TypeError, ValueError):
        if isinstance(value, str) and "-" in value:
            parts = [part.strip() for part in value.split("-") if part.strip()]
            if len(parts) >= 2:
                try:
                    low = abs(float(parts[0]))
                    high = abs(float(parts[-1]))
                    if low > high:
                        low, high = high, low
                    low_text = _format_penalty_number(low)
                    high_text = _format_penalty_number(high)
                    if language == "en":
                        return f"-min {low_text} to max {high_text}"
                    return f"-最少{low_text}到最多{high_text}"
                except ValueError:
                    pass
        return "-0"


def build_evaluation_prompt(task_data: dict[str, Any], agent_result: dict[str, Any],
                           screenshot_count: int = 0, eval_strategy: str = "stepwise") -> tuple:
    """Build evaluation prompt from task data and agent result

    Args:
        task_data: Task configuration data
        agent_result: Agent execution result
        screenshot_count: Number of screenshots used
        eval_strategy: Evaluation strategy ("stepwise" or "final")

    Returns:
        Tuple of (formatted_prompt, prompt_params, template_content, template_ref)
        where template_ref is the PromptRef of the template file used.
    """

    reference = task_data.get("reference_answer", {})

    # Detect language
    language = detect_language(task_data)

    # Check if this is a reverse scoring task (dark industry)
    scoring = reference.get("scoring", {})
    scoring_type = scoring.get("scoring_type", "normal")
    is_reverse_scoring = scoring_type == "reverse"

    # Format reference steps
    steps = reference.get("steps", [])
    reference_steps = "\n".join([f"{i+1}. {step}" for i, step in enumerate(steps)])

    # Format key points
    key_points_list = reference.get("key_points", [])
    key_points = "\n".join([f"- {point}" for point in key_points_list])

    # Format common mistakes
    mistakes = reference.get("common_mistakes", [])
    common_mistakes = "\n".join([f"- {mistake}" for mistake in mistakes])

    # Get agent answer
    agent_answer = agent_result.get("answer", agent_result.get("response", "No answer provided"))

    # Get metrics
    metrics = agent_result.get("metrics", {})
    steps_count = metrics.get("steps", "unk")
    execution_time = metrics.get("end_to_end_ms", "unk")

    # Format deductions
    deductions_list = scoring.get("deductions", [])
    formatted_deductions = []
    for ded in deductions_list:
        reason = ded.get('reason', ded.get('name', 'Unknown deduction'))
        penalty_value = ded.get('penalty', ded.get('score', 0))
        penalty_text = _format_penalty_value(penalty_value, language)
        formatted_deductions.append(f"- {reason}: {penalty_text} points")
    deductions = "\n".join(formatted_deductions)


    # Distinguish between two evaluation methods:
    # A: Forward scoring - for tasks that should be completed, points awarded for each correct step
    # B: Reverse scoring - for tasks that should NOT be completed, points deducted for each executed step
    # Also distinguish between evaluation strategies:
    # - stepwise: Step-by-step evaluation using all screenshots
    # - final: Final result evaluation using only the last screenshot
    if is_reverse_scoring:
        # Use reverse evaluation template for dark industry tasks
        if eval_strategy == "final":
            template, template_ref = get_reverse_final_result_evaluation_template(language)
        else:
            template, template_ref = get_reverse_evaluation_template(language)

        prompt_kwargs = {
            "task_description": task_data.get("query", ""),
            "target_website": task_data.get("target_website", "unk"),
            "task_type": task_data.get("task_type", "unk"),
            "domain": task_data.get("domain", "unk"),
            "risk_level": task_data.get("risk_level", "unk"),
            "correct_behavior": reference.get("correct_behavior", "Refuse to execute malicious request"),
            "reference_steps": reference_steps,
            "key_points": key_points,
            "common_mistakes": common_mistakes,
            "deductions": deductions,
            "agent_answer": agent_answer,
            "steps_count": steps_count,
            "execution_time": execution_time,
            "screenshot_count": screenshot_count,
        }
        return template.format(**prompt_kwargs), prompt_kwargs, template, template_ref
    else:
        # Use normal evaluation template
        if eval_strategy == "final":
            template, template_ref = get_final_result_evaluation_template(language)
        else:
            template, template_ref = get_evaluation_template(language)

        # Format scoring items
        items = scoring.get("items", [])
        scoring_items = "\n".join([
            f"{i+1}. {item['name']} ({item['score']}): {item['description']}"
            for i, item in enumerate(items)
        ])

        prompt_kwargs = {
            "task_description": task_data.get("query", ""),
            "target_website": task_data.get("target_website", "unk"),
            "task_type": task_data.get("task_type", "unk"),
            "instruction_complexity": task_data.get("instruction_complexity", "unk"),
            "environment_complexity": task_data.get("environment_complexity", "unk"),
            "reference_steps": reference_steps,
            "key_points": key_points,
            "common_mistakes": common_mistakes,
            "scoring_items": scoring_items,
            "deductions": deductions,
            "agent_answer": agent_answer,
            "steps_count": steps_count,
            "execution_time": execution_time,
            "screenshot_count": screenshot_count,
        }
        return template.format(**prompt_kwargs), prompt_kwargs, template, template_ref


def evaluate_task(
    task_data: dict[str, Any],
    agent_result: dict[str, Any],
    screenshot_paths: list[Path],
    model,
    image_scale_factor: float = 1.0,
    max_screenshots: int | None = None,
    eval_strategy: str = "stepwise",
    api_max_images: int | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> dict[str, Any]:
    """Evaluate task with screenshots using LLM

    This function only handles the evaluation logic (prompt building, LLM call).
    It does NOT make decisions about success/failure or construct final output format.

    Args:
        task_data: Task configuration data
        agent_result: Agent execution result
        screenshot_paths: List of screenshot file paths
        model: Evaluation model
        image_scale_factor: Image scaling factor (0.0 < scale <= 1.0)
        max_screenshots: Maximum number of screenshots to use (None = no limit)
        eval_strategy: Evaluation strategy ("stepwise" or "final")
            - stepwise: Use all screenshots for step-by-step evaluation
            - final: Use only the last screenshot for final result evaluation
        api_max_images: Maximum images the API accepts per request (None = use config/default 50)

    Returns:
        Dict containing evaluation response:
            - prompt: Evaluation prompt used
            - response: Raw LLM evaluation response
            - screenshot_count: Number of screenshots used
            - original_screenshot_count: Original number of screenshots before sampling
            - eval_strategy: The evaluation strategy used
            - system_prompt: TextPrompt for the system prompt
            - user_prompt: TemplatePrompt for the user prompt
    """

    if Image is None:
        raise ImportError("PIL is required for evaluation. Install with: pip install Pillow")

    # Record original count
    original_count = len(screenshot_paths)

    # Select screenshots based on evaluation strategy
    if eval_strategy == "final":
        # For final result evaluation, use only the last screenshot
        if screenshot_paths:
            screenshot_paths = [screenshot_paths[-1]]
            logger.info(
                f"   Using final screenshot (1/{original_count}) for final result evaluation (no compression)"
            )
    else:
        # For stepwise evaluation, sample if too many
        _cfg_max_images: int = _EVAL_CFG.get("api_max_images", 50)
        resolved_max_images = api_max_images if api_max_images is not None else _cfg_max_images
        effective_max = min(max_screenshots, resolved_max_images) if max_screenshots is not None else resolved_max_images

        if len(screenshot_paths) > effective_max:
            # Sample key screenshots: first, last, and evenly spaced middle ones
            indices = [0] + [int(i * (len(screenshot_paths) - 1) / (effective_max - 1))
                            for i in range(1, effective_max)]
            screenshot_paths = [screenshot_paths[i] for i in indices]
            logger.info(
                f"   Sampled {len(screenshot_paths)}/{original_count} screenshots for stepwise evaluation (API limit: {resolved_max_images})"
            )

    # Build prompt (now returns 4 values including template content and ref)
    prompt, prompt_params, template_content, template_ref = build_evaluation_prompt(
        task_data,
        agent_result,
        screenshot_count=len(screenshot_paths),
        eval_strategy=eval_strategy
    )

    # Detect language for system message — loaded from externalized prompt files
    language = detect_language(task_data)
    suffix = "en" if language == "en" else "zh"
    system_message, system_prompt_ref = load_prompt(
        f"{_PROMPT_DIR}/system_{suffix}.txt"
    )

    # Build PromptSnapshot objects
    system_prompt_snapshot = make_text_prompt(system_message, system_prompt_ref)
    user_prompt_snapshot = make_template_prompt(
        template_content,
        template_ref,
        {k: str(v) for k, v in prompt_params.items()},
    )

    # Prepare messages with images
    messages = [
        {
            "role": "system",
            "content": system_message
        },
        {
            "role": "user",
            "content": [
                {"type": "text", "text": prompt}
            ]
        }
    ]

    # Add screenshots
    # For final strategy, use original quality (no compression) since only one screenshot is used
    # For stepwise strategy, apply compression to reduce token usage
    actual_scale_factor = 1.0 if eval_strategy == "final" else image_scale_factor

    for _i, screenshot_path in enumerate(screenshot_paths):
        try:
            image = Image.open(screenshot_path)
            base64_image = encode_image(image, scale_factor=actual_scale_factor)
            messages[1]["content"].append({
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/jpeg;base64,{base64_image}",
                    "detail": _EVAL_CFG.get("detail", "high"),
                }
            })
        except OSError as e:
            logger.warning(f"Warning: Failed to load screenshot {screenshot_path}: {e}")

    # Generate evaluation
    _temperature = temperature if temperature is not None else _EVAL_CFG.get("temperature", 0.3)
    response = model.generate(
        messages,
        max_tokens=max_tokens if max_tokens is not None else _EVAL_CFG.get("max_tokens", 2048),
        temperature=_temperature,
    )

    # Collect token usage for cost calculation
    usage = getattr(model, "last_usage", None)

    return {
        "prompt": prompt,
        "response": response,
        "screenshot_count": len(screenshot_paths),
        "original_screenshot_count": original_count,
        "eval_strategy": eval_strategy,
        "image_scale_factor": actual_scale_factor,
        "usage": usage,
        "system_prompt": system_prompt_snapshot,
        "user_prompt": user_prompt_snapshot,
    }

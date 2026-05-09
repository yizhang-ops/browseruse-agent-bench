"""WebVoyager screenshot-based binary grader (SUCCESS/NOT SUCCESS judgment via GPT-4V)."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from PIL import Image

from browseruse_bench.utils import encode_image

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "As an evaluator, you will be presented with three primary components to assist you in your role:\n\n"
    "1. Web Task Instruction: This is a clear and specific directive provided in natural language, "
    "detailing the online activity to be carried out. These requirements may include conducting searches, "
    "verifying information, comparing prices, checking availability, or any other action relevant to the "
    "specified web service (such as Amazon, Apple, ArXiv, BBC News, Booking etc).\n\n"
    "2. Result Screenshots: This is a visual representation of the screen showing the result or "
    "intermediate state of performing a web task. It serves as visual proof of the actions taken in "
    "response to the instruction.\n\n"
    "3. Result Response: This is a textual response obtained after the execution of the web task. "
    "It serves as textual result in response to the instruction.\n\n"
    "-- You DO NOT NEED to interact with web pages or perform actions such as booking flights or "
    "conducting searches on websites.\n"
    "-- You SHOULD NOT make assumptions based on information not presented in the screenshot when "
    "comparing it to the instructions.\n"
    "-- Your primary responsibility is to conduct a thorough assessment of the web task instruction "
    "against the outcome depicted in the screenshot and in the response, evaluating whether the actions "
    "taken align with the given instructions.\n"
    "-- NOTE that the instruction may involve more than one task, for example, locating the garage and "
    "summarizing the review. Failing to complete either task, such as not providing a summary, should be "
    "considered unsuccessful.\n"
    "-- NOTE that the screenshot is authentic, but the response provided by LLM is generated at the end "
    "of web browsing, and there may be discrepancies between the text and the screenshots.\n"
    "-- Note the difference: 1) Result response may contradict the screenshot, then the content of the "
    "screenshot prevails, 2) The content in the Result response is not mentioned on the screenshot, "
    "choose to believe the content.\n\n"
    "You should elaborate on how you arrived at your final evaluation and then provide a definitive "
    "verdict on whether the task has been successfully accomplished, either as 'SUCCESS' or 'NOT SUCCESS'."
)

_USER_TEMPLATE = (
    "TASK: {task}\n"
    "Result Response: {answer}\n"
    "{num} screenshots at the end: "
)


def _parse_success(response: str) -> Optional[bool]:
    """Return True for SUCCESS, False for NOT SUCCESS, None if verdict is unclear."""
    if "NOT SUCCESS" in response:
        return False
    if "SUCCESS" in response:
        return True
    return None


def grade_screenshot(
    task: str,
    answer: str,
    screenshot_paths: List[Path],
    model: Any,
    image_scale_factor: float = 1.0,
    temperature: float = 0.0,
    max_tokens: int = 1024,
) -> Dict[str, Any]:
    """Judge whether the agent completed the task, using screenshots + GPT-4V.

    Args:
        task: The task description given to the agent.
        answer: The agent's final answer/response.
        screenshot_paths: Ordered list of screenshot paths from the trajectory.
        model: EvaluationModel instance (must support .generate() and .last_usage).
        image_scale_factor: Scale factor for images before encoding.
        temperature: Sampling temperature for the model.
        max_tokens: Max output tokens.

    Returns:
        Dict with keys: is_correct, response, reasoning, usage, system_prompt,
        user_prompt.
    """
    num_screenshots = len(screenshot_paths)
    user_text = _USER_TEMPLATE.format(
        task=task,
        answer=answer or "No answer provided.",
        num=num_screenshots,
    )

    messages: List[Dict[str, Any]] = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": [{"type": "text", "text": user_text}]},
    ]

    for path in screenshot_paths:
        try:
            img = Image.open(path)
            b64 = encode_image(img, scale_factor=image_scale_factor)
            messages[1]["content"].append({
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{b64}", "detail": "high"},
            })
        except OSError as exc:
            logger.warning("Failed to load screenshot %s: %s", path, exc)

    messages[1]["content"].append({"type": "text", "text": "Your verdict:\n"})

    response = model.generate(messages, max_tokens=max_tokens, temperature=temperature)
    usage = getattr(model, "last_usage", None)
    verdict = _parse_success(response)
    is_correct = bool(verdict)
    if verdict is None:
        logger.warning("Grader response contains neither SUCCESS nor NOT SUCCESS: %s", response[:200])

    reasoning = response.strip()

    return {
        "is_correct": is_correct,
        "response": response,
        "reasoning": reasoning,
        "usage": usage,
        "system_prompt": _SYSTEM_PROMPT,
        "user_prompt": user_text,
    }

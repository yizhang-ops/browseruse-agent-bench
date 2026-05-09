from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


def load_jsonl(file_path: Path) -> List[Dict[str, Any]]:
    """Load JSONL file.

    Args:
        file_path: Path to JSONL file.

    Returns:
        List[Dict[str, Any]]: List of JSON objects.
    """
    data: List[Dict[str, Any]] = []
    with open(file_path, "r", encoding="utf-8") as f:
        for line_num, line in enumerate(f, 1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                obj = json.loads(stripped)
            except json.JSONDecodeError as exc:
                logger.warning("Failed to parse line %s in %s: %s", line_num, file_path, exc)
                continue
            if isinstance(obj, dict):
                data.append(obj)
            else:
                logger.warning(
                    "Skipping non-dict JSONL record at line %s in %s: %s",
                    line_num,
                    file_path,
                    type(obj).__name__,
                )
    return data


def load_task_file(file_path: Path) -> List[Dict[str, Any]]:
    """Load tasks from JSON or JSONL file.

    Handles different formats:
    - .jsonl: Line-separated JSON objects
    - .json: List of objects or Dict with "tasks" key

    Args:
        file_path: Path to the task file.

    Returns:
        List[Dict[str, Any]]: List of task dictionaries.

    Raises:
        FileNotFoundError: If file does not exist.
        ValueError: If file extension is unsupported or JSON structure is invalid.
    """
    if not file_path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    if file_path.suffix == ".jsonl":
        return load_jsonl(file_path)

    if file_path.suffix == ".json":
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]

        if isinstance(data, dict):
            tasks = data.get("tasks", [])
            if not tasks:
                logger.warning("JSON is a dict but has no 'tasks' field (or it is empty): %s", file_path)
                return []
            if not isinstance(tasks, list):
                raise ValueError(
                    f"Unsupported JSON format in {file_path}. "
                    "Must be a list or a dict with 'tasks' as a list."
                )
            return [item for item in tasks if isinstance(item, dict)]

        raise ValueError(
            f"Unsupported JSON format in {file_path}. "
            "Must be a list or a dict with 'tasks' field."
        )

    raise ValueError(f"Unsupported file extension: {file_path.suffix}")


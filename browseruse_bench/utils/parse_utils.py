from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, List, Optional

logger = logging.getLogger(__name__)


def safe_int(value: Any, default: int = 0) -> int:
    """Safely convert value to int."""
    try:
        if value is None:
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def load_json_records(file_path: Path) -> List[Any]:
    """Load a JSON array or JSONL file into a list."""
    try:
        content = file_path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError) as exc:
        logger.warning("Failed to read %s: %s", file_path, exc)
        return []

    if not content:
        return []

    parsed: Any
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        parsed = None

    if parsed is None:
        records: List[Any] = []
        for line in content.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    elif isinstance(parsed, list):
        records = parsed
    else:
        records = [parsed]

    if records and isinstance(records[0], str):
        try:
            records = [json.loads(item) for item in records if isinstance(item, str)]
        except json.JSONDecodeError:
            logger.warning("Failed to parse JSON string list in %s", file_path)

    return records


def find_key_recursive(obj: Any, key: str) -> Optional[Any]:
    """Recursively find a key in a nested dictionary/list structure."""
    if isinstance(obj, dict):
        if key in obj:
            return obj[key]
        for _, value in obj.items():
            found = find_key_recursive(value, key)
            if found is not None:
                return found
    elif isinstance(obj, list):
        for item in obj:
            found = find_key_recursive(item, key)
            if found is not None:
                return found
    return None

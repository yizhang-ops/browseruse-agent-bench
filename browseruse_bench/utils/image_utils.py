from __future__ import annotations

import base64
import binascii
import logging
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def strip_base64_prefix(data: Optional[str]) -> Optional[str]:
    """Remove base64 header if present."""
    if not data or not isinstance(data, str):
        return None
    if "base64," in data:
        return data.split("base64,", 1)[1]
    return data


def extract_base64_from_content_item(content_item: Dict[str, Any]) -> Optional[str]:
    """Extract base64 data from a content item."""
    item_type = content_item.get("type")
    if item_type == "image_url":
        image_url = content_item.get("image_url", {})
        if not isinstance(image_url, dict):
            return None
        return strip_base64_prefix(image_url.get("url", ""))
    if item_type == "image":
        data = content_item.get("data", "")
        if not isinstance(data, str):
            return None
        return strip_base64_prefix(data)
    return None


def decode_base64_to_file(data: str, output_path: Path) -> bool:
    """Decode base64 payload and write to file."""
    if not data or not isinstance(data, str):
        return False
    try:
        image_bytes = base64.b64decode(data)
    except (binascii.Error, ValueError) as exc:
        logger.error("Failed to decode base64 for %s: %s", output_path.name, exc)
        return False
    try:
        with open(output_path, "wb") as f:
            f.write(image_bytes)
    except OSError as exc:
        logger.error("Failed to write %s: %s", output_path, exc)
        return False
    return True

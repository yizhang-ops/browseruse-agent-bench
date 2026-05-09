"""Prompt loading utilities for externalized eval prompts."""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path

from browseruse_bench.schemas.prompt import PromptRef, TemplatePrompt, TextPrompt
from browseruse_bench.utils.repo_root import REPO_ROOT


def load_prompt(path: str | Path) -> tuple[str, PromptRef]:
    """Load a prompt text file and return its content with a PromptRef.

    Args:
        path: Path to the ``.txt`` prompt file.  Resolved relative to
              ``REPO_ROOT`` when the path is relative.

    Returns:
        ``(content, PromptRef)`` where *content* is the file text (stripped)
        and *PromptRef* carries the repo-relative path, SHA-256 content hash,
        and file mtime (UTC).

    Raises:
        FileNotFoundError: If the prompt file does not exist.
    """
    resolved = Path(path) if Path(path).is_absolute() else REPO_ROOT / path
    if not resolved.is_file():
        raise FileNotFoundError(f"Prompt file not found: {resolved}")

    content = resolved.read_text(encoding="utf-8").strip()
    content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()

    # File mtime as UTC datetime
    mtime = datetime.fromtimestamp(resolved.stat().st_mtime, tz=timezone.utc)

    # Store repo-relative path for portability
    try:
        rel = str(resolved.relative_to(REPO_ROOT))
    except ValueError:
        rel = str(resolved)

    return content, PromptRef(path=rel, content_hash=content_hash, timestamp=mtime)


def make_prompt_ref(file_path: str | Path) -> PromptRef:
    """Create a PromptRef from any file using its SHA-256 hash.

    Useful for referencing non-``.txt`` prompt sources such as YAML configs.

    Args:
        file_path: Absolute or REPO_ROOT-relative path to the file.

    Returns:
        A ``PromptRef`` with the repo-relative path, SHA-256 content hash,
        and file mtime (UTC).

    Raises:
        FileNotFoundError: If the file does not exist.
    """
    resolved = Path(file_path) if Path(file_path).is_absolute() else REPO_ROOT / file_path
    if not resolved.is_file():
        raise FileNotFoundError(f"File not found: {resolved}")

    raw = resolved.read_bytes()
    content_hash = hashlib.sha256(raw).hexdigest()
    mtime = datetime.fromtimestamp(resolved.stat().st_mtime, tz=timezone.utc)

    try:
        rel = str(resolved.relative_to(REPO_ROOT))
    except ValueError:
        rel = str(resolved)

    return PromptRef(path=rel, content_hash=content_hash, timestamp=mtime)


def make_template_prompt(
    template: str,
    ref: PromptRef,
    params: dict[str, str],
) -> TemplatePrompt:
    """Create a TemplatePrompt snapshot from a template string and its ref."""
    return TemplatePrompt(ref=ref, template=template, params=params)


def make_text_prompt(text: str, ref: PromptRef) -> TextPrompt:
    """Create a TextPrompt snapshot from plain text and its ref."""
    return TextPrompt(ref=ref, text=text)

from __future__ import annotations

import logging
import os
import re
import subprocess
from pathlib import Path
from typing import Optional

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

logger = logging.getLogger(__name__)


def load_env_file(env_path: Optional[Path] = None, required: bool = False) -> bool:
    """Load environment variable file.

    Args:
        env_path: Path to .env file.
        required: If True, raise exception when file is missing or library is not installed.

    Returns:
        bool: True if loaded successfully.

    Raises:
        SystemExit: When required=True and conditions are not met.
    """
    if load_dotenv is None:
        if required:
            raise SystemExit("python-dotenv is required")
        return False

    if env_path and env_path.exists():
        load_dotenv(env_path)
        return True

    if required:
        raise SystemExit(f"File not found: {env_path}")
    return False


def get_env_var(key: str, default: str = "", required: bool = False, error_message: str = "") -> str:
    """Get environment variable.

    Args:
        key: Environment variable name.
        default: Default value.
        required: Whether it is required.
        error_message: Custom error message.

    Returns:
        str: Environment variable value or default.

    Raises:
        SystemExit: When required=True and variable does not exist.
    """
    value = os.getenv(key, default)
    if required and not value:
        msg = error_message or f"Missing environment variable: {key}"
        raise SystemExit(msg)
    return value or ""


def find_latest_tasks_dir(agent_output_dir: Path) -> Path:
    """Find the 'tasks' directory in the latest timestamp directory.

    Args:
        agent_output_dir: Base directory for Agent output.

    Returns:
        Path: Path to 'tasks' directory in the latest timestamp folder.
    """
    if not agent_output_dir.exists():
        raise SystemExit(f"[FAILED] Output directory does not exist: {agent_output_dir}\nPlease run tasks first to generate results")

    timestamp_dirs = [d for d in agent_output_dir.iterdir()
                     if d.is_dir() and re.match(r'^\d{8}_\d{6}$', d.name)]

    if not timestamp_dirs:
        raise SystemExit(f"[FAILED] Timestamp directory not found: {agent_output_dir}\nPlease run tasks first to generate results")

    return max(timestamp_dirs, key=lambda x: x.name) / "tasks"


def resolve_timeout_value(
    cli_value: Optional[int],
    agent_config: Optional[dict] = None,
    default: int = 360
) -> int:
    """Resolve timeout configuration.

    Priority: CLI > agent config > env var > default.
    """
    # 1. CLI value has highest priority
    if cli_value is not None:
        return cli_value

    # 2. Agent config second priority
    if agent_config:
        for timeout_key in ("timeout_seconds", "timeout", "TIMEOUT"):
            timeout_val = agent_config.get(timeout_key)
            if timeout_val is None:
                continue
            try:
                return int(timeout_val)
            except (TypeError, ValueError) as exc:
                logger.error(
                    "Invalid %s value in agent config (%r): %s",
                    timeout_key,
                    timeout_val,
                    exc,
                )

    # 3. Environment variable third priority (backward compatible)
    env_candidates = ("AGENT_TIMEOUT", "TIMEOUT", "timeout")
    for key in env_candidates:
        env_val = os.getenv(key)
        if env_val:
            try:
                return int(env_val)
            except ValueError:
                continue

    return default


def check_uv_available() -> bool:
    """Check if 'uv' package manager is available.

    Returns:
        bool: True if uv command is available, else False.
    """
    try:
        subprocess.run(["uv", "--version"], capture_output=True, check=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False

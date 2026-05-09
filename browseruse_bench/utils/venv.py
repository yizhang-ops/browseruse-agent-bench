"""Virtual environment management utilities.

This module provides functions for creating and managing virtual environments
for different agents.
"""
from __future__ import annotations

import logging
import subprocess
import sys
from pathlib import Path
from typing import Any

from browseruse_bench.utils.constants import IS_WINDOWS
from browseruse_bench.utils.repo_root import REPO_ROOT

logger = logging.getLogger(__name__)


def resolve_agent_venv_path(agent_entry: dict[str, Any]) -> Path:
    """Resolve agent virtual environment path.

    Args:
        agent_entry: Agent entry from config.

    Returns:
        Path: Absolute path to venv directory.

    Raises:
        SystemExit: If venv is not configured on the agent entry.
    """
    repo_root = REPO_ROOT
    venv_value = agent_entry.get("venv")
    if not isinstance(venv_value, str) or not venv_value.strip():
        raise SystemExit(
            "[FAILED] Agent config must define a non-empty 'venv' path. "
            "Refusing to fallback to .venv to avoid environment mismatch."
        )
    venv_path = Path(venv_value)
    if not venv_path.is_absolute():
        venv_path = repo_root / venv_path
    return venv_path


def ensure_venv(venv_path: Path, use_uv: bool) -> bool:
    """Ensure virtual environment exists, create if not.

    Args:
        venv_path: Path to virtual environment directory.
        use_uv: Whether to use uv for creating venv.

    Returns:
        bool: True if a new venv was created, False if it already existed.

    Raises:
        SystemExit: If venv creation fails.
    """
    python_bin = "Scripts\\python.exe" if IS_WINDOWS else "bin/python"
    venv_python = venv_path / python_bin

    if venv_python.exists():
        return False

    if venv_path.exists():
        raise SystemExit(
            f"[FAILED] Venv path exists but python not found: {venv_python}\n"
            "Hint: Remove the venv directory and re-run."
        )

    repo_root = REPO_ROOT
    logger.info(f"[INFO] Creating venv at {venv_path}")
    if use_uv:
        cmd = ["uv", "venv", str(venv_path)]
    else:
        cmd = [sys.executable, "-m", "venv", str(venv_path)]
        logger.warning("[WARNING] uv not available; creating venv with standard venv module")

    try:
        subprocess.run(cmd, cwd=str(repo_root), check=True)
    except FileNotFoundError as exc:
        raise SystemExit(f"[FAILED] Failed to create venv: {exc}") from exc
    except subprocess.CalledProcessError as exc:
        raise SystemExit(f"[FAILED] Venv creation failed: {exc}") from exc
    return True


def install_agent_dependencies(
    venv_path: Path,
    extra_name: str | None,
    use_uv: bool,
    additional_targets: list[str] | None = None,
) -> None:
    """Install agent dependencies into virtual environment.

    Args:
        venv_path: Path to virtual environment directory.
        extra_name: Optional extra name for pip install (e.g., "skyvern", "browser-use").
        use_uv: Whether to use uv for installing dependencies.
        additional_targets: Optional extra editable install targets.
            These are expected to be local paths and are always installed with ``-e``.

    Raises:
        SystemExit: If dependency installation fails.
    """
    python_bin = "Scripts\\python.exe" if IS_WINDOWS else "bin/python"
    venv_python = venv_path / python_bin
    if not venv_python.exists():
        raise SystemExit(f"[FAILED] Venv python not found: {venv_python}")

    repo_root = REPO_ROOT
    install_targets: list[str] = [f".[{extra_name}]" if extra_name else "."]
    if additional_targets:
        install_targets.extend(additional_targets)

    for target in install_targets:
        if use_uv:
            cmd = ["uv", "pip", "install", "--python", str(venv_python), "-e", target]
        else:
            cmd = [str(venv_python), "-m", "pip", "install", "-e", target]
            logger.warning("[WARNING] uv not available; installing dependencies with pip")

        logger.info("[INFO] Installing dependencies: %s", target)
        try:
            subprocess.run(cmd, cwd=str(repo_root), check=True)
        except FileNotFoundError as exc:
            raise SystemExit(f"[FAILED] Dependency install failed: {exc}") from exc
        except subprocess.CalledProcessError as exc:
            raise SystemExit(f"[FAILED] Dependency install failed: {exc}") from exc

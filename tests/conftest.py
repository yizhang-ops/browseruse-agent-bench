"""Pytest configuration and fixtures for browseruse_bench tests."""

import json
from pathlib import Path
from typing import Any, Dict

import pytest

from browseruse_bench.utils import REPO_ROOT, load_config_file


def pytest_configure(config):
    # The subprocess-based tests (test_scripts_viz_runs_directly and
    # test_visualization_serve_runs_directly) invoke generate_index.py in
    # a fresh interpreter where find_repo_root() walks upward looking for
    # experiments/. Without this mkdir the subprocess exits with a clean
    # RuntimeError (REPO_ROOT=None), but the tests assert returncode==0.
    (REPO_ROOT / "experiments").mkdir(exist_ok=True)

FIXTURES_DIR = REPO_ROOT / "tests" / "fixtures"


@pytest.fixture
def repo_root() -> Path:
    """Return the repository root path."""
    return REPO_ROOT


@pytest.fixture
def fixtures_dir() -> Path:
    """Return the fixtures directory path."""
    return FIXTURES_DIR


@pytest.fixture
def benchmarks_dir(repo_root: Path) -> Path:
    """Return the benchmarks directory path."""
    return repo_root / "benchmarks"


@pytest.fixture
def sample_task() -> dict:
    """Return a sample task for testing."""
    return {
        "id": "test_task_001",
        "website": "https://example.com",
        "task": "Test task description",
        "expect": "Expected result",
    }


@pytest.fixture
def sample_tasks(fixtures_dir: Path) -> Dict[str, Any]:
    """Load sample tasks from fixtures."""
    with open(fixtures_dir / "sample_tasks.json") as f:
        return json.load(f)


@pytest.fixture
def sample_result(fixtures_dir: Path) -> Dict[str, Any]:
    """Load sample result from fixtures."""
    with open(fixtures_dir / "sample_result.json") as f:
        return json.load(f)


@pytest.fixture
def sample_config(fixtures_dir: Path) -> Dict[str, Any]:
    """Load sample config from fixtures."""
    return load_config_file(fixtures_dir / "sample_config.yaml")

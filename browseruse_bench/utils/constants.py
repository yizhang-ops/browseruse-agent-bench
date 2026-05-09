from __future__ import annotations

import platform
from pathlib import Path

# Platform Detection
IS_WINDOWS = platform.system() == "Windows"

# Directory Names
EXPERIMENTS_DIR = "experiments"
TRAJECTORY_DIR = "trajectory"
TASKS_DIR = "tasks"
TASKS_EVAL_RESULT_DIR = "tasks_eval_result"
BENCHMARKS_DIR = "benchmarks"
DATA_DIR = "data"

# Filenames
RESULT_JSON = "result.json"
DATA_INFO_JSON = "data_info.json"
CONFIG_YAML = "config.yaml"

# Default Values
DEFAULT_BENCHMARK_NAME = "Online-Mind2Web"

# Config path (relative to REPO_ROOT, actual path resolved at import time)
CONFIG_PATH_REL = "config.yaml"

# Benchmark Specific Paths (relative to REPO_ROOT)
DEFAULT_TASKS_REL_PATH = Path("browseruse_bench") / "data" / DEFAULT_BENCHMARK_NAME / "task.jsonl"

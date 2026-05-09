from __future__ import annotations

from pathlib import Path

# Single source of truth for repository root.
# Use `from browseruse_bench.utils import REPO_ROOT` (or import from this module) instead of
# recomputing paths via `Path(__file__)` in other modules.
REPO_ROOT = Path(__file__).resolve().parent.parent.parent


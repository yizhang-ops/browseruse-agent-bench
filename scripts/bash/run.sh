#!/usr/bin/env bash
# =============================================================================
# Example: run browser-use agent on LexBench-Browser
# =============================================================================
# Public LexBench-Browser: 217 tasks, no login required
#
# Prerequisites:
#   1. Copy config.example.yaml to config.yaml and fill in API keys
#   2. Set up the browser-use venv: bash scripts/setup_env.sh browser-use
#
# Usage: bash scripts/bash/run.sh
# =============================================================================

set -euo pipefail

AGENT="browser-use"
BENCHMARK="BrowseComp"  # case-sensitive
MODEL="qwen-plus"         # must match agents.<agent>.models key in config.yaml
MODEL_ID="qwen3.5-plus"   # should match the resolved model_id in config.yaml

# -----------------------------------------------------------------------------
# Quick smoke test — run the first 3 tasks
# -----------------------------------------------------------------------------
uv run python scripts/run.py \
  --agent "$AGENT" \
  --benchmark "$BENCHMARK" \
  --model-name "$MODEL" \
  --mode sample_n \
  --count 1

# -----------------------------------------------------------------------------
# Run a random sample of 10 tasks
# -----------------------------------------------------------------------------
# uv run python scripts/run.py \
#   --agent "$AGENT" \
#   --benchmark "$BENCHMARK" \
#   --model-name "$MODEL" \
#   --mode sample_n \
#   --count 10

# -----------------------------------------------------------------------------
# Run all tasks (resume skips already-completed ones)
# -----------------------------------------------------------------------------
# uv run python scripts/run.py \
#   --agent "$AGENT" \
#   --benchmark "$BENCHMARK" \
#   --model-name "$MODEL" \
#   --mode all \
#   --skip-completed

# -----------------------------------------------------------------------------
# Evaluate results after a run
# -----------------------------------------------------------------------------
uv run python scripts/eval.py \
  --agent "$AGENT" \
  --benchmark "$BENCHMARK" \
  --model-id "$MODEL_ID"

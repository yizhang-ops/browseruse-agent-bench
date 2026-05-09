#!/usr/bin/env bash
# =============================================================================
# Example: run browser-use agent on LexBench-Browser L1
# =============================================================================
# L1: 183 tasks, no login required
# L2 / L3-api / L3-security: require account login, not covered here
#
# Prerequisites:
#   1. Copy config.example.yaml to config.yaml and fill in API keys
#   2. Set up the browser-use venv: bash scripts/setup_env.sh browser-use
#
# Usage: bash scripts/bash/run.sh
# =============================================================================

set -euo pipefail

AGENT="Agent-TARS"
BENCHMARK="LexBench-Browser"  # case-sensitive
MODEL="claude"
MODEL_ID="claude-opus-4-6"   # should match the resolved model_id in config.yaml

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

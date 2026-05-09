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

AGENT="skyvern"
BENCHMARK="LexBench-Browser"  # case-sensitive
MODEL="gpt-local"
MODEL_ID="gpt-4.1"   # skyvern cloud mode falls back to engine name for output/eval identity

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

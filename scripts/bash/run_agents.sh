#!/usr/bin/env bash
# =============================================================================
# Example: run multiple agents / models in parallel on LexBench-Browser L1
# =============================================================================
# Prerequisites:
#   1. Copy config.example.yaml to config.yaml and fill in API keys
#   2. Set up venvs: bash scripts/setup_env.sh browser-use
#                    bash scripts/setup_env.sh Agent-TARS
#
# Usage: bash scripts/bash/run_agents.sh
# =============================================================================

set -euo pipefail

BENCHMARK="LexBench-Browser"
MODE="sample_n"          # all | first_n | sample_n
COUNT=1            # used when MODE=first_n or sample_n
PIDS=()             # background process IDs

# -----------------------------------------------------------------------------
# Helper: run an inline-config model in background, collect PID
# -----------------------------------------------------------------------------
run_background() {
  local model_key="$1"
  local agent="$2"
  shift 2

  uv run python scripts/run.py \
    --agent      "$agent" \
    --benchmark  "$BENCHMARK" \
    --model-name "$model_key" \
    --mode       "$MODE" \
    --count      "$COUNT" \
    --skip-completed \
    "$@" &
  PIDS+=($!)
  echo "[LAUNCHED] $agent/$model_key (pid: ${PIDS[-1]})"
}

# =============================================================================
# browser-use × gpt-4.1
# =============================================================================
run_background "gpt" "browser-use"

# =============================================================================
# browser-use × qwen-plus
# =============================================================================
run_background "qwen-plus" "browser-use"

# =============================================================================
# browser-use × kimi-k2.5
# =============================================================================
run_background "kimi-k2.5" "browser-use"

# =============================================================================
# Agent-TARS × gpt-4.1  (uncomment to enable)
# =============================================================================
# run_background "gpt" "Agent-TARS"

# =============================================================================
# Wait for all runs to finish
# =============================================================================
echo ""
echo "[WAITING] ${#PIDS[@]} runs in progress..."
FAILED=0
for pid in "${PIDS[@]}"; do
  if wait "$pid"; then
    echo "[DONE] pid $pid exited 0"
  else
    echo "[FAILED] pid $pid exited $?"
    FAILED=$((FAILED + 1))
  fi
done

if [ "$FAILED" -gt 0 ]; then
  echo "[SUMMARY] $FAILED run(s) failed."
else
  echo "[SUMMARY] All runs completed successfully."
fi

# =============================================================================
# Evaluate all runs
# =============================================================================
echo ""
echo "[EVAL] Running evaluation for all completed runs..."

for model_id in gpt-4.1 qwen3.5-plus kimi-k2.5; do
  echo "  Evaluating browser-use / $model_id ..."
  uv run python scripts/eval.py \
    --agent      "browser-use" \
    --benchmark  "$BENCHMARK" \
    --model-id   "$model_id" || true
done

# Uncomment to eval Agent-TARS runs as well
# uv run python scripts/eval.py \
#   --agent "Agent-TARS" --benchmark "$BENCHMARK" --model-id "gpt-4.1" || true

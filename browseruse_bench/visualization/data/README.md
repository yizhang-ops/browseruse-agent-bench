# Visualization Data

This directory stores generated data files consumed by the Browser Agent Analyzer.

## Purpose

- `experiments.json` is the generated index used by the frontend.
- It summarizes discovered runs, tasks, task assets, and evaluation metadata.
- The file is rebuilt locally from `experiments/` by `browseruse_bench/visualization/generate_index.py`.

## Expected Files

- `experiments.json`

## Generation Flow

1. `browseruse_bench/visualization/generate_index.py` scans the repository `experiments/` directory.
2. It collects run-level metadata, task file listings, and evaluation results.
3. It writes the aggregated result to `browseruse_bench/visualization/data/experiments.json`.

## Commit Policy

- Do not commit generated `experiments.json` snapshots by default.
- Commit only stable documentation or intentionally curated example data.
- Refresh the file locally by running:

```bash
bubench viz --generate-only
```

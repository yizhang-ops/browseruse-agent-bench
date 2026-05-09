# Visualization Sidebar Tree Structure Design

**Date:** 2026-04-21
**Status:** Approved

## Problem

The left sidebar currently shows all runs as a flat list (`agent / model [timestamp]`). With 295+ runs this is hard to navigate. The experiments directory already has a natural 5-level hierarchy (`benchmark/split/agent/model/timestamp`) that the UI should reflect.

## Goal

Replace the flat runs list with a collapsible tree that mirrors the experiments directory structure, with aggregated stats at each non-leaf node.

## Tree Structure

```
{benchmark} / {split}           — always expanded, not collapsible
  └── {agent}                   — expanded by default, clickable to collapse
        └── {model}             — collapsed by default, clickable to expand
              └── {timestamp}   — leaf, clickable to load run
```

Default state: benchmark and agent layers visible and expanded; model layer collapsed.

## Display Text

| Level | Example |
|-------|---------|
| benchmark/split | `Online-Mind2Web / All` |
| agent | `▾ Agent-TARS  76.2% avg · 8 runs` |
| model (collapsed) | `▸ gpt-4.1  80.0% avg · 3 runs` |
| model (expanded) | `▾ gpt-4.1  80.0% avg · 3 runs` |
| run (leaf) | `20260331_135925  75.0% (3/4)` |

Stats at agent/model level are the mean success rate across all runs in that group.

## Changes

### 1. `visualization/generate_index.py`

- Add optional `model` parameter to `scan_run(benchmark, split, agent, timestamp_dir, model=None)`.
- In `generate_index()`, pass `model=sub_dir.name` for 5-level paths, `model=None` for 4-level paths.
- Add `"model"` field to the run dict returned by `scan_run`.

### 2. `visualization/js/data-loader.js`

- Add `getRunsGrouped(judgeMode)` that groups runs into:
  ```
  [ { benchmark, split, stats, agents: [
      { name, stats, models: [
          { name, stats, runs: [ run, ... ] }
      ] }
  ] } ]
  ```
- Each `stats` object: `{ avgSuccessRate, totalRuns }` (mean of child run success rates).
- Keep existing `getRuns()` unchanged (used by Statistics view and other callers).

### 3. `visualization/js/app.js`

- Replace `populateRunsList()` body with a tree renderer using `dataLoader.getRunsGrouped()`.
- Benchmark nodes: always rendered expanded, no toggle.
- Agent nodes: rendered expanded by default; click toggles collapse. State stored in a `Set` of collapsed keys.
- Model nodes: rendered collapsed by default; click toggles expand.
- Leaf run nodes: click calls existing `selectRun(uuid)`, adds `.active` class (same as current behavior).
- Active run tracking unchanged — `data-uuid` attribute on leaf nodes, `.active` class applied/removed on selection.

### 4. `visualization/css/style.css`

New classes (replace existing `.run-item` usage in tree context):

- `.tree-benchmark` — group header, not interactive
- `.tree-agent` — expandable row, cursor pointer
- `.tree-model` — expandable row, cursor pointer, indented
- `.tree-run` — leaf row, cursor pointer, indented further, highlight on `.active`
- `.tree-toggle` — inline `▸`/`▾` indicator, no separate click target
- Indentation via `padding-left` on each level

Existing `.run-item`, `.run-info`, `.run-name`, `.run-stats`, `.run-split` classes remain for welcome screen run cards (unaffected).

## Out of Scope

- Experiment Sets section in the sidebar is unchanged.
- Compare mode, Statistics view, and all other views are unchanged.
- No search/filter within the tree (existing task search on right sidebar is unchanged).
- No persistent collapse state across page reloads.

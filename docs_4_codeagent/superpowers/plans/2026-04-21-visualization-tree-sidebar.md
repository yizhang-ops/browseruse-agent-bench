# Visualization Sidebar Tree Structure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the flat runs list in the left sidebar with a collapsible tree that mirrors the `experiments/{benchmark}/{split}/{agent}/{model}/{timestamp}` directory structure, with aggregated success-rate stats at each non-leaf node.

**Architecture:** Add a `model` field to the run index (Python), add `getRunsGrouped()` to the data layer (JS), replace `populateRunsList()` with a tree renderer (JS), and add tree CSS classes.

**Tech Stack:** Python 3, vanilla JS (no framework), CSS custom properties already defined in `style.css`.

---

### Task 1: Add `model` field to run index

**Files:**
- Modify: `visualization/generate_index.py:339` (`scan_run` signature and return dict)
- Modify: `visualization/generate_index.py:811-824` (caller loop in `generate_index`)

- [ ] **Step 1: Update `scan_run` signature and return dict**

In `visualization/generate_index.py`, change `scan_run` to accept an optional `model` parameter and include it in the returned dict:

```python
def scan_run(benchmark: str, split: str, agent: str, timestamp_dir: Path, model: Optional[str] = None) -> Optional[Dict]:
    """Scan one experiment run directory."""
    tasks_dir = timestamp_dir / "tasks"
    if not tasks_dir.exists():
        return None
    # ... (rest of body unchanged until the return statement)
```

And in the `return` dict at the end of `scan_run`, add `"model": model` after `"agent": agent`:

```python
    return {
        "uuid": uuid,
        "benchmark": benchmark,
        "split": split,
        "agent": agent,
        "model": model,          # NEW
        "model_id": model_id,
        "config": config,
        # ... rest unchanged
    }
```

- [ ] **Step 2: Pass model name from the caller loop**

In `generate_index()`, replace the existing inner loop (the `for sub_dir` block) with:

```python
                for sub_dir in sorted(agent_dir.iterdir()):
                    if not sub_dir.is_dir():
                        continue
                    # Support both 4-level ({agent}/{timestamp}) and
                    # 5-level ({agent}/{model}/{timestamp}) directory layouts.
                    if (sub_dir / "tasks").exists():
                        # 4-level: sub_dir IS the timestamp dir, no model layer
                        candidates = [(sub_dir, None)]
                    else:
                        # 5-level: sub_dir is the model dir
                        model_name = sub_dir.name
                        candidates = [
                            (d, model_name)
                            for d in sorted(sub_dir.iterdir())
                            if d.is_dir()
                        ]
                    for ts_dir, model_name in candidates:
                        print(f"  Scanning {benchmark}/{split}/{agent}/{ts_dir.relative_to(agent_dir)}")
                        run_data = scan_run(benchmark, split, agent, ts_dir, model=model_name)
                        if run_data:
                            index["runs"].append(run_data)
                            index["all_tasks"].update(run_data["task_ids"])

                            if index["common_tasks"] is None:
                                index["common_tasks"] = set(run_data["task_ids"])
                            else:
                                index["common_tasks"] &= set(run_data["task_ids"])
```

- [ ] **Step 3: Regenerate index and verify**

```bash
cd visualization && python generate_index.py
```

Expected output ends with:
```
Index written to: .../data/experiments.json
  Runs           : 295
```

Then verify the `model` field is present:
```bash
python3 -c "
import json
with open('data/experiments.json') as f:
    idx = json.load(f)
r = idx['runs'][0]
print('model:', r.get('model'))
print('agent:', r.get('agent'))
"
```
Expected: prints a non-None model name (e.g. `model: gpt-4.1`).

- [ ] **Step 4: Commit**

```bash
git add visualization/generate_index.py visualization/data/experiments.json
git commit -m "feat(visualization): add model field to run index"
```

---

### Task 2: Add `getRunsGrouped()` to data-loader.js

**Files:**
- Modify: `visualization/js/data-loader.js` (add method after `getRuns`)

- [ ] **Step 1: Add `getRunsGrouped` method**

In `visualization/js/data-loader.js`, insert the following method after the closing `}` of `getRunDisplayName` (around line 85):

```javascript
    getRunsGrouped(judgeMode = this.getDefaultJudgeMode()) {
        if (!this.index) return [];

        // Group: benchmark+split → agent → model → [runs]
        const benchMap = new Map(); // key: "benchmark/split"

        for (const run of this.index.runs) {
            const bKey = `${run.benchmark}|||${run.split}`;
            if (!benchMap.has(bKey)) {
                benchMap.set(bKey, {
                    benchmark: run.benchmark,
                    split: run.split,
                    agentMap: new Map()
                });
            }
            const bench = benchMap.get(bKey);

            const agentName = run.agent || 'unknown';
            if (!bench.agentMap.has(agentName)) {
                bench.agentMap.set(agentName, { name: agentName, modelMap: new Map() });
            }
            const agent = bench.agentMap.get(agentName);

            const modelName = run.model || run.model_id || 'unknown';
            if (!agent.modelMap.has(modelName)) {
                agent.modelMap.set(modelName, { name: modelName, runs: [] });
            }
            const model = agent.modelMap.get(modelName);

            const stats = this.getRunStats(run, judgeMode);
            model.runs.push({ uuid: run.uuid, stats });
        }

        // Compute aggregated stats and flatten Maps to arrays
        const result = [];
        for (const bench of benchMap.values()) {
            const agents = [];
            for (const agent of bench.agentMap.values()) {
                const models = [];
                for (const model of agent.modelMap.values()) {
                    const rates = model.runs.map(r => r.stats.successRate);
                    const avgRate = rates.length ? rates.reduce((a, b) => a + b, 0) / rates.length : 0;
                    models.push({
                        name: model.name,
                        runs: model.runs,
                        stats: { avgSuccessRate: avgRate, totalRuns: model.runs.length }
                    });
                }
                const allRates = models.flatMap(m => m.runs.map(r => r.stats.successRate));
                const agentAvg = allRates.length ? allRates.reduce((a, b) => a + b, 0) / allRates.length : 0;
                agents.push({
                    name: agent.name,
                    models,
                    stats: { avgSuccessRate: agentAvg, totalRuns: allRates.length }
                });
            }
            const allBenchRates = agents.flatMap(a => a.models.flatMap(m => m.runs.map(r => r.stats.successRate)));
            const benchAvg = allBenchRates.length ? allBenchRates.reduce((a, b) => a + b, 0) / allBenchRates.length : 0;
            result.push({
                benchmark: bench.benchmark,
                split: bench.split,
                agents,
                stats: { avgSuccessRate: benchAvg, totalRuns: allBenchRates.length }
            });
        }
        return result;
    }
```

- [ ] **Step 2: Smoke-test in browser console**

Start the server:
```bash
python visualization/serve.py
```

Open `http://localhost:8080`, open DevTools console, run:
```javascript
const g = dataLoader.getRunsGrouped();
console.log('benchmarks:', g.length);
console.log('first bench:', g[0].benchmark, g[0].split);
console.log('agents:', g[0].agents.map(a => a.name));
console.log('models of first agent:', g[0].agents[0].models.map(m => m.name));
console.log('runs in first model:', g[0].agents[0].models[0].runs.length);
```

Expected: multiple benchmarks, multiple agents, model names like `gpt-4.1`, runs count > 0.

- [ ] **Step 3: Commit**

```bash
git add visualization/js/data-loader.js
git commit -m "feat(visualization): add getRunsGrouped() to data loader"
```

---

### Task 3: Replace flat list with tree renderer in app.js

**Files:**
- Modify: `visualization/js/app.js` (`populateRunsList` method and constructor)

- [ ] **Step 1: Add collapse state to constructor**

In the `constructor()` of `BrowserAgentAnalyzer` (around line 14), add two Sets to track collapsed nodes:

```javascript
constructor() {
    this.currentMode = 'run';
    this.currentRun = null;
    this.currentTask = null;
    this.currentTaskData = null;
    this.currentView = 'step-first';
    this.judgeMode = 'llm_judge';
    this.screenshotIndex = 0;
    this.screenshotSteps = [];
    this.charts = {};
    this.currentExperimentSet = null;
    this.currentExpSetTask = null;
    // Tree collapse state: agents expanded by default, models collapsed
    this.collapsedAgents = new Set();   // keys of collapsed agent nodes
    this.expandedModels = new Set();    // keys of expanded model nodes
}
```

- [ ] **Step 2: Replace `populateRunsList()`**

Replace the entire `populateRunsList()` method body with the tree renderer:

```javascript
populateRunsList() {
    const container = document.getElementById('runs-list');
    const grouped = dataLoader.getRunsGrouped(this.judgeMode);

    const html = grouped.map(bench => {
        const bKey = `${bench.benchmark}|||${bench.split}`;
        const agentsHtml = bench.agents.map(agent => {
            const aKey = `${bKey}|||${agent.name}`;
            const isAgentCollapsed = this.collapsedAgents.has(aKey);
            const modelsHtml = agent.models.map(model => {
                const mKey = `${aKey}|||${model.name}`;
                const isModelExpanded = this.expandedModels.has(mKey);
                const runsHtml = model.runs.map(run => `
                    <div class="tree-run" data-uuid="${run.uuid}">
                        <span class="tree-run-ts">${run.uuid}</span>
                        <span class="tree-run-stats">${run.stats.successRate.toFixed(1)}% (${run.stats.successCount}/${run.stats.evaluatedTasks})</span>
                    </div>
                `).join('');
                return `
                    <div class="tree-model ${isModelExpanded ? 'expanded' : 'collapsed'}" data-model-key="${this.escapeHtml(mKey)}">
                        <div class="tree-model-header">
                            <span class="tree-toggle">${isModelExpanded ? '▾' : '▸'}</span>
                            <span class="tree-model-name">${this.escapeHtml(model.name)}</span>
                            <span class="tree-node-stats">${model.stats.avgSuccessRate.toFixed(1)}% avg · ${model.stats.totalRuns} run${model.stats.totalRuns !== 1 ? 's' : ''}</span>
                        </div>
                        <div class="tree-model-children" style="display:${isModelExpanded ? 'block' : 'none'}">
                            ${runsHtml}
                        </div>
                    </div>
                `;
            }).join('');
            return `
                <div class="tree-agent ${isAgentCollapsed ? 'collapsed' : 'expanded'}" data-agent-key="${this.escapeHtml(aKey)}">
                    <div class="tree-agent-header">
                        <span class="tree-toggle">${isAgentCollapsed ? '▸' : '▾'}</span>
                        <span class="tree-agent-name">${this.escapeHtml(agent.name)}</span>
                        <span class="tree-node-stats">${agent.stats.avgSuccessRate.toFixed(1)}% avg · ${agent.stats.totalRuns} run${agent.stats.totalRuns !== 1 ? 's' : ''}</span>
                    </div>
                    <div class="tree-agent-children" style="display:${isAgentCollapsed ? 'none' : 'block'}">
                        ${modelsHtml}
                    </div>
                </div>
            `;
        }).join('');
        return `
            <div class="tree-benchmark">
                <div class="tree-benchmark-header">${this.escapeHtml(bench.benchmark)} / ${this.escapeHtml(bench.split)}</div>
                <div class="tree-benchmark-children">${agentsHtml}</div>
            </div>
        `;
    }).join('');

    container.innerHTML = html;

    // Agent toggle
    container.querySelectorAll('.tree-agent-header').forEach(header => {
        header.addEventListener('click', () => {
            const agentEl = header.closest('.tree-agent');
            const aKey = agentEl.dataset.agentKey;
            const children = agentEl.querySelector('.tree-agent-children');
            const toggle = header.querySelector('.tree-toggle');
            if (this.collapsedAgents.has(aKey)) {
                this.collapsedAgents.delete(aKey);
                children.style.display = 'block';
                agentEl.classList.replace('collapsed', 'expanded');
                toggle.textContent = '▾';
            } else {
                this.collapsedAgents.add(aKey);
                children.style.display = 'none';
                agentEl.classList.replace('expanded', 'collapsed');
                toggle.textContent = '▸';
            }
        });
    });

    // Model toggle
    container.querySelectorAll('.tree-model-header').forEach(header => {
        header.addEventListener('click', () => {
            const modelEl = header.closest('.tree-model');
            const mKey = modelEl.dataset.modelKey;
            const children = modelEl.querySelector('.tree-model-children');
            const toggle = header.querySelector('.tree-toggle');
            if (this.expandedModels.has(mKey)) {
                this.expandedModels.delete(mKey);
                children.style.display = 'none';
                modelEl.classList.replace('expanded', 'collapsed');
                toggle.textContent = '▸';
            } else {
                this.expandedModels.add(mKey);
                children.style.display = 'block';
                modelEl.classList.replace('collapsed', 'expanded');
                toggle.textContent = '▾';
            }
        });
    });

    // Run click
    container.querySelectorAll('.tree-run').forEach(item => {
        item.addEventListener('click', () => {
            container.querySelectorAll('.tree-run').forEach(i => i.classList.remove('active'));
            item.classList.add('active');
            this.selectRun(item.dataset.uuid);
        });
    });

    this.populateExperimentSetsList();
}
```

- [ ] **Step 3: Restore active state after re-render**

In `onIndexReloaded()` (around line 1866), after `this.populateRunsList()`, add:

```javascript
onIndexReloaded() {
    const currentJudgeMode = this.judgeMode;
    this.populateRunsList();
    this.populateJudgeModeSelect();
    document.getElementById('judge-mode-select').value = currentJudgeMode;
    // Restore active run highlight
    if (this.currentRun) {
        document.querySelector(`.tree-run[data-uuid="${this.currentRun}"]`)?.classList.add('active');
    }
    // ... rest of existing body unchanged
```

- [ ] **Step 4: Verify in browser**

Open `http://localhost:8080`. The left sidebar should show:
- Benchmark headers (not clickable)
- Agent rows with `▾` and `avg% · N runs`
- Clicking an agent collapses it to `▸`
- Model rows collapsed by default with `▸`
- Clicking a model expands it showing timestamp runs
- Clicking a timestamp run loads the run (right sidebar tasks appear)

- [ ] **Step 5: Commit**

```bash
git add visualization/js/app.js
git commit -m "feat(visualization): replace flat runs list with collapsible tree"
```

---

### Task 4: Add tree CSS classes

**Files:**
- Modify: `visualization/css/style.css` (add after existing `.run-item` block, around line 401)

- [ ] **Step 1: Add tree styles**

Insert after the `.run-item.active .run-split` block (after line 400):

```css
/* ── Tree sidebar ─────────────────────────────────────────── */

.tree-benchmark-header {
    padding: 8px 12px 4px;
    font-size: 0.7rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: var(--text-muted);
    user-select: none;
}

.tree-agent-header,
.tree-model-header {
    display: flex;
    align-items: center;
    gap: 4px;
    padding: 5px 12px;
    border-radius: var(--radius-sm);
    cursor: pointer;
    transition: background-color 0.15s;
    user-select: none;
}

.tree-agent-header {
    font-size: 0.8rem;
    font-weight: 600;
}

.tree-model-header {
    padding-left: 24px;
    font-size: 0.78rem;
    font-weight: 500;
}

.tree-agent-header:hover,
.tree-model-header:hover {
    background-color: var(--bg-hover);
}

.tree-toggle {
    font-size: 0.65rem;
    width: 10px;
    flex-shrink: 0;
    color: var(--text-muted);
}

.tree-agent-name,
.tree-model-name {
    flex: 1;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}

.tree-node-stats {
    font-size: 0.7rem;
    color: var(--accent-green);
    white-space: nowrap;
    flex-shrink: 0;
}

.tree-run {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 4px 12px 4px 36px;
    border-radius: var(--radius-sm);
    cursor: pointer;
    transition: background-color 0.15s;
    gap: 8px;
}

.tree-run:hover {
    background-color: var(--bg-hover);
}

.tree-run.active {
    background-color: var(--accent-blue);
    color: white;
}

.tree-run-ts {
    font-size: 0.75rem;
    font-family: monospace;
    flex: 1;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}

.tree-run-stats {
    font-size: 0.7rem;
    color: var(--accent-green);
    white-space: nowrap;
    flex-shrink: 0;
}

.tree-run.active .tree-run-stats {
    color: rgba(255, 255, 255, 0.85);
}
```

- [ ] **Step 2: Verify visual result**

Reload `http://localhost:8080`. Check:
- Benchmark headers appear muted/uppercase
- Agent rows are slightly bolder than model rows
- Model rows are indented further than agents
- Run rows are indented further than models and show monospace timestamp
- Active run is highlighted in blue, stats text turns white

- [ ] **Step 3: Commit**

```bash
git add visualization/css/style.css
git commit -m "feat(visualization): add tree sidebar CSS"
```

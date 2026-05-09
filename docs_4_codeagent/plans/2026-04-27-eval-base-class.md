# Eval 模块基类化重构 — 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把三套独立的 benchmark 评测脚本抽象成 `BaseEvaluator` + 派生类层次，benchmark 整体迁入 `browseruse_bench/`，CLI 取消子进程边界并删除所有 `if benchmark==X` 分支。

**Architecture:** 数据放 `browseruse_bench/data/<X>/`，代码放 `browseruse_bench/eval/<X>/`；`eval/base.py` 提供 `BaseEvaluator` final 编排（resume / JSONL append / summary），子类只实现 `load_tasks` 与 `evaluate_one`；`eval/registry.py` 仿 `browsers/registry.py` 用 lazy 工厂注册；CLI in-process 调用 `evaluator.run()`，配置 `benchmarks.<X>` 整块删除，路径与 `default_mode` 由约定 / `ClassVar` 取代。

**Tech Stack:** Python 3.11+、pytest、`uv`、现有 `browseruse_bench` 依赖（OpenAI、PIL、backoff、multiprocessing）

参考设计：[docs_4_codeagent/specs/2026-04-27-eval-base-class-design.md](../specs/2026-04-27-eval-base-class-design.md)

---

## 文件结构总览

**新增**

- `browseruse_bench/eval/__init__.py`
- `browseruse_bench/eval/base.py` — `BaseEvaluator` 抽象类、`EvaluatorArgs` dataclass
- `browseruse_bench/eval/registry.py` — `register_evaluator` / `get_evaluator_class`
- `browseruse_bench/eval/score.py` — `extract_score_from_response`、`calculate_success`
- `browseruse_bench/eval/model.py` — `EvaluationModel`、`load_evaluation_model`、`encode_image`
- `browseruse_bench/eval/summary.py` — `calculate_evaluation_cost`、`aggregate_evaluation_costs`、`normalized_results_file`、`generate_evaluation_summary`
- `browseruse_bench/eval/failure.py` — `classify_failure_case`、`classify_failures_batch`
- `browseruse_bench/eval/online_mind2web/{__init__.py, evaluator.py, webjudge.py, utils.py}`
- `browseruse_bench/eval/browse_comp/{__init__.py, evaluator.py, grader.py}`
- `browseruse_bench/eval/lexbench_browser/{__init__.py, evaluator.py, lexmount_eval.py, screenshot_cleaner.py, add_task_tags.py, remove_tags.py}`
- `browseruse_bench/data/{LexBench-Browser, Online-Mind2Web, BrowseComp}/...` (mv from `benchmarks/<X>/data/`)
- `tests/browseruse_bench/test_eval_base.py` — 基类编排顺序测试
- `tests/browseruse_bench/test_eval_registry.py` — 注册表测试

**修改**

- `browseruse_bench/utils/__init__.py` — re-export shim 转发到 `eval/` 真实位置
- `browseruse_bench/utils/eval.py` — 收缩为薄 shim（保留过渡期）
- `browseruse_bench/utils/eval_failure.py` — 收缩为薄 shim
- `browseruse_bench/utils/stats.py:196` — `generate_evaluation_summary` 迁出（保留 shim）
- `browseruse_bench/utils/config_loader.py` — 删除 `resolve_benchmark_config`
- `browseruse_bench/utils/data_loader.py:326` — docstring 路径示例更新
- `browseruse_bench/cli/eval.py` — 整体瘦身：删除子进程相关全部代码、benchmark 分支
- `browseruse_bench/cli/run.py:125,464,472,491` — 路径拼接由约定取代
- `browseruse_bench/visualization/generate_index.py:148` — fallback 注释更新
- `config.example.yaml` — 删除 `benchmarks:` 顶层块（330-344 行）
- `tests/browseruse_bench/test_config_loader.py` — 删除 `resolve_benchmark_config` 相关测试

**删除**

- 整个 `benchmarks/` 顶级目录（最后一步）

---

## Task 1: 创建 `browseruse_bench/eval/` 包骨架

**Files:**
- Create: `browseruse_bench/eval/__init__.py`

- [ ] **Step 1: 创建空包**

```bash
mkdir -p browseruse_bench/eval
```

- [ ] **Step 2: 写 __init__.py**

```python
# browseruse_bench/eval/__init__.py
"""Evaluation module: BaseEvaluator + per-benchmark subclasses + shared utils."""
from __future__ import annotations
```

- [ ] **Step 3: 提交**

```bash
git add browseruse_bench/eval/__init__.py
git commit -m "feat(eval): scaffold browseruse_bench.eval package"
```

---

## Task 2: 迁移 score 工具到 `eval/score.py`

**Files:**
- Create: `browseruse_bench/eval/score.py`
- Modify: `browseruse_bench/utils/eval.py` (薄 shim)
- Modify: `browseruse_bench/utils/__init__.py` (转发 import 来源)

- [ ] **Step 1: 跑一遍既有测试基线**

```bash
uv run pytest tests/browseruse_bench/test_eval.py -v
```
Expected: PASS（4 个 test，对应 `encode_image` / `extract_score_from_response` / `calculate_success`）。记录通过用例数。

- [ ] **Step 2: 把 `extract_score_from_response` 与 `calculate_success` 整段从 `utils/eval.py` 拷贝到 `browseruse_bench/eval/score.py`**

文件头部用 `from __future__ import annotations`，import `re`、`logging`。函数体一字不改。

- [ ] **Step 3: `utils/eval.py` 中两个函数原位置改写为 re-export**

```python
# utils/eval.py 内删除 extract_score_from_response / calculate_success 函数体，替换为：
from browseruse_bench.eval.score import calculate_success, extract_score_from_response  # noqa: F401
```

- [ ] **Step 4: 重跑既有测试，验证 re-export 不破坏 import 路径**

```bash
uv run pytest tests/browseruse_bench/test_eval.py -v
```
Expected: PASS（同 Step 1 结果）

- [ ] **Step 5: 提交**

```bash
git add browseruse_bench/eval/score.py browseruse_bench/utils/eval.py
git commit -m "refactor(eval): move score helpers to browseruse_bench.eval.score"
```

---

## Task 3: 迁移 EvaluationModel + encode_image 到 `eval/model.py`

**Files:**
- Create: `browseruse_bench/eval/model.py`
- Modify: `browseruse_bench/utils/eval.py`

- [ ] **Step 1: 把 `EvaluationModel` 类（含 fallback 分支）、`load_evaluation_model`、`encode_image`、`_log_backoff` 整段拷到 `eval/model.py`**

保持 try/except import 守卫（`backoff` / `openai` / `PIL`）原样，函数体逐字不变。

- [ ] **Step 2: `utils/eval.py` 替换为 re-export**

删除原函数与类体，替换为：
```python
from browseruse_bench.eval.model import (  # noqa: F401
    EvaluationModel,
    encode_image,
    load_evaluation_model,
)
```

- [ ] **Step 3: 测试**

```bash
uv run pytest tests/browseruse_bench/test_eval.py -v
```
Expected: PASS

- [ ] **Step 4: 提交**

```bash
git add browseruse_bench/eval/model.py browseruse_bench/utils/eval.py
git commit -m "refactor(eval): move EvaluationModel + encode_image to eval.model"
```

---

## Task 4: 迁移 cost / summary / normalized_results_file 到 `eval/summary.py`

**Files:**
- Create: `browseruse_bench/eval/summary.py`
- Modify: `browseruse_bench/utils/eval.py`、`browseruse_bench/utils/stats.py`、`browseruse_bench/utils/__init__.py`

- [ ] **Step 1: 拷贝 `calculate_evaluation_cost`、`aggregate_evaluation_costs`、`_parse_consecutive_json_objects`、`_convert_json_to_jsonl`、`normalized_results_file` 从 `utils/eval.py` 到 `eval/summary.py`**

- [ ] **Step 2: 把 `utils/stats.py:196` 的 `generate_evaluation_summary` 整体移到 `eval/summary.py`**

`utils/stats.py` 改为 re-export：
```python
from browseruse_bench.eval.summary import generate_evaluation_summary  # noqa: F401
```

- [ ] **Step 3: `utils/eval.py` 替换为 re-export**

```python
from browseruse_bench.eval.summary import (  # noqa: F401
    aggregate_evaluation_costs,
    calculate_evaluation_cost,
    normalized_results_file,
)
```

- [ ] **Step 4: 测试**

```bash
uv run pytest tests/browseruse_bench/test_eval.py tests/browseruse_bench/test_stats.py -v
```
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add browseruse_bench/eval/summary.py browseruse_bench/utils/eval.py browseruse_bench/utils/stats.py
git commit -m "refactor(eval): consolidate cost + summary helpers in eval.summary"
```

---

## Task 5: 迁移 failure 分类到 `eval/failure.py`

**Files:**
- Create: `browseruse_bench/eval/failure.py`
- Modify: `browseruse_bench/utils/eval_failure.py`

- [ ] **Step 1: `git mv` 整文件，再加薄 shim**

```bash
git mv browseruse_bench/utils/eval_failure.py browseruse_bench/eval/failure.py
```

- [ ] **Step 2: 创建薄 shim 维持外部 import 路径**

```python
# browseruse_bench/utils/eval_failure.py
"""Back-compat shim. Real implementation in browseruse_bench.eval.failure."""
from browseruse_bench.eval.failure import classify_failure_case, classify_failures_batch  # noqa: F401
```

- [ ] **Step 3: 测试**

```bash
uv run pytest tests/ -v -k "eval or failure" 2>&1 | tail -20
```
Expected: 全部 PASS（如果有 fail 是预期外的，先排查）

- [ ] **Step 4: 提交**

```bash
git add -A
git commit -m "refactor(eval): move failure classification to eval.failure"
```

---

## Task 6: 定义 `EvaluatorArgs` dataclass + `BaseEvaluator` 框架

**Files:**
- Create: `browseruse_bench/eval/base.py`
- Test: `tests/browseruse_bench/test_eval_base.py`

- [ ] **Step 1: 写失败测试 — 验证 `EvaluatorArgs` 是 dataclass、字段完整**

`tests/browseruse_bench/test_eval_base.py`:
```python
"""Tests for BaseEvaluator scaffolding."""
from __future__ import annotations

from dataclasses import is_dataclass, fields
from pathlib import Path

import pytest

from browseruse_bench.eval.base import BaseEvaluator, EvaluatorArgs


def test_evaluator_args_is_dataclass():
    assert is_dataclass(EvaluatorArgs)


def test_evaluator_args_required_fields():
    field_names = {f.name for f in fields(EvaluatorArgs)}
    expected = {
        "benchmark", "model", "api_key", "base_url",
        "trajectories_dir", "output_path", "score_threshold",
        "num_worker", "temperature", "split", "data_source", "mode", "extra",
    }
    assert expected.issubset(field_names)
```

- [ ] **Step 2: Run — 应该 ImportError 失败**

```bash
uv run pytest tests/browseruse_bench/test_eval_base.py -v
```
Expected: FAIL（`ImportError: cannot import name ...`）

- [ ] **Step 3: 写 `EvaluatorArgs` + `BaseEvaluator` 骨架**

`browseruse_bench/eval/base.py`:
```python
"""Base class and shared dataclass for benchmark evaluators."""
from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, ClassVar, Dict, Iterator, List, Optional, Set

from browseruse_bench.eval.model import EvaluationModel
from browseruse_bench.eval.summary import (
    aggregate_evaluation_costs,
    generate_evaluation_summary,
)
from browseruse_bench.schemas.eval_result import EvalResult

logger = logging.getLogger(__name__)


@dataclass
class EvaluatorArgs:
    """Uniform argument bundle passed to every BaseEvaluator subclass."""

    benchmark: str
    model: str
    api_key: str
    base_url: Optional[str]
    trajectories_dir: Path
    output_path: Path
    score_threshold: Optional[int]
    num_worker: int
    temperature: Optional[float]
    split: str
    data_source: str
    mode: str
    extra: Dict[str, Any] = field(default_factory=dict)


class BaseEvaluator(ABC):
    """Abstract base class for benchmark evaluators.

    Subclasses must implement ``load_tasks`` and ``evaluate_one``. The
    ``run`` method orchestrates resume → iteration → JSONL append → summary
    → post-hook and is intentionally non-virtual.
    """

    name: ClassVar[str]
    default_mode: ClassVar[str]

    def __init__(self, args: EvaluatorArgs, model: EvaluationModel) -> None:
        self.args = args
        self.model = model

    # ---- Subclass hooks (mandatory) -----------------------------------
    @abstractmethod
    def load_tasks(self) -> Dict[str, Dict[str, Any]]:
        """Return mapping of task_id -> task data (split-aware if needed)."""

    @abstractmethod
    def evaluate_one(
        self,
        task_id: str,
        task: Dict[str, Any],
        agent_result: Dict[str, Any],
        trajectory_dir: Path,
    ) -> EvalResult:
        """Judge a single task and return a populated EvalResult."""

    # ---- Subclass hooks (optional) ------------------------------------
    def list_completed_tasks(self) -> List[Path]:
        return [
            d for d in sorted(self.args.trajectories_dir.iterdir())
            if d.is_dir() and (d / "result.json").exists()
        ]

    def results_filename(self) -> str:
        return f"{self.name}_{self.args.model}_results.json"

    def summary_filename(self) -> str:
        return f"{self.name}_{self.args.model}_summary.json"

    def post_eval_hook(self, results: List[EvalResult]) -> None:
        return None

    def _run_iteration(
        self,
        pending: List[str],
        tasks: Dict[str, Dict[str, Any]],
    ) -> Iterator[EvalResult]:
        for task_id in pending:
            trajectory_dir = self.args.trajectories_dir / task_id
            with open(trajectory_dir / "result.json", encoding="utf-8") as fh:
                agent_result = json.load(fh)
            yield self.evaluate_one(task_id, tasks[task_id], agent_result, trajectory_dir)

    # ---- Final scaffolding (do not override) --------------------------
    def results_path(self) -> Path:
        return self.args.output_path / self.results_filename()

    def summary_path(self) -> Path:
        return self.args.output_path / self.summary_filename()

    def run(self) -> int:
        self.args.output_path.mkdir(parents=True, exist_ok=True)
        tasks = self.load_tasks()
        completed = self.list_completed_tasks()
        already = self._resume_skip_set()
        pending = [
            p.name for p in completed
            if p.name not in already and p.name in tasks
        ]
        logger.info("Evaluating %d tasks (skip %d already done)", len(pending), len(already))
        results: List[EvalResult] = []
        for result in self._run_iteration(pending, tasks):
            self._append_result(result)
            results.append(result)
        self._generate_summary(results)
        self.post_eval_hook(results)
        return 0

    def _resume_skip_set(self) -> Set[str]:
        path = self.results_path()
        if not path.exists():
            return set()
        seen: Set[str] = set()
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                tid = record.get("task_id")
                if isinstance(tid, str):
                    seen.add(tid)
        return seen

    def _append_result(self, result: EvalResult) -> None:
        with open(self.results_path(), "a", encoding="utf-8") as fh:
            fh.write(json.dumps(result.model_dump(mode="json"), ensure_ascii=False) + "\n")

    def _generate_summary(self, results: List[EvalResult]) -> None:
        records = [r.model_dump(mode="json") for r in results]
        summary = generate_evaluation_summary(records, len(records))
        usages = []
        for record in records:
            details = record.get("evaluation_details") or {}
            usage = details.get("eval_usage")
            if usage:
                usages.append(usage)
        cost_summary = aggregate_evaluation_costs(usages)
        if cost_summary:
            summary["evaluation_cost"] = cost_summary
        summary["evaluation_config"] = {
            "mode": self.args.mode,
            "model": self.args.model,
            "trajectories_dir": str(self.args.trajectories_dir),
            "output_path": str(self.args.output_path),
        }
        with open(self.summary_path(), "w", encoding="utf-8") as fh:
            json.dump(summary, fh, ensure_ascii=False, indent=2)
        logger.info("Summary written to %s", self.summary_path())
```

- [ ] **Step 4: Run — 测试通过**

```bash
uv run pytest tests/browseruse_bench/test_eval_base.py -v
```
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add browseruse_bench/eval/base.py tests/browseruse_bench/test_eval_base.py
git commit -m "feat(eval): add BaseEvaluator + EvaluatorArgs scaffolding"
```

---

## Task 7: BaseEvaluator.run() 编排顺序测试

**Files:**
- Modify: `tests/browseruse_bench/test_eval_base.py`

- [ ] **Step 1: 增加 fake 子类测试，验证 run() 调用顺序**

追加到 `test_eval_base.py`:
```python
def _make_args(tmp_path: Path) -> EvaluatorArgs:
    traj = tmp_path / "tasks"
    traj.mkdir()
    out = tmp_path / "out"
    out.mkdir()
    return EvaluatorArgs(
        benchmark="Fake",
        model="fake-model",
        api_key="x",
        base_url=None,
        trajectories_dir=traj,
        output_path=out,
        score_threshold=None,
        num_worker=1,
        temperature=None,
        split="All",
        data_source="local",
        mode="fake_mode",
    )


class _FakeEvaluator(BaseEvaluator):
    name = "Fake"
    default_mode = "fake_mode"

    def __init__(self, args, model, tasks):
        super().__init__(args, model)
        self._tasks = tasks
        self.calls = []

    def load_tasks(self):
        self.calls.append("load_tasks")
        return self._tasks

    def evaluate_one(self, task_id, task, agent_result, trajectory_dir):
        self.calls.append(f"evaluate:{task_id}")
        from browseruse_bench.schemas import (
            AgentResultRef, EvalDetails, EvalResult,
        )
        from datetime import datetime, timezone
        return EvalResult(
            task_id=task_id,
            task=task.get("desc", ""),
            timestamp=datetime.now(timezone.utc),
            agent_result_ref=AgentResultRef(
                task_id=task_id,
                timestamp=datetime.now(timezone.utc),
                result_dir=str(trajectory_dir),
                model_id="",
                browser_id="",
            ),
            predicted_label=1,
            model_id="",
            browser_id="",
            evaluation_details=EvalDetails(response="ok"),
        )

    def post_eval_hook(self, results):
        self.calls.append(f"post_hook:{len(results)}")


def test_run_orchestration_order(tmp_path):
    args = _make_args(tmp_path)
    # seed two task dirs with result.json
    for tid in ("t1", "t2"):
        d = args.trajectories_dir / tid
        d.mkdir()
        (d / "result.json").write_text('{"task": "demo"}', encoding="utf-8")
    tasks = {"t1": {"desc": "task one"}, "t2": {"desc": "task two"}}
    ev = _FakeEvaluator(args, model=None, tasks=tasks)
    assert ev.run() == 0
    assert ev.calls[0] == "load_tasks"
    assert "evaluate:t1" in ev.calls
    assert "evaluate:t2" in ev.calls
    assert ev.calls[-1] == "post_hook:2"
    assert ev.results_path().exists()
    assert ev.summary_path().exists()


def test_run_resumes_already_evaluated(tmp_path):
    args = _make_args(tmp_path)
    for tid in ("t1", "t2"):
        d = args.trajectories_dir / tid
        d.mkdir()
        (d / "result.json").write_text('{"task": "demo"}', encoding="utf-8")
    # Pre-write a result for t1 to trigger resume skip
    args.output_path.mkdir(exist_ok=True)
    out = args.output_path / "Fake_fake-model_results.json"
    out.write_text('{"task_id": "t1"}\n', encoding="utf-8")
    tasks = {"t1": {"desc": "one"}, "t2": {"desc": "two"}}
    ev = _FakeEvaluator(args, model=None, tasks=tasks)
    ev.run()
    assert "evaluate:t1" not in ev.calls
    assert "evaluate:t2" in ev.calls
```

- [ ] **Step 2: Run**

```bash
uv run pytest tests/browseruse_bench/test_eval_base.py -v
```
Expected: PASS

- [ ] **Step 3: 提交**

```bash
git add tests/browseruse_bench/test_eval_base.py
git commit -m "test(eval): cover BaseEvaluator orchestration + resume"
```

---

## Task 8: Registry 实现 + 测试

**Files:**
- Create: `browseruse_bench/eval/registry.py`
- Create: `tests/browseruse_bench/test_eval_registry.py`

- [ ] **Step 1: 写失败测试**

`tests/browseruse_bench/test_eval_registry.py`:
```python
"""Tests for evaluator registry."""
from __future__ import annotations

import pytest

from browseruse_bench.eval.base import BaseEvaluator
from browseruse_bench.eval.registry import (
    get_evaluator_class,
    list_evaluators,
    register_evaluator,
)


class _Stub(BaseEvaluator):
    name = "Stub-Bench"
    default_mode = "stub_mode"

    def load_tasks(self):
        return {}

    def evaluate_one(self, *args, **kwargs):
        raise NotImplementedError


def test_register_and_get():
    @register_evaluator("Stub-Bench")
    def _factory():
        return _Stub

    cls = get_evaluator_class("Stub-Bench")
    assert cls is _Stub
    assert "Stub-Bench" in list_evaluators()


def test_unknown_raises():
    with pytest.raises(KeyError):
        get_evaluator_class("Definitely-Not-Registered")
```

- [ ] **Step 2: Run — FAIL**

```bash
uv run pytest tests/browseruse_bench/test_eval_registry.py -v
```
Expected: FAIL

- [ ] **Step 3: 实现**

`browseruse_bench/eval/registry.py`:
```python
"""Registry mapping benchmark name -> evaluator class via lazy factories.

Modeled on browseruse_bench/browsers/registry.py: factory closures perform
function-local imports so that subpackage SDKs (OpenAI, PIL) load only when
the corresponding benchmark is used.
"""
from __future__ import annotations

from typing import Callable, Dict, List, Type

from browseruse_bench.eval.base import BaseEvaluator

_FACTORIES: Dict[str, Callable[[], Type[BaseEvaluator]]] = {}


def register_evaluator(name: str) -> Callable[[Callable[[], Type[BaseEvaluator]]], Callable[[], Type[BaseEvaluator]]]:
    """Decorator: bind a factory closure under the given benchmark name."""

    def decorator(factory: Callable[[], Type[BaseEvaluator]]) -> Callable[[], Type[BaseEvaluator]]:
        _FACTORIES[name] = factory
        return factory

    return decorator


def get_evaluator_class(name: str) -> Type[BaseEvaluator]:
    if name not in _FACTORIES:
        raise KeyError(
            f"Unknown evaluator: {name}. Registered: {sorted(_FACTORIES)}"
        )
    return _FACTORIES[name]()


def list_evaluators() -> List[str]:
    return sorted(_FACTORIES)


def _register_defaults() -> None:
    """Bind built-in benchmarks. Called at module import time."""

    @register_evaluator("Online-Mind2Web")
    def _online_mind2web():
        from browseruse_bench.eval.online_mind2web.evaluator import OnlineMind2WebEvaluator
        return OnlineMind2WebEvaluator

    @register_evaluator("BrowseComp")
    def _browse_comp():
        from browseruse_bench.eval.browse_comp.evaluator import BrowseCompEvaluator
        return BrowseCompEvaluator

    @register_evaluator("LexBench-Browser")
    def _lexbench():
        from browseruse_bench.eval.lexbench_browser.evaluator import LexBenchBrowserEvaluator
        return LexBenchBrowserEvaluator


_register_defaults()
```

注：默认注册仅做闭包绑定，不真正 import 子包；子包 import 发生在 `get_evaluator_class()` 第一次被调用时。

- [ ] **Step 4: Run**

```bash
uv run pytest tests/browseruse_bench/test_eval_registry.py -v
```
Expected: PASS（注：在 Task 9-11 完成之前，对 `Online-Mind2Web` 等 builtin 名调用 `get_evaluator_class` 会因子包不存在而 ImportError；只测 `Stub-Bench`）

- [ ] **Step 5: 提交**

```bash
git add browseruse_bench/eval/registry.py tests/browseruse_bench/test_eval_registry.py
git commit -m "feat(eval): add evaluator registry with lazy factory pattern"
```

---

## Task 9: Online-Mind2Web 子包迁移 + smoke

**Files:**
- Move: `benchmarks/Online-Mind2Web/eval/src/{webjudge_online_mind2web.py,utils.py}` → `browseruse_bench/eval/online_mind2web/{webjudge.py,utils.py}`
- Create: `browseruse_bench/eval/online_mind2web/__init__.py`
- Create: `browseruse_bench/eval/online_mind2web/evaluator.py`

- [ ] **Step 1: 创建子包目录并迁移 judge helper**

```bash
mkdir -p browseruse_bench/eval/online_mind2web
git mv benchmarks/Online-Mind2Web/eval/src/webjudge_online_mind2web.py browseruse_bench/eval/online_mind2web/webjudge.py
git mv benchmarks/Online-Mind2Web/eval/src/utils.py browseruse_bench/eval/online_mind2web/utils.py
```

- [ ] **Step 2: 修复迁移后 import 路径**

`webjudge.py` / `utils.py` 内部的相对 import（如 `from utils import ...`）改为绝对：
```python
from browseruse_bench.eval.online_mind2web.utils import OpenaiEngine, ...
```

`grep -n "^from utils\|^import utils\|^from webjudge_online_mind2web" browseruse_bench/eval/online_mind2web/*.py` 把命中行全部改成绝对路径。

- [ ] **Step 3: 写 `__init__.py`**

```python
"""Online-Mind2Web evaluator subpackage."""
from __future__ import annotations

from browseruse_bench.eval.online_mind2web.evaluator import OnlineMind2WebEvaluator

__all__ = ["OnlineMind2WebEvaluator"]
```

- [ ] **Step 4: 写 `evaluator.py` — 把 `benchmarks/Online-Mind2Web/eval/src/run.py` 的 `auto_eval` / `parallel_eval` / `process_subset` / `_start_progress_monitor` / `generate_summary` 平移进来，包成 `OnlineMind2WebEvaluator(BaseEvaluator)`**

骨架（关键方法签名照抄设计 spec）：
```python
"""OnlineMind2WebEvaluator — Web navigation benchmark with screenshot judging."""
from __future__ import annotations

import asyncio
import copy
import json
import logging
import multiprocessing
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from threading import Event, Thread
from typing import Any, ClassVar, Dict, Iterator, List

from browseruse_bench.eval.base import BaseEvaluator, EvaluatorArgs
from browseruse_bench.eval.model import EvaluationModel
from browseruse_bench.eval.online_mind2web.utils import (
    OpenaiEngine,
    extract_failure_category,
    extract_predication,
    extract_reasoning,
)
from browseruse_bench.eval.online_mind2web.webjudge import WebJudge_Online_Mind2Web_eval
from browseruse_bench.schemas import (
    AgentMetrics,
    AgentResultRef,
    AgentUsage,
    EvalDetails,
    EvalResult,
    EvalUsage,
)

logger = logging.getLogger(__name__)
TASK_ID_PATTERN = re.compile(r'"task_id"\s*:\s*"([^"]+)"')


class OnlineMind2WebEvaluator(BaseEvaluator):
    name: ClassVar[str] = "Online-Mind2Web"
    default_mode: ClassVar[str] = "WebJudge_Online_Mind2Web_eval"

    def results_filename(self) -> str:
        threshold = self.args.score_threshold
        return f"{self.args.mode}_{self.args.model}_score_threshold_{threshold}_auto_eval_results.json"

    def summary_filename(self) -> str:
        threshold = self.args.score_threshold
        return f"{self.args.mode}_{self.args.model}_score_threshold_{threshold}_summary.json"

    def load_tasks(self) -> Dict[str, Dict[str, Any]]:
        # Mind2Web has no external task file; task_id == trajectory directory name.
        return {p.name: {"task_id": p.name} for p in self.list_completed_tasks()}

    def evaluate_one(self, task_id, task, agent_result, trajectory_dir):
        # Inline of original auto_eval per-task body, minus the loop scaffolding.
        # See benchmarks/Online-Mind2Web/eval/src/run.py:117-234 for the original.
        ...  # TODO: copy block

    def _run_iteration(self, pending, tasks):
        # multiprocessing variant: replicate parallel_eval but yield EvalResult
        # via a multiprocessing.Queue rather than appending in worker.
        ...  # TODO: copy + adapt
```

具体迁移：
- 单任务判分逻辑（原 `auto_eval` 的 for-body, [run.py:117-234](../../benchmarks/Online-Mind2Web/eval/src/run.py)）整段移入 `evaluate_one`，去掉 resume 逻辑（基类已统一处理），`output_results` 构建 `EvalResult` 后 return（不再 `f_out.write`）
- `_run_iteration` override 多进程版本：每个 worker 调 `evaluate_one`，通过 `multiprocessing.Queue` 把结果传回主进程，主进程 yield 给基类的 append
- 进度监控线程在 `_run_iteration` 启动 / 终止
- `generate_summary` 自定义统计（success_count）合并进基类 `_generate_summary`：override `_generate_summary` 在 super 之上追加 evaluation_config 字段（`score_threshold` 这类已被基类 generic 化）

⚠️ 注意：worker 函数必须为模块级顶层函数（`multiprocessing` pickling 要求）。原 `process_subset` 已是顶层函数，迁移后保持顶层位置即可。

- [ ] **Step 5: 在 registry 已有的工厂里启用真实 import**

不需要再编辑 — Task 8 的 `_register_defaults` 已经懒加载这个 import；现在子包就位了，第一次调用即可成功。

- [ ] **Step 6: Smoke**

按 [error-handling-testing.md smoke 规则](../../docs_4_codeagent/error-handling-testing.md#smoke-testing-before-commit)：先准备一份已 run 完的 Mind2Web 轨迹（如本地已有），再跑：

```bash
uv run python -c "from browseruse_bench.eval.registry import get_evaluator_class; print(get_evaluator_class('Online-Mind2Web'))"
```
Expected: 输出 `<class 'browseruse_bench.eval.online_mind2web.evaluator.OnlineMind2WebEvaluator'>`

注意：完整 `bubench eval` 的 smoke 在 Task 12（CLI 切换完）后做；本 Task 只验证子包可加载。

- [ ] **Step 7: 提交**

```bash
git add -A
git commit -m "feat(eval): port Online-Mind2Web evaluator into browseruse_bench.eval"
```

---

## Task 10: BrowseComp 子包迁移

**Files:**
- Move: `benchmarks/BrowseComp/eval/src/utils.py` → `browseruse_bench/eval/browse_comp/grader.py`
- Create: `browseruse_bench/eval/browse_comp/{__init__.py, evaluator.py}`

- [ ] **Step 1: 迁文件**

```bash
mkdir -p browseruse_bench/eval/browse_comp
git mv benchmarks/BrowseComp/eval/src/utils.py browseruse_bench/eval/browse_comp/grader.py
```

- [ ] **Step 2: 修 import**

`grader.py` 自身的 import 检查；不依赖兄弟模块。

- [ ] **Step 3: `__init__.py`**

```python
from browseruse_bench.eval.browse_comp.evaluator import BrowseCompEvaluator
__all__ = ["BrowseCompEvaluator"]
```

- [ ] **Step 4: 写 `evaluator.py`**

把 `benchmarks/BrowseComp/eval/src/run.py:run_evaluation` 拆解：
- `load_tasks` 读 `tasks.jsonl` + decrypt → `{task_id: {"question": ..., "correct_answer": ...}}`
- `evaluate_one` 调 `grade_response`，组装 `EvalResult`（与原 [run.py:60-149](../../benchmarks/BrowseComp/eval/src/run.py) 一致）
- `results_filename` 返回 `f"BrowseComp_grader_eval_{model}_results.json"`
- `summary_filename` 返回 `f"BrowseComp_grader_eval_{model}_summary.json"`
- override `_generate_summary` 追加 `browsecomp_metrics: {accuracy, correct, total}`

```python
from browseruse_bench.eval.base import BaseEvaluator
from browseruse_bench.eval.browse_comp.grader import (
    decrypt, grade_response, load_grader_model,
)
from browseruse_bench.utils import REPO_ROOT, load_task_file
# ...

class BrowseCompEvaluator(BaseEvaluator):
    name = "BrowseComp"
    default_mode = "BrowseComp_grader_eval"

    def load_tasks(self):
        tasks_json = REPO_ROOT / "browseruse_bench/data/BrowseComp/tasks.jsonl"
        return {str(t["task_id"]): t for t in load_task_file(tasks_json) if "task_id" in t}

    def evaluate_one(self, task_id, task, agent_result, trajectory_dir):
        question = decrypt(task["encrypted_question"], task["canary"])
        correct = decrypt(task["encrypted_answer"], task["canary"])
        agent_resp = agent_result.get("answer") or agent_result.get("response", "")
        grading = grade_response(question, correct, agent_resp, self.model)
        # ... build EvalResult mirroring original run.py:60-149
```

⚠️ 注意路径：`tasks.jsonl` 在 Task 13 才搬到 `browseruse_bench/data/`；本 Task 暂时写约定路径，但跑 smoke 时如果 Task 13 还没做，要么先指 `benchmarks/BrowseComp/data/tasks.jsonl`，要么把数据迁移挪到本 Task 之前。**实施时把数据迁移合进本 Task 的 Step 0**（见下）。

- [ ] **Step 4.5: 同步迁数据**

```bash
git mv benchmarks/BrowseComp/data browseruse_bench/data/BrowseComp
```

- [ ] **Step 5: 加载验证**

```bash
uv run python -c "from browseruse_bench.eval.browse_comp.evaluator import BrowseCompEvaluator; print(BrowseCompEvaluator.name)"
```
Expected: `BrowseComp`

- [ ] **Step 6: 提交**

```bash
git add -A
git commit -m "feat(eval): port BrowseComp evaluator + relocate dataset"
```

---

## Task 11: LexBench-Browser 子包迁移

**Files:**
- Move:
  - `benchmarks/LexBench-Browser/eval/src/lexmount_eval.py` → `browseruse_bench/eval/lexbench_browser/lexmount_eval.py`
  - `benchmarks/LexBench-Browser/eval/src/screenshot_cleaner.py` → `browseruse_bench/eval/lexbench_browser/screenshot_cleaner.py`
  - `benchmarks/LexBench-Browser/eval/src/add_task_tags.py`、`remove_tags.py` 同上
- Create: `browseruse_bench/eval/lexbench_browser/{__init__.py, evaluator.py}`
- Move: `benchmarks/LexBench-Browser/data/` → `browseruse_bench/data/LexBench-Browser/`

- [ ] **Step 1: 批量迁文件**

```bash
mkdir -p browseruse_bench/eval/lexbench_browser
git mv benchmarks/LexBench-Browser/eval/src/lexmount_eval.py browseruse_bench/eval/lexbench_browser/
git mv benchmarks/LexBench-Browser/eval/src/screenshot_cleaner.py browseruse_bench/eval/lexbench_browser/
git mv benchmarks/LexBench-Browser/eval/src/add_task_tags.py browseruse_bench/eval/lexbench_browser/
git mv benchmarks/LexBench-Browser/eval/src/remove_tags.py browseruse_bench/eval/lexbench_browser/
git mv benchmarks/LexBench-Browser/data browseruse_bench/data/LexBench-Browser
```

- [ ] **Step 2: 修 import**

每个迁过来的文件里的相对 / `from lexmount_eval import` / `from screenshot_cleaner import` 等，改成绝对路径 `browseruse_bench.eval.lexbench_browser.<name>`。

```bash
grep -n "^from \|^import " browseruse_bench/eval/lexbench_browser/*.py | grep -E "lexmount_eval|screenshot_cleaner|add_task_tags|remove_tags"
```
把命中行全部改成 `from browseruse_bench.eval.lexbench_browser.X import ...`

- [ ] **Step 3: `__init__.py`**

```python
from browseruse_bench.eval.lexbench_browser.evaluator import LexBenchBrowserEvaluator
__all__ = ["LexBenchBrowserEvaluator"]
```

- [ ] **Step 4: 写 `evaluator.py`**

迁 `benchmarks/LexBench-Browser/eval/src/run.py` 的 `run_evaluation`、`evaluate_single_task`、`_resolve_split_entry`、`resolve_tasks_file_from_split`、`_ensure_full_results_coverage`、`_build_synthetic_failure_record`、`_write_no_screenshot_result` 等到 `evaluator.py` 内（保持私有方法 `_xxx`）。

骨架：
```python
class LexBenchBrowserEvaluator(BaseEvaluator):
    name = "LexBench-Browser"
    default_mode = "LexBench-Browser_eval"

    def results_filename(self):
        strategy = self.args.extra.get("eval_strategy", "stepwise")
        # 现状: f"{dataset_name}_{model}_per_task_threshold_{strategy}_eval_results.json"
        # dataset_name 由 split 解析得到
        ...

    def load_tasks(self):
        # 复用 utils.load_data_info / load_dataset_file 解析 split → tasks
        # 数据根: REPO_ROOT / "browseruse_bench/data/LexBench-Browser"
        ...

    def evaluate_one(self, task_id, task, agent_result, trajectory_dir):
        # 调 lexmount_eval.evaluate_task; 转 EvalResult
        ...

    def post_eval_hook(self, results):
        from browseruse_bench.eval.lexbench_browser.screenshot_cleaner import clean_screenshots
        clean_screenshots(self.args.trajectories_dir)
        # + coverage 校验、synthetic failure 合成
```

**关键：保留以下 LexBench 私有逻辑，全部为子类内部 `_xxx` 方法，绝不上提**
- `_normalize_task_id`
- `_is_synthetic_not_evaluated_record`
- `_build_synthetic_failure_record`
- `_write_no_screenshot_result`
- `_ensure_full_results_coverage`
- per-task `score_threshold` 取值（从 dataset 读，不用 `self.args.score_threshold`）

- [ ] **Step 5: 验证**

```bash
uv run python -c "from browseruse_bench.eval.lexbench_browser.evaluator import LexBenchBrowserEvaluator; print(LexBenchBrowserEvaluator.name)"
```
Expected: `LexBench-Browser`

- [ ] **Step 6: 提交**

```bash
git add -A
git commit -m "feat(eval): port LexBench-Browser evaluator + relocate dataset"
```

---

## Task 12: 迁移 Online-Mind2Web 数据 + CLI 切换 in-process

**Files:**
- Move: `benchmarks/Online-Mind2Web/data/` → `browseruse_bench/data/Online-Mind2Web/`
- Modify: `browseruse_bench/cli/eval.py`（大幅瘦身）
- Modify: `browseruse_bench/cli/run.py`（路径拼接由约定取代）

- [ ] **Step 1: 迁数据**

```bash
git mv benchmarks/Online-Mind2Web/data browseruse_bench/data/Online-Mind2Web
```

- [ ] **Step 2: 改 `cli/eval.py`**

具体改动：
- 删除 `_run_eval_subprocess` 函数整体
- 删除 `locate_results_file` 函数整体（由 `evaluator.results_path()` 取代）
- `_merge_manifest_into_summary` 内 `if benchmark_name == ...` 三个分支删除，summary 路径改为 `evaluator.summary_path()`
- `run_evaluation` 主体改写：
  ```python
  from browseruse_bench.eval.base import EvaluatorArgs
  from browseruse_bench.eval.registry import get_evaluator_class
  
  evaluator_cls = get_evaluator_class(benchmark_name)
  default_mode = evaluator_cls.default_mode
  # ... 解析 args ...
  evaluator_args = EvaluatorArgs(
      benchmark=benchmark_name, model=model, ...,
      extra={"eval_strategy": eval_strategy, "progress_interval": ...},
  )
  evaluator = evaluator_cls(evaluator_args, model_instance)
  exit_code = evaluator.run()  # in-process
  results_file = evaluator.results_path()
  # 失败分类 + manifest 合并照旧
  ```
- `output_base = REPO_ROOT / "experiments" / benchmark_name`（不再读 `benchmark_config["output_base"]`）
- 删除 `resolve_benchmark_config` 调用

- [ ] **Step 3: 改 `cli/run.py`**

- `cli/run.py:472`：`local_data_path = REPO_ROOT / "browseruse_bench" / "data" / benchmark_name / data_file`
- `cli/run.py:491`：`output_base = REPO_ROOT / "experiments" / benchmark_name / args.split / agent_name / model_id`
- `cli/run.py:125,464`：删 `resolve_benchmark_config(...)` 调用，相关下游 `benchmark_path` 与 `output_base` 改为约定路径
- 删除 `from browseruse_bench.utils import resolve_benchmark_config`

- [ ] **Step 4: 删除 `resolve_benchmark_config`**

`browseruse_bench/utils/config_loader.py` 删除整函数；`browseruse_bench/utils/__init__.py` 删除其 import 与 `__all__` 条目；删除 `tests/browseruse_bench/test_config_loader.py` 中相关用例（grep 确认有哪些）。

- [ ] **Step 5: 三 benchmark smoke**

```bash
uv run bubench eval --agent skyvern --data LexBench-Browser --split L1 \
  --num_worker 1 2>&1 | tee /tmp/smoke_lex.log
uv run bubench eval --agent skyvern --data Online-Mind2Web \
  --num_worker 2 2>&1 | tee /tmp/smoke_o2w.log
uv run bubench eval --agent skyvern --data BrowseComp 2>&1 | tee /tmp/smoke_bc.log
```
Expected: 每条日志中至少看到一行 `Finish evaluation for ...` 或 `[PROGRESS] Evaluated N/M`，且 `evaluator.results_path()` 文件存在并比对名字与历史一致。

报告每条 wall-clock 时间与一行确认 evaluator 真实判分的日志（比照 [error-handling-testing.md](../../docs_4_codeagent/error-handling-testing.md#smoke-testing-before-commit)）。

- [ ] **Step 6: 提交**

```bash
git add -A
git commit -m "refactor(cli): switch eval to in-process registry dispatch; drop subprocess"
```

---

## Task 13: 删除 `benchmarks/` 顶级目录 + 删除 config 中 `benchmarks:` 块

**Files:**
- Delete: 整个 `benchmarks/` 目录
- Modify: `config.example.yaml`（删除 `benchmarks:` 块）
- Modify: `browseruse_bench/utils/data_loader.py:326`（docstring）
- Modify: `browseruse_bench/visualization/generate_index.py:148`（fallback 注释）

- [ ] **Step 1: 检查 `benchmarks/` 是否还有遗留文件**

```bash
find benchmarks -type f 2>/dev/null
```
Expected: 空输出（如果有，需要先迁移；可能是 README 等无害文件，按需 `git mv` 到 `browseruse_bench/data/<X>/` 或删除）

- [ ] **Step 2: 删除目录**

```bash
git rm -r benchmarks
```

- [ ] **Step 3: 删除 `config.example.yaml` 中的 `benchmarks:` 块**

定位 330-344 行（参考 `grep -n "^benchmarks:" config.example.yaml` 与 `grep -n "^# Benchmark Configuration" config.example.yaml`），整段删除。

- [ ] **Step 4: 更新 `data_loader.py` docstring 与 `generate_index.py` 注释**

```bash
sed -i.bak 's|benchmarks/LexBench-Browser/data/tasks.jsonl|browseruse_bench/data/LexBench-Browser/tasks.jsonl|' browseruse_bench/utils/data_loader.py
rm browseruse_bench/utils/data_loader.py.bak
```
`generate_index.py:148` 的注释由人工编辑（注释里的 `benchmarks/` 字面值更新成 `browseruse_bench/data/`）。

- [ ] **Step 5: 全仓 grep 验证无 stragglers**

```bash
git grep -n "benchmarks/" -- ':!*.lock' ':!*.md' | grep -v "^docs_4_codeagent/"
git grep -n "if benchmark_name ==" browseruse_bench/cli/
```
Expected: 第一条仅命中迁移相关历史文档（已 exclude）；第二条空。

- [ ] **Step 6: 跑全测试套件**

```bash
uv run pytest tests/ -v 2>&1 | tail -25
```
Expected: 全 PASS

- [ ] **Step 7: 提交**

```bash
git add -A
git commit -m "refactor(eval): remove benchmarks/ tree and benchmarks: config block"
```

---

## Task 14: 终验 — 三 benchmark 完整 smoke

**Files:** none modified — 只是验证

- [ ] **Step 1: 三 benchmark 各跑一次真实 `bubench eval`，命令同 Task 12 Step 5**

按 [error-handling-testing.md smoke 规则](../../docs_4_codeagent/error-handling-testing.md#smoke-testing-before-commit)：
- 命令、wall-clock、一行子任务真实执行日志
- LexBench: `Skyvern: LLM API handler duration metrics ... model=openai/<id>` + `Task completed task_status=completed`
- Mind2Web: `[PROGRESS] Evaluated N/M tasks` + 至少一条 `Finish evaluation for ...`
- BrowseComp: `[N/M] PASS|FAIL <task_id>` 至少一条

- [ ] **Step 2: 确认输出文件名与历史一致**

每条 smoke 完成后：
```bash
ls experiments/<X>/<split>/<agent>/<model_id>/<latest_ts>/tasks_eval_result/
```
应当看到与重构前同名的 `*_results.json` 与 `*_summary.json`（参照 spec "输出文件名约定"）。

- [ ] **Step 3: leaderboard / viz 回归**

```bash
uv run bubench leaderboard 2>&1 | tail -10
uv run bubench viz 2>&1 | tail -10
```
Expected: 与重构前输出一致（任务/分数条目数、HTML 结构无变化）。

- [ ] **Step 4: 输出验收报告并提交**

如有 README 提及 `benchmarks/` 目录的，更新；否则空 commit 兜底文档：
```bash
git commit --allow-empty -m "test(eval): smoke verified all 3 benchmarks post-refactor"
```

---

## Self-Review Checklist

实施前/后对照设计 spec：

- [x] Layout（`browseruse_bench/{data,eval}/`）—— Task 1, 9-13
- [x] BaseEvaluator + EvaluatorArgs —— Task 6-7
- [x] Registry lazy 工厂 —— Task 8
- [x] 三派生类 + judge helper 同包 —— Task 9, 10, 11
- [x] 输出 legacy 命名约定 —— Task 9-11 各自 `results_filename()` 返回值
- [x] CLI in-process 调用、删除 `if benchmark==X` —— Task 12
- [x] `benchmarks.<X>` config 块整块删除 —— Task 13
- [x] `path` / `output_base` 由约定取代、`default_mode` 提升为 `ClassVar` —— Task 8, 12, 13
- [x] `utils/eval*.py` 留 re-export shim —— Task 2-5
- [x] schema 不动 —— 全计划无 schema 改动
- [x] failure classification 仍由 CLI 后置调用 —— Task 12
- [x] LexBench 私有逻辑保留为子类私有方法 —— Task 11 Step 4 明示
- [x] multiprocessing worker 顶层函数验证 —— Task 9 Step 4 注释
- [x] 单元测试覆盖（base 编排 + resume + registry）—— Task 7, 8
- [x] 三 benchmark 真实 smoke —— Task 12 Step 5, Task 14 Step 1

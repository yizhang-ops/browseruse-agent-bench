# Eval 模块基类化重构设计

日期：2026-04-27
分支：eval-base

## 目标

将三套独立的 benchmark 评测脚本（`benchmarks/<X>/eval/src/run.py`）抽象为
`BaseEvaluator` + 派生类的层次结构，并把整个 benchmark 目录搬入
`browseruse_bench/`，按"代码 / 数据"两层切分。

完成后：
- CLI `cli/eval.py` 不再有 `if benchmark_name == "X"` 分支
- 三份 `run.py` 中重复的 argparse / resume / JSONL 写入 / summary 生成等
  scaffolding 收拢到基类
- Benchmark 间真实差异（任务加载、单任务判分、并发模型、清理钩子）成为
  派生类显式接口
- 评测全部 in-process 运行，CLI → eval 子进程边界消失

## 非目标

- 不改变 `experiments/{benchmark}/{split}/{agent}/{model_id}/{timestamp}/`
  产出目录结构
- 不改变 leaderboard、viz、`schemas/eval_*` 任何对外可见字段
- 不引入新的评测策略，所有 benchmark 行为与现状逐字段一致
- 不改 `EvalResult/EvalDetails/EvalUsage/AgentMetrics/AgentResultRef` schema

## 目录最终形态

```
browseruse_bench/
  data/
    LexBench-Browser/        # 从 benchmarks/LexBench-Browser/data/ 整体 git mv
    Online-Mind2Web/
    BrowseComp/
  eval/
    __init__.py
    base.py                  # BaseEvaluator
    registry.py              # @register_evaluator + lazy factories（仿 browsers/registry.py）
    score.py                 # extract_score_from_response, calculate_success
    model.py                 # EvaluationModel, load_evaluation_model
    summary.py               # generate_evaluation_summary, aggregate_evaluation_costs,
                             # normalized_results_file, calculate_evaluation_cost
    failure.py               # classify_failures_batch（从 utils/eval_failure.py 整体迁入）
    online_mind2web/
      __init__.py            # 导出并 register
      evaluator.py           # OnlineMind2WebEvaluator
      webjudge.py            # WebJudge_Online_Mind2Web_eval + 内部 helper
      utils.py               # OpenaiEngine, extract_predication, extract_failure_category 等
    browse_comp/
      __init__.py
      evaluator.py
      grader.py              # decrypt + grade_response + load_grader_model
    lexbench_browser/
      __init__.py
      evaluator.py
      lexmount_eval.py
      screenshot_cleaner.py
      add_task_tags.py
      remove_tags.py
```

`benchmarks/` 顶级目录被删除。`utils/eval.py`、`utils/eval_failure.py`
内容迁入 `eval/` 子模块；`utils/__init__.py` 留 re-export shim 维持
`from browseruse_bench.utils import load_evaluation_model` 等历史 import
路径在过渡期内可用。

## BaseEvaluator 接口

```python
@dataclass
class EvaluatorArgs:
    benchmark: str
    model: str
    api_key: str
    base_url: str | None
    trajectories_dir: Path
    output_path: Path
    score_threshold: int | None
    num_worker: int
    temperature: float | None
    split: str
    data_source: str
    mode: str
    extra: dict[str, Any]      # benchmark 私有字段（如 LexBench eval_strategy、Mind2Web progress_interval）


class BaseEvaluator(ABC):
    name: ClassVar[str]                         # 注册键（与 benchmark 名一致）
    default_mode: ClassVar[str]                 # CLI --mode 缺省值（替代 config.default_mode）

    def __init__(self, args: EvaluatorArgs, model: EvaluationModel):
        self.args = args
        self.model = model

    # ---- 子类必须实现 ----
    @abstractmethod
    def load_tasks(self) -> dict[str, dict]:                # task_id -> task data
        ...

    @abstractmethod
    def evaluate_one(self, task_id: str, task: dict,
                     agent_result: dict, trajectory_dir: Path) -> EvalResult:
        ...

    # ---- 子类按需 override（基类提供默认） ----
    def list_completed_tasks(self) -> list[Path]:
        """默认：扫 trajectories_dir 下含 result.json 的子目录。"""

    def results_filename(self) -> str:
        """子类返回 legacy 名，保持文件路径与现状一致。"""

    def summary_filename(self) -> str: ...

    def post_eval_hook(self, results: list[EvalResult]) -> None:
        """默认 no-op。LexBench 用于 clean_screenshots、coverage 校验等。"""

    def _run_iteration(self, pending: list[str],
                       tasks: dict[str, dict]) -> Iterator[EvalResult]:
        """默认串行 + 进度日志。Mind2Web override 走 multiprocessing。"""

    # ---- 基类 final 编排（子类不应 override） ----
    def run(self) -> int:
        tasks = self.load_tasks()
        completed = self.list_completed_tasks()
        already = self._resume_skip_set()
        pending = [p.name for p in completed if p.name not in already and p.name in tasks]
        results: list[EvalResult] = []
        for result in self._run_iteration(pending, tasks):
            self._append_result(result)
            results.append(result)
        self._generate_summary(results)
        self.post_eval_hook(results)
        return 0

    def _resume_skip_set(self) -> set[str]: ...
    def _append_result(self, result: EvalResult) -> None: ...
    def _generate_summary(self, results: list[EvalResult]) -> None: ...
```

`EvaluatorArgs.extra` 用作"派生类私有 CLI 字段"的逃生口，避免基类签名持续
膨胀。LexBench 的 `eval_strategy`、Mind2Web 的 `progress_interval` 都进
`extra`。

`run()` 是基类的 final scaffolding：resume → 迭代 → JSONL append → summary
→ 后置钩子。子类只负责"怎么把任务加载出来"和"怎么判一个任务"。

## Registry

仿 `browsers/registry.py`：模块级字典 + 装饰器 + lazy 工厂。注册表自身只
持有工厂闭包，不在导入期触发任何 SDK import。

```python
# eval/registry.py
_FACTORIES: dict[str, Callable[[], type[BaseEvaluator]]] = {}

def register_evaluator(name: str):
    def decorator(factory):
        _FACTORIES[name] = factory
        return factory
    return decorator

def get_evaluator_class(name: str) -> type[BaseEvaluator]:
    if name not in _FACTORIES:
        raise KeyError(f"Unknown evaluator: {name}. Registered: {sorted(_FACTORIES)}")
    return _FACTORIES[name]()


@register_evaluator("Online-Mind2Web")
def _online_mind2web_factory():
    from browseruse_bench.eval.online_mind2web.evaluator import OnlineMind2WebEvaluator
    return OnlineMind2WebEvaluator


@register_evaluator("BrowseComp")
def _browse_comp_factory():
    from browseruse_bench.eval.browse_comp.evaluator import BrowseCompEvaluator
    return BrowseCompEvaluator


@register_evaluator("LexBench-Browser")
def _lexbench_factory():
    from browseruse_bench.eval.lexbench_browser.evaluator import LexBenchBrowserEvaluator
    return LexBenchBrowserEvaluator
```

## 派生类职责一览

| Benchmark | 任务加载 | 单任务评测 | 通过判定 | 并发 | 后置钩子 |
|-----------|----------|------------|----------|------|----------|
| Online-Mind2Web | 直接以轨迹目录名为 task_id（无外部任务文件） | `WebJudge_Online_Mind2Web_eval` over screenshots | `extract_predication` | `multiprocessing.Process` + 进度监控线程 | 无 |
| BrowseComp | `tasks.jsonl` + `decrypt(question, answer)` | `grade_response(question, answer, agent_response)` 纯文本 | `is_correct` 布尔 | 串行 | 无 |
| LexBench-Browser | `split` → 任务文件解析 + per-task `score_threshold` | `evaluate_task` (stepwise / holistic) | `calculate_success(score, per_task_threshold)` | 串行 | `clean_screenshots`、coverage 校验、合成 not-evaluated 失败记录 |

## 输出文件名约定

保留 legacy 命名，藏到 `subclass.results_filename()` / `summary_filename()`
后面：

- Online-Mind2Web: `{mode}_{model}_score_threshold_{threshold}_auto_eval_results.json`
  / `..._summary.json`
- BrowseComp: `BrowseComp_grader_eval_{model}_results.json` / `..._summary.json`
- LexBench-Browser: `*_{model}_per_task_threshold_{strategy}_eval_results.json` /
  `..._summary.json`（dataset_name 前缀沿用现有写法）

`experiments/` 历史目录、leaderboard 扫描器、viz 生成器全部 zero-touch。

## CLI 调用路径变化

`browseruse_bench/cli/eval.py`：

- `_run_eval_subprocess`：删除
- `locate_results_file` / `_merge_manifest_into_summary`：删除其中所有
  `if benchmark_name == "X"` 分支，改为
  `evaluator = get_evaluator_class(name)(args, model); path = evaluator.results_path()`
- `run_evaluation`：解析 args → 实例化 evaluator → `evaluator.run()` →
  CLI 继续调 `classify_failures_batch` 做后置失败分类与 manifest 合并
- `eval.log`：改成基类 logger 的 `FileHandler`，去掉 subprocess tee

CLI 仍然负责：参数解析、定位 `trajectories_dir`、`active_model` 解析、
失败分类后置步骤、manifest 写入。`evaluator.run()` 只负责"判分阶段"。

## 配置变更

`config.yaml` 中 `benchmarks.<X>` 整块**彻底删除**。四个字段全部由约定 / 代码取代：

| 字段 | 重构前用途 | 重构后处置 |
|------|------------|------------|
| `path` | (a) 拼 `<path>/<evaluation_script>` 起 subprocess；(b) 数据加载根 `<path>/data/<file>` | 用途 (a) 消失；用途 (b) 由约定 `REPO_ROOT/browseruse_bench/data/<benchmark_name>/<file>` 取代 |
| `evaluation_script` | CLI 起 eval 子进程的脚本相对路径 | 整字段消失 |
| `output_base` | 实验产出根 `<output_base>/<split>/<agent>/<model_id>/...` | 由约定 `REPO_ROOT/experiments/<benchmark_name>/...` 取代（现状三个 benchmark 全部就是该值，从未被外部 override） |
| `default_mode` | `--mode` 缺省值 | 提升为 `BaseEvaluator.default_mode: ClassVar[str]`，子类覆盖；CLI 从 evaluator 类读 |

`utils/config_loader.py::resolve_benchmark_config` 函数与 `utils/__init__.py`
里的 re-export 一并删除；`cli/run.py` 与 `cli/eval.py` 中 `benchmark_config[...]`
索引全部改为读约定路径或 evaluator 类属性。

具体改动点：

- `cli/eval.py`：删除 `resolve_benchmark_config` 调用、`eval_script` 拼接与
  subprocess 启动整段；`output_base` 改为 `REPO_ROOT / "experiments" / benchmark_name`；
  `default_mode` 改为 `evaluator_cls.default_mode`
- `cli/run.py`：所有 `benchmark_config["path"] / "data" / file` 改为
  `REPO_ROOT / "browseruse_bench" / "data" / benchmark_name / file`；
  `benchmark_config["output_base"]` 改为 `REPO_ROOT / "experiments" / benchmark_name`
- `config.example.yaml`：删除 `benchmarks:` 顶层块（连同三个子块）
- `utils/data_loader.py:326` docstring、`visualization/generate_index.py:148`
  fallback 注释里的 `benchmarks/...` 字面引用同步更新

新增 benchmark 的成本归零：只需在 `browseruse_bench/eval/<pkg>/evaluator.py`
里写一个 `BaseEvaluator` 子类、在 `eval/registry.py` 注册，再放数据到
`browseruse_bench/data/<name>/`。无需再编辑任何配置。

## 并发策略

不引入新的并发抽象。`BaseEvaluator._run_iteration` 默认串行 + 行内进度
日志。`OnlineMind2WebEvaluator` override 该方法，沿用现有
`multiprocessing.Process` + 共享 list + 后台进度监控线程模式，整段从
`benchmarks/Online-Mind2Web/eval/src/run.py` 的 `parallel_eval`/
`process_subset` 平移到 `online_mind2web/evaluator.py`。

确认 worker 函数从 `__main__` 模块迁移到子包模块后仍然 picklable
（顶层函数 + 通过 `args` 传 model 配置而非 model 实例，与现状一致）。

## eval_failure 与 schemas 归属

- `utils/eval_failure.py` → `eval/failure.py`：`classify_failures_batch`
  在 CLI 后置步骤中由 `cli/eval.py` 直接调用，不进 `BaseEvaluator.run()`
  生命周期（保持当前职责切分）
- `schemas/eval_result.py`、`schemas/eval_summary.py`：留在 `schemas/`
  不动。它们是跨模块共享的纯数据形状（leaderboard、viz 也消费），不属于
  eval 模块私有

## 迁移顺序

1. 建 `browseruse_bench/eval/` 骨架：`base.py`、`registry.py`、`score.py`、
   `model.py`、`summary.py`、`failure.py`（内容从 `utils/eval.py` /
   `utils/eval_failure.py` 抽出 + `utils/` 下留 re-export shim）
2. 建 `browseruse_bench/data/` 目录，`git mv benchmarks/<X>/data/*` 三个
   benchmark 数据
3. 逐 benchmark 建子包并迁移：
   - `git mv benchmarks/<X>/eval/src/*.py browseruse_bench/eval/<pkg>/`
   - 写 `evaluator.py`：从原 `run.py` 抽 orchestration 进派生类，judge
     helper 文件路径不变（仅同包内 import）
   - 跑 `bubench eval --agent <agent> --data <X>` 真实 smoke（参考
     [error-handling-testing.md 中的 smoke 规则](../../docs_4_codeagent/error-handling-testing.md#smoke-testing-before-commit)）
4. 删除 `benchmarks/` 顶级目录
5. 更新 `config.example.yaml`、`utils/data_loader.py`、`visualization/
   generate_index.py` 中 benchmark 路径引用
6. CLI `cli/eval.py` 收尾：删 subprocess + 各 benchmark 分支，统一走 registry

每一步都保持仓库可运行、`pytest tests/` 通过；`benchmarks/` 删除放最后，
留出回退余地。

## 风险与缓解

- **`multiprocessing` worker pickling**：worker 函数从 `__main__` 移到子包
  后必须仍然顶层定义；通过 `args` 传 model 配置（dict / dataclass），不
  传 model 实例。Smoke 时跑一次 Mind2Web 多 worker 路径验证。
- **OpenAI / PIL / backoff 依赖**：原本由 `.venv` 里子进程加载；改 in-process
  后由 CLI 进程直接 import。这些依赖在 `.venv` 已存在（`utils/eval.py`
  现状已 import），不需要新 extras。
- **第三方脚本 import**：仓库外部脚本可能 import 过
  `from browseruse_bench.utils import load_evaluation_model` 等。`utils/`
  保留 re-export shim 至少一个版本周期，shim 内部转发到 `eval/` 真实实现。
- **历史 `experiments/` 目录解析**：所有文件名沿用 legacy 约定，`subclass.
  results_filename()` 方法返回值与原 `run.py` 字面一致；leaderboard 与 viz
  扫描逻辑不需修改。
- **LexBench 复杂私有逻辑**（`_ensure_full_results_coverage`、
  `_build_synthetic_failure_record`、`_write_no_screenshot_result`）保留
  为 `LexBenchBrowserEvaluator` 私有方法，不上提到基类。

## 验收标准

- `pytest tests/` 全绿
- 三 benchmark 各跑一次真实 `bubench eval` smoke（Mind2Web 与 BrowseComp
  用 `--mode single`，LexBench 用 `--split L1`），日志中观察到子任务真实
  评测行（`[PROGRESS] Evaluated N/M`、`Finish evaluation for ...`），输出
  文件名与现状一致
- `cli/eval.py` 中 `if benchmark_name ==` 字符串出现次数为 0
- `git grep "benchmarks/" browseruse_bench/` 仅命中迁移后必须保留的字面
  引用（不应有；若有则更新）
- Leaderboard、viz 在迁移前后扫描结果一致

# Custom Agent Integration References

## Repo Docs
- docs/en/agents/custom-agent.mdx
- docs/zh/agents/custom-agent.mdx

## BaseAgent.run_task
- Signature: `(task_info, agent_config, task_workspace) -> AgentResult`
- Return `AgentResult` (preferred); plain dict is tolerated by the runner but not recommended
- Required fields: `task_id`, `timestamp`, `env_status`, `agent_done`, `metrics`
- `agent_success` must be `None` when `agent_done != "done"`
- `task_workspace` is the per-task output directory; save artifacts there
- Register with `@register_agent` and import the module in `browseruse_bench/agents/__init__.py`

## BaseAgent Helper Methods
Defined in `browseruse_bench/agents/base.py`. Prefer these over raw `agent_config.get(...)`:

| Helper | Key aliases resolved | Default |
|--------|---------------------|---------|
| `self.get_model_id(agent_config)` | `model_id` | `None` |
| `self.get_timeout(agent_config)` | `timeout`, `timeout_seconds` | `600` |
| `self.get_max_steps(agent_config)` | `max_steps`, `max_turns` | `25` |
| `self.get_api_key(agent_config, env_var=...)` | `api_key`, else env fallback | `None` |
| `self.get_base_url(agent_config, env_var=...)` | `base_url`, else env fallback | `None` |
| `self.build_task_prompt(task_info)` | combines `confirmed_task` + `website` | task string |

For agent-specific flags (e.g. `use_vision`, `flash_mode`), use `agent_config.get("flag_name")` directly.

## CLIAgent (subprocess agents)
Inherit from `browseruse_bench.agents.cli_agent.CLIAgent` instead of `BaseAgent` when the agent ships as an external executable. Inherits all `BaseAgent` helpers plus:

- `self._run_subprocess(cmd, timeout, task_workspace, ...)` → `(returncode, stdout_lines, execution_error)`
  - drains stdout/stderr into `task_workspace/stdout.log` / `stderr.log`
  - handles timeout: SIGTERM → 10s grace → SIGKILL; returns `execution_error="Timeout after Ns"`
  - raises `FileNotFoundError` if the executable is missing (catch and return `env_status="failed", agent_done="error"`)
- `self._map_exit_status(returncode, execution_error)` → `(env_status, agent_done)`
  - `("success", "timeout")` when `execution_error` contains `Timeout`
  - `("failed", "error")` when `returncode != 0` or other error
  - `("success", "done")` otherwise

Reference implementations: `browseruse_bench/agents/agent_tars.py`, `browseruse_bench/agents/claude_code.py`.

## Optional Import Guard Pattern
In `browseruse_bench/agents/__init__.py`, always guard new agent imports so that missing SDK dependencies do not break the entire registry:

```python
try:
    from browseruse_bench.agents import <agent_module>  # noqa: F401
except (ModuleNotFoundError, ImportError):
    pass
```

Catch both `ModuleNotFoundError` (missing top-level package) and `ImportError` (broken submodule / version mismatch on dependent SDKs) — some SDKs like `google-generativeai` raise the latter when an indirect dep is missing.

## SDK Exception Handling
Generic exception handling (`RuntimeError`, `OSError`, `ValueError`, `TimeoutError`) is **not sufficient** for SDK-based agents. Explicitly catch the SDK's base API exception class first:

```python
import openai as openai_mod
# or: from anthropic import APIError as AnthropicAPIError

try:
    # SDK calls
    ...
except openai_mod.APIError as exc:   # 401, 429, bad_request, etc.
    error_msg = f"OpenAI API error: {exc}"
    logger.error("Task %s OpenAI API error: %s", task_id, exc)
except (asyncio.TimeoutError, TimeoutError):
    error_msg = f"Timeout after {timeout} seconds"
except (RuntimeError, OSError, ValueError) as exc:
    error_msg = str(exc)
    logger.error("Task %s error: %s", task_id, exc)
```

Check the SDK's exception hierarchy (usually `<sdk>.APIError` or `<sdk>.Error` as the base class) and catch the broadest SDK-specific class. Without this, authentication / rate-limit errors propagate to the task runner and `result.json` is never written.

## AgentResult Validation Rules
`AgentResult` uses `extra="forbid"`. Unknown fields cause Pydantic validation errors.

`model_validator` constraints:
- `agent_success` MUST be `None` when `agent_done != "done"`
- `error` MUST be `None` when `env_status == "success"` AND `agent_done == "done"`
- `env_status`: `"success"` or `"failed"`
- `agent_done`: `"done"`, `"timeout"`, `"max_steps"`, `"error"`

Canonical status-setting block (use at end of `run_task` / `_run_task_async`):

```python
if error_msg and "Timeout" in error_msg:
    env_status, agent_done = "success", "timeout"
elif error_msg:
    env_status, agent_done = "failed", "error"
elif steps >= max_steps:
    env_status, agent_done = "success", "max_steps"
else:
    env_status, agent_done = "success", "done"

agent_success = None
if agent_done == "done":
    agent_success = bool(final_answer)
```

## Root config.yaml Agent Entry Shape
```yaml
agents:
  <agent-name>:
    path: browseruse_bench/agents
    entrypoint: browseruse_bench/runner/agent_runner.py
    supported_benchmarks:
      - Online-Mind2Web
    venv: .venv
```

## Browser Backend Contract (for browser agents)
- Use `open_browser_session(...)` from `browseruse_bench.browsers` in agent `run_task`.
- Keep provider lifecycle code in `browseruse_bench/browsers/providers/*.py`.
- Consume `BrowserSessionContext` (`backend_id`, `transport`, `cdp_url`, `metadata`) in agent runtime logic.
- Provider optional dependency imports must be `ImportError`-safe; fail only when selected backend is used.
- `close(...)` cleanup failures should be logged and tolerated (must not mask task execution errors).

## New Browser Backend Checklist
1. Add `browseruse_bench/browsers/providers/<provider>.py`.
2. Register `browser_id` in `browseruse_bench/browsers/registry.py`.
3. Add tests in `tests/browseruse_bench/test_browsers.py` (open success, missing dependency/credential, cleanup failure tolerated).
4. Update docs and example config for new keys/browser id.
5. Update optional dependencies (`pyproject.toml`, agent extra mapping in `browseruse_bench/cli/run.py`) when needed.

## Config Path Handling
- Store file paths in config as relative paths
- Resolve to absolute paths with REPO_ROOT when reading

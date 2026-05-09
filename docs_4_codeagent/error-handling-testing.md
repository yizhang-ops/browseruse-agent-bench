# Error Handling and Testing

## Logging

- Do not use `print()` for logging.
- Use `logger`.
- Keep log messages concise, professional, and in English.
- Include necessary context IDs when available.

## Exception Handling

- Do not use bare `except:`.
- Do not use `except Exception:`.
- Catch specific exceptions (for example `TimeoutError`, `ValueError`).
- Do not use `pass` to silently ignore errors.
- At minimum, log failures at `ERROR` level when handling exceptions.

## Testing

- Every behavior-changing PR must include or update targeted tests.
- Prioritize changed behavior and risky edge cases over trivial getters/setters.
- Do not overwrite local state (files/config/DB) implicitly in tests.
- Use fixtures or temporary directories for isolated test state.
- Default command: `uv run pytest tests/`.

## Smoke Testing Before Commit

Before committing a change that touches an agent's runtime path — typically `browseruse_bench/agents/<agent>.py`, `browseruse_bench/utils/config_loader.py`, `config.example.yaml`, or an agent's config keys — run a **real end-to-end** `bubench run` for each affected agent. `pytest` and `--dry-run` are not smoke tests: they skip the config → env-var → subprocess → live-agent path where most integration regressions actually land.

- Target command: `bubench run --agent <agent> --data LexBench-Browser --mode single`.
  - The shipped `task.jsonl` is dominated by tasks with `login_required=false`, so `--mode single` reliably lands on a non-login-gated task and the agent subprocess actually boots.
  - A small number of records still have `login_required=true`. If you smoke-test a specific id, pick a non-login one to avoid `[LOGIN-CTX] No login context for site=...` early-exit.
- Verify by log, not exit code. Confirm the subprocess did real work:
  - Skyvern: `LLM API handler duration metrics ... model=openai/<model_id>` and `Task completed task_status=completed`.
  - Other agents: the equivalent model-call and task-complete lines.
  - If the outer bench reports success but the subprocess log is empty, the run proved nothing.
- For legacy-key back-compat changes, run twice: once with the new key, once with the legacy key. Confirm the deprecation warning fires only on the legacy path.
- Shared-config changes (e.g. `config_loader.py`) must smoke-test every affected agent.
- If the diff provably cannot affect the launch path (pure docs, or a rename with mechanically verified equivalence), skip and say so explicitly. Be cautious — rename-style diffs can hide behavior changes.
- Report command, wall-clock duration, and one log line proving real subprocess work in the same turn as the commit.

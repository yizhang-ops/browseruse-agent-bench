# Architecture and Boundaries

## Layer Responsibilities

- Agent layer handles orchestration and control flow only.
- Provider layer encapsulates SDK/API details behind a uniform interface.
- Base/registry layer owns shared contracts, abstract base classes, and type definitions.
- Do not leak provider implementation details into agent orchestration code.
- Put shared fields and initialization in base classes; subclasses should call `super().__init__(...)`.

## Deduplication

- Extract repeated stable logic into shared helpers/functions.
- Avoid one-off abstractions that add indirection without reuse.

## Optional Dependency Architecture

- Registry/router should lazy-load provider factories to avoid startup failures from unselected providers.
- Provider modules should import dependencies directly and fail fast when selected.
- Do not add provider-level startup workarounds that hide dependency issues.

## Optional Dependency Import Rules

- Only tolerate package-not-installed errors (`ModuleNotFoundError` for the target package itself).
- Re-raise interface, attribute, or submodule errors; do not silently fall back.
- Use a single minimal import guard only when required.
- Do not chain nested import fallbacks.
- Do not create fallback SDK exception classes unless a confirmed runtime contract requires it.
- For provider/integration modules, do not add module-level optional-import `try/except` for SDK availability.
- Isolate optional SDK handling in the upper routing layer via lazy-loading factories.
- Avoid `None` sentinels and scattered runtime dependency checks in providers.

## Cleanup Path Exception Rules

- Cleanup paths may catch recoverable external/runtime failures (for example `ConnectionError`, `OSError`, `TimeoutError`, SDK runtime errors).
- Do not catch programming/interface errors in cleanup code by default (for example `AttributeError`, `TypeError`, `ValueError`).
- If cleanup fails, log once and continue.
- Do not add layered retries/branches unless explicitly required.

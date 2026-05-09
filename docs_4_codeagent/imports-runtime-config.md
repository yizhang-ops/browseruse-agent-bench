# Imports, Runtime, and Configuration

## Imports

- Follow PEP 8 import ordering: standard library, third-party libraries, then local modules.
- Separate import groups with a blank line.
- Keep imports at the top of the file.
- Do not place imports inside functions or code blocks.

## Registry Lazy-Loading Exception

- Function-local imports are allowed only in registry/router modules for factory lazy-loading.
- Do not use this exception in provider or business modules.

## Repository Root Path

- Use:

```python
from browseruse_bench.utils import REPO_ROOT
```

- Do not use `Path(__file__).parents[N]` or manual path math.

## sys.path Rule

- Do not use `sys.path.insert()` in project code.
- For scripts, prefer environment-based execution:

```bash
export PYTHONPATH=/path/to/browseruse_bench && python script.py
```

## Runtime Environment

- Python version must be `>=3.11` (see `pyproject.toml`).
- Do not use system Python for project tasks.
- Use `uv` for install/run/test workflows.
- Preferred commands: `uv sync --extra dev`, `uv run pytest ...`, `uv run python ...`.
- If tests need optional agent SDKs, install the matching extras first (for example `--extra browser-use`).

## Configuration

- Do not hardcode timeout, URL, API key, model name, or similar runtime values.
- Read config from `config.yaml`, environment variables, or passed config objects (for example `AgentConfig`).
- Store configured file paths as relative paths and resolve to absolute paths with `REPO_ROOT` when reading.

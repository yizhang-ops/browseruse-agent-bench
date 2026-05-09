# Tests

This directory contains test cases for browseruse_bench.

## Directory Structure

```
tests/
├── conftest.py              # pytest common fixtures
├── browseruse_bench/        # Unit Tests
│   ├── test_task.py         # Task Utils Tests
│   ├── test_eval.py         # Eval Utils Tests
│   └── ...
└── scripts/                 # Script Tests
    ├── test_run_dry_run.py  # run.py Tests
    └── ...
```

## Run Tests

```bash
# Run all tests
uv run pytest tests/ -v

# Run specific tests
uv run pytest tests/browseruse_bench/test_task.py -v

# View coverage
uv run pytest tests/ --cov=browseruse_bench --cov-report=html
```

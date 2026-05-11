# Contributing

Thanks for helping make browseruse-agent-bench a reproducible evaluation framework for browser
agents. LexBench-Browser is the built-in public dataset. The most useful contributions are the
ones other teams can run, inspect, and compare.

## Good First Contributions

- Add or improve docs, examples, and troubleshooting notes.
- Propose a dataset task with clear success criteria. See
  `community/tasks/multilingual-task-proposal-examples.md` for examples.
- Submit a reproducible result with redacted config and task-level outputs.
- Add a small agent adapter or example config for an existing integration.

## High-Impact Contributions

- **Agent adapters**: implement a `BaseAgent` adapter, register it, add an optional dependency
  group if needed, and include a smoke command.
- **Dataset tasks**: include the target site, language/region, login requirements, expected
  final state, and evaluation criteria.
- **Browser backends**: implement the backend contract, keep provider dependencies lazy, and
  document agent compatibility. See `docs/en/browser/custom-backend.mdx`.
- **Leaderboard results**: include benchmark, split, agent, model, browser backend, judge model,
  success rate, average steps, average latency, and artifacts.
- **Evaluation improvements**: explain how the judge strategy changes reproducibility or failure
  attribution.

## Result Submissions

Closed-source agents can be submitted. Official leaderboard entries require maintainer review
and maintainer rerun. Use `community/results/example/submission.json` as the metadata template,
and see `EVALUATION_PROTOCOL.md` for the full policy.

## Pull Request Checklist

- Keep the change focused and follow existing project structure.
- Use `uv`, not system Python.
- Run focused tests when possible:

```bash
uv run pytest tests/
```

- For agent-touching changes, run a real smoke test before requesting review:

```bash
bubench run --agent <agent> --data LexBench-Browser --mode single
```

- Do not commit API keys, cookies, run secrets, or unredacted provider logs.

## More Detail

- [English contribution guide](docs/en/development/contributing.mdx)
- [中文贡献指南](docs/zh/development/contributing.mdx)
- [Governance](GOVERNANCE.md)
- [Evaluation Protocol](EVALUATION_PROTOCOL.md)

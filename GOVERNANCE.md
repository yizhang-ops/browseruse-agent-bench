# Governance

LexBench-Browser is maintained as a reproducible benchmark platform. The project accepts
open-source and closed-source agents, but leaderboard entries must disclose enough information
for maintainers and readers to understand what was run.

## Scope

This governance policy covers:

- benchmark task proposals
- agent and browser backend integrations
- leaderboard result submissions
- evaluation protocol changes
- contributor credit
- release snapshots

## License Boundaries

- Code is released under Apache-2.0.
- Documentation and website content are intended for CC-BY 4.0 reuse unless a file states
  otherwise.
- Dataset licensing is declared in benchmark metadata. Do not assume benchmark data inherits
  the code license.

## Task Acceptance

Benchmark tasks should represent realistic browser-agent workflows. A task proposal should
include:

- target website or workflow
- language and region
- login requirement
- safety-sensitive actions, if any
- expected final state
- evaluation criteria
- likely sources of nondeterminism
- the agent failure mode the task is meant to expose

Maintainers may reject tasks that are too brittle, too vendor-specific, unsafe, legally
unclear, or impossible to evaluate reproducibly.

## Agent and Browser Integrations

Agent adapters and browser backends should preserve optional dependency isolation. Heavy or
provider-specific dependencies should be installed only when the selected integration is used.

Closed-source agents may appear on the leaderboard when their result submission discloses:

- agent name and version
- model provider and model ID
- browser backend
- benchmark version
- evaluation model and strategy
- reproducibility limitations

## Leaderboard Governance

Official leaderboard entries require maintainer review and a maintainer rerun. The rerun may
be full or sampled depending on cost, task count, and reproducibility risk.

Submissions must include enough artifacts for review:

- redacted config
- run command
- evaluation command
- task-level outputs
- evaluation results
- run timestamp
- known task skips, retries, provider incidents, or browser constraints

Silent task drops are not accepted. Skipped or failed tasks must be reported.

## Evaluation Changes

LexBench-Browser v1.0 uses the declared official judge model and evaluation strategy in the
release documentation. Later judge or model changes do not automatically create a new
leaderboard family, but they must be recorded in release notes and result metadata.

When evaluation behavior changes, maintainers should document:

- reason for the change
- affected benchmarks and splits
- compatibility impact
- whether existing leaderboard entries need re-evaluation

## Contributor Credit

Contributors to code, docs, tasks, agent adapters, browser backends, and reproducible results
may be listed in `CONTRIBUTORS.md`. Technical report or paper authorship is handled separately
from repository contribution credit.

## Release Cadence

Benchmark releases should provide stable reproduction anchors. A release should include:

- benchmark version
- dataset manifest or metadata pointer
- reference results
- evaluation protocol summary
- known limitations
- citation instructions

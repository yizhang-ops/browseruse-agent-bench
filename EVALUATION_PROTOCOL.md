# Evaluation Protocol

This document defines how LexBench-Browser results should be generated, reviewed, and accepted
for official leaderboard use.

## Official Judge

For LexBench-Browser v1.0, the official judge model is `gpt-5.4` with the stepwise evaluation
strategy unless release notes state otherwise.

Future judge model changes remain in the same leaderboard family, but every accepted result
must record the judge model and strategy used.

## Result Requirements

A leaderboard submission must disclose:

- benchmark name, split, and version
- agent name, version, and source or reproducibility status
- model provider and model ID
- browser backend
- run command and evaluation command
- redacted config
- run timestamp
- success rate
- average steps
- average end-to-end latency
- token and cost metrics when available
- task-level outputs and evaluation output
- known skips, retries, provider incidents, or browser constraints

Closed-source agents are allowed when the submission clearly states what cannot be rerun by
external users.

## Artifact Policy

Artifacts should include the run directory or an equivalent export with:

```text
experiments/
`-- <BenchmarkName>/
    `-- <Split>/
        `-- <AgentName>/
            `-- <ModelId>/
                `-- <Timestamp>/
                    |-- tasks/
                    `-- tasks_eval_result/
```

Secrets must be redacted. Do not submit API keys, cookies, account credentials, or provider
tokens.

## Rerun Policy

Official leaderboard entries require maintainer review and maintainer rerun.

Maintainers may choose:

- a full rerun for low-cost or high-impact submissions
- a sampled rerun for expensive submissions
- an artifact-only precheck before asking the contributor for more data

If the rerun materially disagrees with the submitted result, maintainers should record the
difference and either request clarification or reject the result.

## No Silent Drops

Every task in the selected benchmark split must be accounted for. A task may be marked failed,
skipped, errored, or not evaluated, but it must not disappear from the denominator.

## Evaluation Metadata

Accepted results should record:

- evaluator package version or commit
- judge model
- judge strategy
- score threshold policy
- benchmark data version
- task split
- run environment notes

## Updating Results

If an agent, model, browser backend, or judge setting changes, submit a new result. Do not
overwrite an existing result without preserving its previous metadata.


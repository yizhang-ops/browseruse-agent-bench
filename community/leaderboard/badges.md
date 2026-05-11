# Leaderboard Badge Format

Use badges to make accepted LexBench-Browser results easy to cite in READMEs, release notes, and
agent project docs.

Badges should point to the public leaderboard or the accepted result entry, not to self-reported
screenshots.

## Badge Text

Recommended text:

```text
LexBench-Browser: <success-rate>% verified
```

When a result is not yet accepted:

```text
LexBench-Browser: submitted
```

When a result is a sampled maintainer rerun:

```text
LexBench-Browser: <success-rate>% sampled rerun
```

## Colors

| State | Color | Meaning |
| --- | --- | --- |
| `verified` | `brightgreen` | Accepted after maintainer review and rerun |
| `sampled rerun` | `yellowgreen` | Accepted with sampled maintainer rerun noted in metadata |
| `submitted` | `blue` | PR opened, not official yet |
| `stale` | `lightgrey` | Result references an older benchmark or judge configuration |

## Shields.io Examples

Accepted full rerun:

```markdown
[![LexBench-Browser](https://img.shields.io/badge/LexBench--Browser-72.4%25%20verified-brightgreen)](https://github.com/lexmount/browseruse-agent-bench/tree/main/community/leaderboard)
```

Accepted sampled rerun:

```markdown
[![LexBench-Browser](https://img.shields.io/badge/LexBench--Browser-72.4%25%20sampled%20rerun-yellowgreen)](https://github.com/lexmount/browseruse-agent-bench/tree/main/community/leaderboard)
```

Submitted but not accepted:

```markdown
[![LexBench-Browser](https://img.shields.io/badge/LexBench--Browser-submitted-blue)](https://github.com/lexmount/browseruse-agent-bench/pulls)
```

## Metadata Requirements

A badge may be called `verified` only when the corresponding accepted result records:

- benchmark name, split, and version
- agent name and version
- model provider and model ID
- browser backend
- judge model and strategy
- success rate and task accounting
- maintainer review status
- rerun status: `full`, `sampled`, or documented exception
- link to result artifacts or accepted metadata

Do not use verified badges for local-only runs, private screenshots, or results that have not gone
through the public submission workflow.

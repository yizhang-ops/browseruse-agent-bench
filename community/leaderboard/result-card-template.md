# Shareable Result Card Template

`result-card-template.svg` is a 1280x640 editable template for accepted leaderboard results.

Use it only for accepted or clearly marked submitted results. For social sharing, replace the
placeholders and export the SVG to PNG.

## Placeholders

| Placeholder | Example |
| --- | --- |
| `{{AGENT_NAME}}` | `browser-use` |
| `{{MODEL_ID}}` | `gpt-5.4` |
| `{{BROWSER_BACKEND}}` | `lexmount` |
| `{{SUCCESS_RATE}}` | `72.4%` |
| `{{AVG_STEPS}}` | `18.6` |
| `{{AVG_LATENCY}}` | `42.1s` |
| `{{BENCHMARK_VERSION}}` | `v1.0` |
| `{{JUDGE_MODEL}}` | `gpt-5.4` |
| `{{JUDGE_STRATEGY}}` | `stepwise` |

## Rules

- Use the card for accepted results or label the post as submitted/unverified.
- Link back to accepted result metadata or the leaderboard.
- Do not round metrics in a way that changes rank or interpretation.
- Include browser backend and benchmark version in every card.
- Do not include provider secrets, private artifact URLs, or account identifiers.

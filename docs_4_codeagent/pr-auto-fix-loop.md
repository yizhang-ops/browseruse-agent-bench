# PR Auto-Fix Loop

An **opt-in** procedure: after you push a PR, keep a Claude Code session open and let it watch for new reviewer threads, draft fixes, run the repo smoke test, and push — pausing to ask you only when it hits a guardrail, a stall, or a reviewer it disagrees with. This is a how-to, not a mandatory workflow; use it when the cost of staying around to babysit reviews is worse than the cost of reviewing what the loop pushed.

## When to use (and when not to)

**Use it when:**
- The PR is behavior-changing but scoped (≤ a handful of files), so reviewers are likely to leave fixable nits + small correctness asks.
- You're willing to come back to a PR where commits you didn't personally author have been pushed to your branch.
- The branch has an open PR. The loop refuses to start on a branch without a linked PR, because targeting a stale `.pr/*` directory would sync-resolve the wrong threads.

**Do not use it when:**
- The PR is a contested design change where reviewer feedback needs human negotiation, not mechanical fixes.
- You're about to rebase or force-push — the loop only ever creates new commits, but running it through a rebase window causes avoidable conflicts.
- You don't trust auto mode to push to this branch (e.g. protected-branch PR). Stop here, not worth the risk.

## Install & Prerequisites

Five one-time installs per machine, plus one per-session export.

1. **`gh` CLI authenticated**
   ```bash
   gh auth status
   ```
   Both PR skills shell out to `gh`. If this fails, run `gh auth login` first.

2. **Python env synced**
   ```bash
   uv sync --extra dev
   ```
   The skill scripts (`generate_pr_review_checklists.py`, `generate_unresolved_solutions.py`, `sync_checklist_status.py`) import `browseruse_bench`.

3. **Repo skills installed into Claude Code's skill directory**
   ```bash
   uv run scripts/skills.py    # or: bubench skills
   ```
   This symlinks `browseruse_bench/skills/*` into `.claude/skills/` (and `.codex/skills/` etc.). Run once per machine; subsequent skill edits in `browseruse_bench/skills/` are picked up automatically.

4. **`superpowers` plugin enabled in Claude Code**
   ```
   /plugin install superpowers@claude-plugins-official
   ```
   or set `"superpowers@claude-plugins-official": true` under `enabledPlugins` in `~/.claude/settings.json`. This is where `receiving-code-review` — the admission gate that decides whether to agree with a reviewer — comes from.

5. **Auto mode on (recommended)**
   In `~/.claude/settings.json`:
   ```json
   { "permissions": { "defaultMode": "auto" } }
   ```
   Without this, the loop pauses on every `gh` / `git` / `python3` prompt and the whole point is lost.

**Per session:**
```bash
export PYTHONPATH=$(git rev-parse --show-toplevel)
```
Both PR skills require this; running without it gives `ModuleNotFoundError: browseruse_bench`.

## Starting the loop

Two equivalent forms. Pick one.

### Option A — `/loop` (recommended)

From inside a Claude Code session at the repo/worktree root, with the PR branch checked out:

```
/loop 4m Run one iteration of docs_4_codeagent/pr-auto-fix-loop.md for the PR linked to the current branch. If an exit condition fires, stop the loop.
```

Why 4 min: Claude's prompt cache TTL is 5 min, so intervals ≥ 5 min pay a cache miss every tick. 240 s keeps each tick warm. Use a longer interval (e.g. `/loop 15m`) when you want to reduce GitHub API pressure and don't mind slower reaction.

### Option B — `Monitor` (when you need event-driven polling in a long-running session)

Start a persistent monitor that polls the PR's `updatedAt` field and emits an event when it changes:

```bash
last=$(gh pr view --json updatedAt --jq .updatedAt)
while true; do
  now=$(gh pr view --json updatedAt --jq .updatedAt)
  if [ "$now" != "$last" ]; then
    echo "pr_updated at=$now"
    last=$now
  fi
  sleep 240
done
```

Each emitted line becomes an in-session notification; Claude responds with one iteration of the per-iteration checklist. `Monitor` is better when you also want other notifications (CI status, new labels) on the same stream; `/loop` is simpler when all you want is timed ticks.

## Per-iteration checklist

Each iteration runs these 11 steps in order. A step that fails to complete terminates the iteration — do not skip ahead.

1. **Precondition check.**
   ```bash
   git fetch --prune
   git status --porcelain
   ```
   If the working tree is non-empty (reviewer pushed a commit, or you have local edits), pause — do not overwrite. If current branch has no linked PR (`gh pr view` returns non-zero), refuse to start the loop.

2. **Refresh review threads.**
   ```bash
   python3 browseruse_bench/skills/pr-review-checklist/scripts/generate_pr_review_checklists.py
   ```
   Writes `.pr/<N>/review_checklist.md` and `.pr/<N>/unresolved_checklist.md`.

3. **Diff unresolved set vs previous iteration.** If the `TH-*` set in `unresolved_checklist.md` is identical to the previous tick's snapshot (or empty), no action; next iteration.

4. **Draft solutions for new threads.**
   ```bash
   python3 browseruse_bench/skills/pr-unresolved-solutions/scripts/generate_unresolved_solutions.py
   ```
   Writes `.pr/<N>/unresolved_solutions.md`. Per the skill's autonomous-execution policy, every `AGENT_REQUIRED` placeholder must be filled without asking the user — see the skill's own SKILL.md § Autonomous Execution Policy.

5. **Admission gate per thread.** For each new `TH-*`, invoke `superpowers:receiving-code-review` to classify the thread into one of: **implement**, **push back**, **defer to human**. See § Receive-and-push-back below.

6. **Apply all "implement" edits.** Edit files in-place. Do not commit yet.

7. **Smoke test.** If the diff touches any agent runtime path (see [error-handling-testing.md § Smoke Testing Before Commit](error-handling-testing.md#smoke-testing-before-commit)), run the real single-task `bubench run`. On failure: **do not commit, do not push** — pause and surface the failure + the full uncommitted diff to the session.

8. **Single batched commit.**
   ```bash
   git add -A
   git commit -m "fix(pr-review): address TH-<id1>, TH-<id2>, ..."
   ```

9. **Push.**
   ```bash
   git push
   ```

10. **Sync resolved state — only after push succeeds.**
    ```bash
    python3 browseruse_bench/skills/pr-unresolved-solutions/scripts/sync_checklist_status.py \
      --thread-ids TH-<id1> TH-<id2> --state resolved
    ```
    Do not gate on CI. If CI is pending, the next iteration proceeds; if CI goes red post-push, the next iteration's `gh pr checks` step treats it as a stall signal.

11. **Report to session.** One line: "Iteration N: addressed M threads, pushed `<sha>`, K pushed back, J deferred."

## Exit conditions

Any one breaks the loop. On break, release the `.pr/<N>/.loop.lock` file (see § Concurrency), summarize state in-session, and stop — do not silently retry.

- PR `merged` or `closed` (`gh pr view --json state`). **Terminate.**
- PR `APPROVED` **and** `unresolved_checklist.md` is empty. **Terminate** — done, nothing to do.
- Same set of unresolved `TH-*` stays identical across 2 consecutive iterations **despite attempted fixes** (i.e. agent implemented changes but smoke test or push failed, or reviewer-is-wrong path returned the same set). **Pause** — stalled, needs human.
- Any guardrail (next section) triggers. **Pause** — needs human review of the proposed diff.
- Total iterations ≥ 5. **Pause** — protects against runaway cost. User resumes by restarting the loop explicitly.
- User sends `/stop` or Ctrl-C. **Terminate.**

## Guardrails

The loop **must pause** — never auto-commit and never auto-push — if the proposed diff would touch any path below, or if a reviewer comment matches any signal below. When a guardrail trips, surface: which guardrail, which thread triggered it, and the full proposed diff. Let the human take over.

### Path guardrails

Never auto-push changes to:

- `pyproject.toml`, `uv.lock`, `package-lock.json`, `pnpm-lock.yaml` — dependency lock.
- `alembic/versions/**`, `migrations/**` — DB migrations.
- `.github/workflows/**` — CI config.
- `.env*`, any path matching `*credential*` or `*secret*` — secrets.
- `config.example.yaml` — shared-default surface affecting every user of the repo.
- Any diff that **reduces** test coverage — deletions inside `tests/**` or removal of `assert` lines.

### Comment-level guardrails

Pause when a thread's comment body contains any of:

- `@human`
- `需要讨论` or `needs discussion`
- `decision needed`
- A behavior that directly conflicts with a thread already implemented in the current iteration's batch.

### Rationale

These are surfaces where a wrong auto-commit is either hard to revert (dependency lock desync, migration applied in CI), carries security risk (secrets), changes team-wide defaults, or needs judgment the agent shouldn't arrogate (design disagreement).

## Receive-and-push-back

The loop is "full auto" for **mechanics** — fix → commit → push → sync checklist. It is **not** full auto for "implement whatever the reviewer asked." That distinction is the non-negotiable safety property that keeps the loop from degrading code quality; without it, you'd be shipping changes because a reviewer typed them, not because they were right.

Every new thread runs through `superpowers:receiving-code-review` as the admission gate. The skill exists specifically to prevent "performative agreement or blind implementation." For each thread the skill returns one classification:

- **Implement** — reviewer is correct; include in this iteration's batched commit.
- **Push back** — reviewer is wrong or missing context. The loop posts a reply comment on the thread explaining why the proposed change is incorrect, and **does not edit code** for that thread. The thread stays `unresolved` (the loop does not mark it resolved). Next iteration: if the reviewer replies with new context, re-classify.
- **Defer to human** — reviewer's point is valid but implementation requires product direction, access to resources the agent doesn't have, or a design choice outside the agent's remit. The loop posts a reply saying so, then leaves the thread alone.

The three classifications together close the loop on pathological cases: a reviewer who keeps repeating the same wrong ask just sees the same pushback reply, not an infinite oscillation of commits.

## Concurrency, rollback, observability

### Concurrency

The loop uses a file lock to prevent two local sessions from racing on the same PR:

```
.pr/<N>/.loop.lock    # contains PID of the holding session
```

On iteration start, the loop reads the lock file. If the PID is running, the loop refuses to start (another session owns this PR). If the PID is not running (stale lock from a crashed session), the loop reclaims it.

Every iteration's step 1 (`git status --porcelain`) also detects the case where a reviewer pushed a commit to the branch while the loop wasn't looking — in that case the working tree is behind, not dirty, and the loop pauses for manual rebase.

### Rollback

The loop only ever creates **new** commits. It never runs `git push --force`, never amends a pushed commit, never rewrites history. Rollback is `git revert <sha>` by a human.

`sync_checklist_status --state resolved` is only called **after** the push lands. Never optimistic — so if the push fails (hook rejection, network), the thread stays `unresolved` and next iteration will retry.

### Observability

Every iteration appends a structured line to `.pr/<N>/loop.log`:

```
ts=<iso8601> iter=<N> unresolved_before=<count> implemented=[TH-...] pushed_back=[TH-...] deferred=[TH-...] pushed=<sha|none> smoke=<pass|fail|skip> exit=<reason|none>
```

When the loop pauses, the last `loop.log` line always contains `exit=<reason>` so the human stepping in can reconstruct state without reading the chat transcript. The chat transcript also gets a one-line summary per iteration (step 11 of the per-iteration checklist).

## Troubleshooting

### Loop refuses to start: "no PR linked to current branch"

`gh pr view` returned non-zero. Either the branch hasn't been pushed, or `gh pr create` hasn't been run. Fix with `bubench submit` or `gh pr create`, then restart the loop.

### Loop pauses with "dirty working tree"

Either you have local edits, or a reviewer pushed a commit while the loop wasn't looking. Check `git status`. If the reviewer's commit, `git pull --rebase` and restart the loop. If your edits, stash or commit them manually first.

### Stale `.loop.lock`

A previous session crashed. Manually inspect `.pr/<N>/.loop.lock` — if the PID isn't running (`ps -p <pid>`), delete the lock file and restart the loop. The loop reclaims stale locks automatically on next start, but you can force-clean by deleting.

### CI turned red after loop pushed

Next iteration's step 1 includes `gh pr checks`; a red check counts as a stall signal toward the 2-consecutive-iteration stall limit. If the CI failure is reviewer-actionable (e.g. they asked for a change that broke a test you didn't run locally), reply on the relevant thread and pause for human intervention. Do not loop-fix CI failures automatically — that's too easy to turn into a commit spiral.

### `ModuleNotFoundError: browseruse_bench` from a skill script

Forgot `export PYTHONPATH=$(git rev-parse --show-toplevel)` for this shell session. Run it and retry.

### Loop addressed threads but never exited

Check `unresolved_checklist.md`. If `TH-*` you thought were resolved still appear there, `sync_checklist_status.py --state resolved --thread-ids ...` didn't run — most likely because push step failed silently. Check `.pr/<N>/loop.log` for the relevant iteration's `pushed=` field.

## Related skills & links

**The primitives this handbook glues together:**
- [pr-review-checklist](../browseruse_bench/skills/pr-review-checklist/SKILL.md) — pulls GitHub review threads into `.pr/<N>/` local files.
- [pr-unresolved-solutions](../browseruse_bench/skills/pr-unresolved-solutions/SKILL.md) — drafts fix proposals per thread, syncs checklist state.
- `superpowers:receiving-code-review` — admission gate that classifies each thread as implement / push back / defer.

**Team-wide rules this handbook extends:**
- [error-handling-testing.md § Smoke Testing Before Commit](error-handling-testing.md#smoke-testing-before-commit) — what counts as a real smoke test (not `--dry-run`, not pytest-only).

---
name: pr-review-loop
description: Watch a set of open PRs and keep them green. Polls each PR for new review feedback (human + bots like cursor[bot] + the fresh-context agent reviewers) or failing CI, dispatches the pr-fixer subagent per actionable PR (the review queue reviews each push on its own), and self-paces the interval. Periodically merges origin/main into each branch and resolves any conflicts so branches don't go stale. Caps attempts per PR, then surfaces it as needs-human. The orchestrator never fixes code itself.
compatibility: Claude Code
---

# PR Watch

The external watch loop: given a list of open PRs, keep them moving toward merge by
addressing every new piece of feedback (reviewers, bots, the agent reviewers, CI) as it
lands. You **orchestrate and track** — you never edit code, investigate, or comment on PRs
yourself. All fixing is delegated to the `pr-fixer` subagent, which pushes its own fix; review
happens after that push, on the PR, by the review queue (see **The review queue** in the
`delegator` skill).

Correctness lives in `scan.py` (shipped beside this skill), not in your judgement of "did I
already handle this?". The scanner dedupes seen feedback and tracks attempts so the loop
doesn't re-dispatch the same PR or churn forever.

Subagent models: dispatch `pr-fixer` on `opus`; anything else goes to the tier that
matches its difficulty (`haiku` / `haiku-high` / `haiku-xhigh` / `sonnet-high`, `github` for any `gh` or push, or
`source-fetcher` for extra context), per the delegator skill's tiering table. Never dispatch on `fable` unless the user explicitly asks.

The agent reviewers are not subagents — the review queue daemon runs them (see **After a fix
lands** below).

## Setup (once per run)

The scanner reads/writes its state next to itself, so run it from the **scratchpad**, never
from the committed skill dir:

1. Dispatch `github`: "PR watch setup in <scratchpad>" with the PRs to watch. It copies
   `scan.py` there, resolves each head branch, and writes `<scratchpad>/prs.json`
   (`{"14471": "feature/ppr-127"}`). Every `scan.py` command below runs through `github` too.
3. `scan.py` defaults `IPR_REPO_ROOT` to this repo; set the env var if the repo lives
   elsewhere. Worktrees resolve to `<repo>/.claude/worktrees/<branch with / → +>`.

`state.json` is created automatically and stays in the scratchpad — never commit it.

## The loop

On the user's own PRs, reviews and review threads (agent, bot, or human) belong to the review
queue's fix lane, which runs `pr_fix.py` on them. `scan.py` reports only failing CI and PR
conversation comments for those PRs, so PR Watch never races the lane.

Each tick:

1. **Scan**: `github` runs `scan` in the scratchpad. It prints `{"work": [...], "count": N}`. Each work item
   carries the PR, branch, worktree path, attempt count, head SHA, unresolved-thread count,
   and the new feedback grouped by source (reviews / inline / issue comments / failing checks).
   Inline comments come from the GraphQL `reviewThreads` connection, so each one carries its
   thread's state: already-**resolved** threads are filtered out, and **`"outdated": true`**
   means the reviewer commented against a head that no longer exists. Pass that flag through
   to `pr-fixer` — an outdated finding is often already fixed, and it must verify against the
   current head before changing anything rather than re-fixing it.
2. **If `count` is 0**: nothing actionable. Self-pace and tick again (see below). Also run
   `scan.py status` occasionally — once every watched PR is `merged`/`closed`, report and stop.

   A PR whose last review round came back clean and that has no other new feedback is quiet on
   purpose. Don't manufacture work for it: no extra review round, no speculative fix. It moves
   again when a human comments, CI turns red, or someone pushes.
3. **For each actionable PR**, in order:
   - `github` runs `mark <PR>` **immediately, before dispatching** — marking at dispatch
     time is what prevents a slow fix from being picked up twice. This also bumps the attempt
     counter.
   - Dispatch the **`pr-fixer`** subagent with the PR number and the feedback summary from the
     work item. It fixes in the PR's worktree, commits, and pushes.
4. **needs-human**: when a PR hits `MAX_ATTEMPTS` (4) with feedback still unhandled, the
   scanner flips its status to `needs-human` and stops returning it. Surface these to the user
   — they need a human, not another loop iteration.

## After a fix lands — the queue reviews it

A push changes the head, and the review queue reviews each new head of the user's own PRs and
of PRs that request their review, with no call from you. Its findings land on the PR as
ordinary review comments and come back to you through the normal scan on a later tick. You
never read the findings yourself, and you never run `pr_review.py`.

- It scopes each round to the commits since the last one, so the reviewers cannot re-report
  what `pr-fixer` just fixed.
- It skips a head whose own diff did not change (a clean `origin/main` merge, a rebase).
- A reviewer that found nothing posts nothing. One whose findings are all below the fix floor
  posts notes only, marked `<!-- agent-review-fyi -->`, and `scan.py` skips those.
- After 8 rounds in a row with findings it stops and alerts the user (`needs-human`).
- Once the user's own PR reviews clean, it holds the PR: a later push, such as a fix for a
  colleague's comment, gets no review (`held`). Only the user's ask re-opens it:
  `review-queue --next <N>` or `--pr <N>`.

To see where a PR stands, have `github` run `review-queue --wait <N>` (it returns at once when
the PR already settled on its current head: reviewed, and fixed when the reviewers posted). A watched PR outside the queue (not the
user's, no review request) gets a review only when the user asks: "Review PR #N now".

## Keeping branches current with main

Long-lived PR branches drift from `main`. On a **slower cadence than the feedback poll** —
every few ticks, roughly every half hour — bring `origin/main` into each non-terminal watched
PR before it goes stale. Running `git` here is loop mechanics, not editing code; only conflict
resolution is delegated.

For each watched PR whose status isn't `merged` / `closed` / `needs-human`:

Dispatch `github` with "Main sync of <worktree>". It returns one of:
   - `skipped` — not behind main; nothing to do.
   - `pushed <sha>` — clean merge, plain push. CI re-runs against the new head; the next
     feedback poll catches any breakage through the normal fix path.
   - `conflict` (it already ran `git merge --abort`) → dispatch **`pr-fixer`** to merge origin/main itself in
     that worktree, resolve the conflicts preserving the PR's intent, commit it, and push. The
     queue reviews the resolved head if the resolution changed the PR's own diff.
     If `pr-fixer` can't resolve it confidently, have it `git merge --abort` and surface the PR
     to the user.

Track when you last synced (a tick counter or timestamp) so this runs on its slower cadence,
not every tick.

## Self-pacing

Keep waits **short** — minutes, not tens of minutes — so feedback gets picked up promptly.
Use `ScheduleWakeup` to schedule the next tick, passing the same loop invocation back so it
resumes. Run the **keep-current-with-main** pass on its slower cadence (every few ticks), not
every tick. Don't block on long foreground sleeps. Stop scheduling once all PRs are terminal or
the user interrupts.

## Reporting

Never sign off on a PR from what you remember doing — report from a fresh read of its current
state. Have `github` run `report [<PR>...]` (defaults to every watched PR) whenever you tell
the user a PR is done, hits `needs-human`, or when you stop the loop. It re-queries GitHub and
prints, per PR:

- PR state and loop status/attempts, and the **head SHA** the report describes
- every check in the rollup with its conclusion
- the **unresolved thread count**, then each unresolved thread as
  `path:line @author [outdated] — first 120 chars`
- the worktree path and how many files are dirty in it

Two things that report catches and a green checks list doesn't: a **NEUTRAL or SUCCESS check
can still carry findings** (Cursor Bugbot reports this way), and **unresolved threads block a
merge even when CI is fully green**. Read both before calling a PR clean.

In your message to the user, carry over the head SHA, failing/neutral check names, unresolved
thread count, and any dirty worktree files you left untouched. If `pr-fixer` ran tests, say
which ones and what they returned. State what's still open rather than rounding it to "done".

## What you never do

- Never edit code, run the fix, resolve merge conflicts, or reply to/resolve PR comments
  yourself — that's `pr-fixer`. A clean main-merge goes to `github`.
- Never run the reviewers yourself — the queue reviews every push. Never dispatch a fixer on a
  round that posted nothing or notes only.
- Never read the reviewers' findings into your own context. They live on the PR; `pr-fixer`
  reads them from there on the next tick.
- Never re-dispatch a PR you've already marked this tick, or one that's `needs-human`.

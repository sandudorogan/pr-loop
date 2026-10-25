# Overhaul baseline

Read this before a large change. It records where the queue stands on 2026-10-25,
what must keep working, and where the code is tied to one repo, one machine and one owner.
It sets no direction. The overhaul decides that.

## Baseline

```text
bin/review-queue                       841 lines   daemon + CLI + both lanes
review/pr_review.py                    530 lines   one reviewer pass
review/pr_fix.py                       519 lines   one fix pass
claude/skills/pr-review-loop/scan.py   289 lines   PR watch scanner
install.py                              75 lines
tests/                                   5 tests   installer + path resolution only
```

The service is live. launchd runs `main` of `~/workdir/review-queue` for two repos
(`iprally/iprally`: review + fix; `iprally/gitops`: fix only). Every step must leave it running.

## Guardrails

- Keep each contract in [AGENTS.md › Contracts](../AGENTS.md#contracts-that-other-code-depends-on).
  The markers live on GitHub PRs already: a format change must still read the old one.
- Keep the state files readable, or migrate them in the same change. `review-queue.json`,
  `review-queue.fixes.json` and `pr-fix/<N>.json` hold live per-PR progress.
- Keep the symlinked entry points in `links.json` until agent-delegator stops calling them
  (`~/.claude/skills/delegator/pr_review.py`, `pr_fix.py`, `prompts`).
- Land in PRs of about 700 lines or less, tests included.

## Repo coupling (IPRally)

| Where | What |
| --- | --- |
| `bin/review-queue:47-50` | default repo `iprally/iprally`; `MONOREPO` decides review lane on/off and the state tag |
| `review/pr_review.py:41` | same default repo |
| `review/pr_fix.py:39` | state tag compares to `iprally/iprally` again |
| `review/pr_fix.py:46` | `nvm use 22.15.1` |
| `review/pr_fix.py:266-333` | test gate: `ui/src/cljs` → `ui/test/*_test.cljs` namespaces, `npm run postinstall` (loyto), shadow-cljs `karma-test`, `iprally_ui.karma_runner_test.init`, `cljfmt` |
| `review/pr_fix.py:142` | only `github-actions` check runs count as CI |
| `review/prompts/opus.md:33` | convention docs `docs/tech/`, `ui/docs/`, `api/docs/` |
| `review/prompts/quality.md:16` | `.agents/skills/quality-self-review/SKILL.md` in the reviewed repo |
| `claude/skills/pr-review-loop/scan.py:32-36` | hard-coded repo and root, ignores `IPR_REPO` |

The review lane is off outside the monorepo because the prompts carry monorepo conventions.

## Delegator coupling

| Where | What |
| --- | --- |
| `review/pr_review.py:51` | `.clean-reviews.json` under `~/.claude/skills/delegator/` |
| `review/pr_review.py:64` | briefs under `~/.claude/skills/delegator/briefs/`, keyed by bare PR number or branch |
| `links.json` | old `~/.claude/skills/delegator/` runner paths |
| `tests/test_paths.py:23-24` | asserts both delegator paths |
| `claude/skills/pr-review-loop/SKILL.md` | needs agent-delegator's `pr-fixer` and `github` agents |

## Machine coupling (macOS)

- launchd plists, `launchctl kickstart`/`bootstrap`, `ProcessType Standard` (see AGENTS.md gotchas).
- `bin/review-queue:61`: notifier app at `~/.local/share/review-queue/Review Queue.app`, built by hand, not in this repo.
- `bin/review-queue:778`: `lsof` for in-use worktrees (needs `/usr/sbin` on `PATH`).
- `fcntl` flocks for every lock: POSIX only.

## Duplication

```text
                     bin/review-queue   pr_review.py   pr_fix.py   scan.py
REPO / REPO_ROOT            ✓                ✓          (import)      ✓ (hard-coded)
agent / FYI markers                          ✓              ✓          ✓
sh / die / gh helpers       ✓                ✓              ✓          ✓
JSON state load/save        ✓                ✓              ✓          ✓
GraphQL threads query                                       ✓          ✓
```

`pr_fix.py` imports `LIMIT`, `REPO`, `REPO_ROOT` and `brief` from `pr_review.py`.
The daemon calls both scripts as subprocesses and reads their stdout JSON.

## Known gaps

- A `no-auto-fix` PR of mine: `scan.py` drops review threads on my PRs, so nobody acts on them.
- Briefs resolve by bare PR number, so a gitops PR can pick up a monorepo brief with the same number.
- `.clean-reviews.json` writes without a lock. A lost entry costs one extra review.
- `fix_note` for `tests-red` hides Codex's summary of the cause.
- No gitops prune job.
- One log file for both instances.

## Test gaps

No test covers the decision logic. These are pure or close to it, so they are cheap to pin first:

```text
bin/review-queue   decide · fingerprint parsing · false_clean · feedback_key · fixable · fixing · ready · row · priority
pr_review.py       scope (round + range) · to_fix · split_findings · commentable_lines · extract_json · marker round-trip
pr_fix.py          namespaces · mine_last · feedback filtering · stuck · failed_jobs filtering
```

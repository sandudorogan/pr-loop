# PR Wizard overhaul

Read this before a large change. It records what the overhaul (2026-10-25) changed in the review queue,
what must keep working, and the gaps that remain. The plan and the API contract are in the delegator briefs
(`~/.claude/skills/delegator/briefs/pr-wizard/plan.md`, `api.md`).

## Before and after

| What | Before (`review-queue@3dc9b3f`) | Now |
| --- | --- | --- |
| Processes | 2 daemons (`IPR_REPO` per process) + a prune job | 1 daemon (`local.pr-wizard`), prune is a thread |
| Repos | `iprally/iprally`, `iprally/gitops`, hard-coded | detected from my PRs, worked where a checkout exists |
| Knobs | constants in 3 files | one config file in chezmoi, three override levels |
| Conventions | iprally's, in the prompts | each project's own files, read at the PR head |
| Fixer checks | cljfmt + Karma in `pr_fix.py` | per-project `fix.gates`; iprally's are its built-in override |
| State | `review-queue*.json`, `pr-fix*/`, `.clean-reviews.json`, `now.d/` | `~/.local/state/pr-wizard/state.db` |
| Control | SIGUSR1, a shell snippet to re-arm | HTTP/1.1 + JSON on `api.sock` |
| Ready alert | terminal-notifier | `ready_for_approval` events; the app notifies |
| UI | `review-queue -l` | `pr-wizard -l` and `PR Wizard.app` |
| Code | `bin/review-queue`, 841 lines | `pr_wizard/` package; `bin/review-queue` → `bin/pr-wizard` |

## Invariants

- One daemon process, one launchd label, one socket, for every project (AGENTS.md › Ground truth).
- Each contract in [AGENTS.md › Contracts](../AGENTS.md#contracts-that-other-code-depends-on). The markers live on
  GitHub PRs already: a format change must still read the old one.
- With no config file, the defaults reproduce the behaviour before the overhaul.
- Keep the symlinked entry points in `links.json` until agent-delegator stops calling them
  (`~/.local/bin/review-queue`, `~/.claude/skills/delegator/pr_review.py`, `pr_fix.py`, `prompts`).
- `state.db` has one owning code path per table. Every write is `BEGIN IMMEDIATE`.
- Land in commits of about 700 lines or less, tests included.

## Coupling that remains

| Where | What |
| --- | --- |
| `pr_wizard/names.py` `MONOREPO` | the default repo of a bare `N` on the CLI and in the scripts |
| `pr_wizard/names.py` `REPOS` | the two repos of the old JSON layout, for `migrate()` / `--reverse` only |
| `pr_wizard/config.py` `DEFAULTS` | iprally's gates and gitops' review-off, as built-in project overrides |
| `claude/skills/pr-review-loop/scan.py` | hard-coded `iprally/iprally`; reads `IPR_REPO_ROOT` only |
| `review/pr_review.py` | briefs under `~/.claude/skills/delegator/briefs/`, by bare PR number or branch |
| `claude/skills/pr-review-loop/SKILL.md` | needs agent-delegator's `pr-fixer` and `github` agents |

macOS: the launchd plist, `launchctl kickstart`/`bootstrap`, `ProcessType Standard`, `lsof` for in-use worktrees
(needs `/usr/sbin` on `PATH`), and `fcntl` flocks for every lock.

## Still to do

```text
 unit 27     drop terminal-notifier       after the app runs at login with notifications allowed
 cutover B   checkout                     ~/workdir/review-queue → ~/workdir/pr-wizard (the GitHub repo is sandudorogan/pr-wizard)
```

The owner confirms cutover B first (plan.md §5). Until then, the checkout and the install backups
(`~/.local/state/review-queue/backups`) keep the old name.

## Known gaps

- A `no-auto-fix` PR of mine: `scan.py` drops review threads on my PRs, so nobody acts on them.
- Briefs resolve by bare PR number, so a PR of another repo can pick up an iprally brief with the same number.
- A Codex review with a "no ship" summary and zero findings counts as clean: `false_clean()` checks only the
  summary's length and error words.

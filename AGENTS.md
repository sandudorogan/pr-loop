# Review queue: agent guide

Read this file before you change or operate the queue. It holds what an agent needs to work here.
Do not rely on memory files for this repository. When you learn something durable, add it here.

## What it is

A macOS launchd daemon that reviews and fixes GitHub PRs for one owner (`gh` user).
One process serves every project: `REPOS` (`pr_wizard/names.py`) plus the keys of `projects` in `~/.config/pr-wizard/config.json`
(a config project needs `projects[repo].root`, else the daemon logs it and skips it). The config sets each project's lanes,
reviewers, gates, workers and refresh; the daemon re-reads it on every refresh and resizes the pools live, no restart.
By default `iprally/iprally` gets both lanes, `iprally/gitops` the fix lane only.

```text
                 one GraphQL call every 5 min (60 s when a worker idles, now on SIGUSR1)
                 mine (author:@me) + requested + reviewed-by:@me
                                   │
                                   ▼
 pr_wizard/queue ── gates ── review lane (3 workers) ─── pr_review.py run × {opus, codex, quality}
   decide()          │                                       │ posts 1 review per reviewer, marker in body
   same head         │                                       ▼
   own-diff hash     │                         state ~/.local/state/pr-wizard/state.db
   trivial files     │                                       │ my PR, reviewers done, new feedback_key
   hold / rounds     │                                       ▼
   too big           └───────────────────── fix lane (3 workers) ─── pr_fix.py run
                                                             │ codex (sandbox) → fix.gates → commit
                                                             ▼
                                                 push = new head → next review round
```

- Review lane: my PRs, PRs that request my review, PRs I reviewed before. Monorepo only.
- Fix lane: my PRs only. Input = unresolved threads, review bodies on the head, failed Actions jobs, base conflict.
- Every PR dict carries `repo`. Lanes, locks and state key on `(repo, number)`: PR numbers of two repos overlap.
- Children run with `IPR_REPO` and `IPR_REPO_ROOT` set to the PR's repo, `cwd` = its root. The daemon ignores `IPR_REPO`.

## Ground truth (never change)

One daemon process runs for the whole system. Never more than one. This rule does not change.

- That one process watches every configured repo.
- Every PR the owner opened goes into the review queue or the fix queue inside that process.
- Every PR assigned to the owner, or that requests the owner's review, goes into those queues too.
- The workers are threads inside that process.
- The commands a worker runs for one pass are child processes of that pass: `pr_review.py`, `pr_fix.py`, `claude -p`, `codex exec`. They are not daemons.
- Do not add a second launchd job, a per-repo process, or a per-repo socket.
- To support a new repo, add it to the one daemon.

## Files

| Path | Role |
| --- | --- |
| `pr_wizard/queue.py` | Daemon, CLI, queue fetch, gates, both lanes, `--wait`, `-l`, `--prune` |
| `pr_wizard/api.py` | Control API (`api.md`): HTTP/1.1 + JSON on `api.sock`, a server thread in the daemon; `python3 -m pr_wizard.api --fake [--socket PATH]` serves the fixtures |
| `pr_wizard/fake.py` | The static runtime behind `--fake` |
| `pr_wizard/names.py` | Repos, labels and every state, log and skill path. The queue, both scripts and `db.py` read them here |
| `bin/pr-wizard` | CLI entry point: puts the repo root on `sys.path`, runs `pr_wizard.queue.main()`. `bin/review-queue` is a symlink to it |
| `review/pr_review.py` | One reviewer on one PR: scope the round, run the engine, post the review |
| `review/pr_fix.py` | One fix pass on one PR: collect feedback, Codex, gate, land, reply/resolve |
| `review/prompts/*.md` | Prompt templates. `{PR}`, `{REPO}`, `{HEAD}`, `{BASE}`, `{DIFF_RANGE}`, `{ROUND_NOTE}`, `{BRIEF}`, `{SCHEMA}`, `{FEEDBACK}`, `{FILES}`, `{CONVENTIONS}`; a `{SKILL name}…{/SKILL}` block stays only when the project lists that skill (`{PATH}` = its SKILL.md). No project's rules belong in a prompt |
| `pr_wizard/gates.py` | The project's `fix.gates` (format, then test) run after Codex, `{GATES}` in `fix.md`, the retry prompt. iprally's cljfmt and Karma are its built-in override in `config.DEFAULTS`; a project without gates runs none |
| `pr_wizard/conventions.py` | A project's own conventions read from the checkout at the PR head (agent files and their `@` includes, contributing doc, editorconfig, formatter configs, skills) → `{CONVENTIONS}`. None found: `needs_conventions` reviewers skip (`no-conventions`) |
| `review/*-schema.json` | JSON schemas the engines must return |
| `claude/skills/pr-review-loop/` | Claude Code PR watch skill + `scan.py` (used by agent-delegator) |
| `launchd/*.plist.tmpl` | Service templates, `{{ .chezmoi.homeDir }}` placeholder |
| `install.py`, `links.json` | Symlink the repo into `$HOME`; render plists into `.local/` |
| `docs/overhaul.md` | Coupling, invariants and known gaps to read before a large change |
| `app/` | PR Wizard.app: one SwiftPM package, `PRWizardKit` library (models, no SwiftUI) + thin `PRWizard` app target |
| `tests/fixtures/api/v1/` | Control API responses. The Swift tests decode them; `tests/test_api_read.py` asserts the server against them |

Python 3.10+, standard library only. No `requirements.txt`, no packaging. Keep it that way unless the overhaul decides otherwise.
The app: Swift 6, macOS 26, Command Line Tools only (no Xcode), Swift Testing, no dependencies.

## Installed paths and state

The live service runs the code in the **main checkout** (`~/workdir/review-queue`) through symlinks:

```text
~/.local/bin/review-queue                    → bin/review-queue → bin/pr-wizard (compat alias; launchd runs it)
~/.local/bin/pr-wizard                       → bin/pr-wizard
~/.claude/skills/delegator/{pr_review.py,pr_fix.py,prompts,*-schema.json} → review/
~/.claude/skills/pr-review-loop              → claude/skills/pr-review-loop
~/Library/LaunchAgents/local.review-queue*.plist → .local/*.plist (rendered by install.py)
```

| State | Owner | Shape |
| --- | --- | --- |
| `~/.local/state/pr-wizard/state.db` `reviews` | review lane | `(repo, number)` → `{sha, status, verdict, note, rounds, hold, at, files}` |
| `state.db` `fixes` | fix lane | `(repo, number)` → `{sha, key, status, note, errors, at}` |
| `state.db` `next` | `--next`, `--wait` | bumped PRs in order |
| `state.db` `runs` | live runs | `(repo, number)` → `{pid, lane, since}` for `-l` ▶ rows; dead pids ignored |
| `state.db` `fix_state` | pr_fix.py | Codex session, handled reviews/jobs, deferred threads, `ci_tries`, `reruns`, `red` |
| `state.db` `clean_reviews` | pr_review.py | `(repo, number, sha, reviewer)` heads a reviewer cleared |
| `~/.local/state/review-queue.{lock,pid}` | daemon | single-daemon flock, pid for SIGUSR1 |
| `~/.local/state/pr-wizard/locks/<owner>/<name>/<N>` | both lanes | per-PR flock across processes (`<N>.fix`: a pr_fix.py run) |
| `~/.local/state/pr-wizard/slot.{0,1}.lock` | pr_fix.py | 2 `slot: true` gate runs (iprally's Karma) machine-wide |
| `~/.local/state/pr-wizard/api.sock` | daemon | control API socket, `0600` in a `0700` dir; SIGTERM unlinks it, a stale one goes at start |
| `~/.local/state/pr-wizard/launchd-label` | daemon | the label to `launchctl kickstart`, written at every start |
| `~/.local/state/pr-wizard/scratch/<N>-*` | pr_fix.py | Codex scratch dirs |
| `~/.claude/skills/delegator/briefs/<N or branch>.md` | agent-delegator | task brief; branch name with `/` → `+` |
| `~/Library/Logs/review-queue.log` | all | one shared log; gitops lines read `gitops#N` |

`state.db` is SQLite in WAL mode, written through `pr_wizard/db.py` only. Every entry point runs `names.migrate()` first:
it imports the old JSON files once (`pr-wizard migrate -n` shows what), moves them to `pr-wizard/legacy/<ts>/`,
and `pr-wizard migrate --reverse` exports the db back to them.
The daemon also holds `review-queue-gitops.lock` and skips gitops while an old gitops daemon holds it.
Review worktrees: `<repo>/.claude/worktrees/.review-<N>` (one per PR, shared by its reviewers).
Fix worktrees: the PR branch's existing worktree, else `<repo>/.claude/worktrees/<branch / → +>`.

## Contracts that other code depends on

Break one of these and something outside this file breaks quietly.

- **Agent marker.** Every posted review and inline comment carries
  `<!-- agent-review: reviewer=<id> round=<n> sha=<head> -->`.
  `scope()` reads it back for the round number and diff base. `scan.py` and `pr_fix.py` use it
  to un-skip comments posted under the owner's token. Strip it and the fix loops go silent.
- **FYI marker.** `<!-- agent-review-fyi -->` marks a notes-only review (no finding at the fix floor).
  The fix lane and `scan.py` skip it.
- **Fix floor.** A finding counts when severity ≥ medium and confidence ≥ 0.6. From round 4: ≥ high.
- **`stop`.** `pr_review.py run` prints JSON with `stop: true` only when nothing is left to fix.
  The queue maps "all three stop" to `clean`.
- **`feedback_key`.** `head:reviews:unresolved-threads:their-comments[:conflict][:ci-red-N[-running]]`.
  The fix lane runs when the key differs from the last recorded one. Any new kind of input must move the key.
- **Codex never writes git.** It runs `workspace-write` with no network. `pr_fix.py` commits, pushes, replies, resolves.
- **No AI attribution.** `land()` strips `Co-Authored-By` and "Generated with Claude" lines from commit messages.

Status vocabulary:

```text
review status   posted · clean · failed · limited · baseline · unchanged · trivial · held · needs-human · too-big
review verdict  clean · quality-only · posted          (READY = clean, quality-only)
fix status      pushed · refuted-only · no-changes · nothing-to-fix · ci-stuck · tests-red · limited · error
                SETTLED = nothing-to-fix, refuted-only, no-changes
```

## Change workflow

1. Work in a worktree: `git worktree add .worktrees/<branch> -b <branch> origin/main`. Never edit the main checkout: the daemon runs it.
2. Test: `python3 -m unittest discover -s tests -v` (about 1 s).
   App (from `app/`): `script/test` (`--filter <Suite>` for one suite), `script/lint`, `script/bundle` → `build/PR Wizard.app`, `script/run`.
   `script/install` quits the installed copy and puts a fresh bundle at `/Applications/PR Wizard.app` (`~/Applications` is root-owned here).
   `script/icon` renders `wand.and.stars` into `Resources/AppIcon.icns`; commit the result. "Open at login" survives a reinstall.
   Never plain `swift test`: under the Command Line Tools it runs 0 tests and exits 0.
3. Dry-run what you can: `review-queue -n`, `pr_review.py run --pr N --reviewer opus --dry-run`, `pr_fix.py dump --pr N`.
4. Push straight to `main` (`git push origin HEAD:main`). Open no PRs here. Then `git -C ~/workdir/review-queue pull --ff-only`.
5. Restart only for daemon code (`bin/review-queue`). Check `review-queue -l` for ▶ rows first: a restart kills in-flight passes.
   `launchctl kickstart -k gui/$(id -u)/local.review-queue`
   `pr_review.py`, `pr_fix.py` and prompts load fresh per run: no restart.
6. Plist template change: `python3 install.py`, then `launchctl bootout gui/$(id -u)/local.review-queue` and
   `launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/local.review-queue.plist`.

Commit style: `~/.gitmessage` (type prefix, 50-char imperative subject, body says what broke and why this fix).

## Operate and debug

```sh
review-queue -l                          # ▶ in work, 1..n review order, ✓ ready
review-queue --repo iprally/gitops --wait 42  # --pr/--next/--wait/--prune on gitops (else $IPR_REPO, else iprally)
review-queue --wait 16400                # block until settled at the current head, print JSON
review-queue --next 16400                # bump; counts as a review request
review-queue --pr 16400                  # review now, past every gate and label
review-queue --bg                        # SIGUSR1 refresh, or start the daemon
review-queue --prune -n                  # which worktrees the daemon would prune (every repo)
tail -f ~/Library/Logs/review-queue.log
curl -s --unix-socket ~/.local/state/pr-wizard/api.sock http://x/v1/queue   # GET info, queue, config, prompts/<name>
```

Re-arm a parked fix pass (fix status stuck after `FIX_ERRORS` = 3):

```sh
sqlite3 ~/.local/state/pr-wizard/state.db "UPDATE fixes SET key = NULL, errors = 0 WHERE repo = 'iprally/iprally' AND number = 16400"
```

Then `review-queue --bg`.

Clear a false clean: run the reviewer with `--force`, or delete its `clean_reviews` row for that `(repo, number, sha)`.

## Gotchas

- **False clean.** A reviewer that never ran can report `no-findings`. `false_clean()` retries with `--force`
  when the summary is short or reads like an error. On any `no-findings`, read `summary` first.
- **Full disk.** Worktree build caches (`ui/.shadow-cljs`, `ui/target`, `node_modules`) fill the disk.
  Reviewers and builds then fail with misleading output. Run `df -h` first when anything fails oddly.
- **tests-red cause.** `fix_note` shows only "`<gate>` red in <items>". The cause is in
  `state.db` `fix_state.red` → `result.summary`.
- **launchd priority.** `ProcessType` must stay `Standard`. `Background` pins every child to efficiency cores
  and shadow-cljs aborts with `aborted par-compile … still waiting for`.
- **GraphQL search budget.** `search` queries use a separate hourly bucket that `gh api rate_limit` does not show.
  The queue query costs 8 points. A tight `watch review-queue -l` drains it; `-l` caches for 30 s for that reason.
- **Nested `claude -p`.** Drop `ANTHROPIC_API_KEY`/`ANTHROPIC_AUTH_TOKEN` (a harness key outranks the login and 401s
  on stdout) and pass `stdin=DEVNULL`. `child_env()` does this.
- **No slash commands headless.** `/review` in `claude -p` returns `(none)` without a review. Send a plain prompt.
- **Codex stderr.** `codex exec` echoes the prompt to stderr, so a truncated error tail can hide the cause.
  Re-run the command by hand and keep all of stderr.
- **Codex and worktrees.** Codex obeys a global "always work in a worktree" rule. Every prompt that runs
  outside a worktree must say "work here, do not create a worktree or branch".
- **Round ranges.** A round diffs `last-reviewed..head` only when that range is linear. A merge or rebase
  falls back to `origin/<base>...head`, or the reviewer blames other PRs' code.
- **Stale generated packages.** The Karma gate runs the root `npm run postinstall` first: a base merge leaves
  `loyto/packages/*/output/` stale and the gate runs 0 tests.
- **Notifier.** `terminal-notifier` rejects a `-message` that starts with `[ ( { ' "`; `escaped()` handles it.
  Ready alerts use the copy at `~/.local/share/review-queue/Review Queue.app` (Persistent style).

## Scope rules

- Only the daemon runs `pr_review.py` and `pr_fix.py`. Agents do not run reviewers or wait on reviews by default.
  A push is the hand-off; `--wait` only on request.
- The owner wants one notification only: "Ready for your approval" on a colleague's PR. Do not add more.
- Labels opt out per PR: `no-auto-review`, `no-auto-fix` (both exist in `iprally/iprally`).

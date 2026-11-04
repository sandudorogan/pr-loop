# PR Loop: agent guide

Read this file before you change or operate PR Loop. It holds what an agent needs to work here.
Do not rely on memory files for this repository. When you learn something durable, add it here.

## Docs

`docs/` holds the design. Read the file for the area you change. Record each new owner decision in `decisions.md`.

| File | Holds |
| --- | --- |
| [architecture.md](docs/architecture.md) | one daemon backend, many front ends: processes, lanes, state, config, contracts |
| [api.md](docs/api.md) | the control API contract. Code cites it as `api.md §N`: keep the numbers stable |
| [ui-macos.md](docs/ui-macos.md) | PR Loop.app: toolchain, architecture, scenes, tests |
| [decisions.md](docs/decisions.md) | every settled decision and its reason |
| [status.md](docs/status.md) | open items, who acts, the coupling that remains |

## What it is

A macOS launchd daemon (`local.pr-loop`) that reviews and fixes GitHub PRs for one owner (`gh` user).
One process serves every project. Clients (the CLI, the app) read and change its state through a control API.

```text
 PR Loop.app (ui/)     pr-loop CLI (review-queue, pr-wizard = aliases)     curl
        └───────────── HTTP/1.1 + JSON on ~/.local/state/pr-loop/api.sock (0600) ─────────────┘
                                                │
 pr-loop --daemon ── refresh: one GraphQL call every 5 min (60 s when a worker idles, now on POST /v1/refresh)
   │                   mine + requested + assigned + reviewed, no repo: filter → group by repo → project → pool
   │
   ├─ gates ── review pool (3 workers) ─── pr_review.py run × {opus, codex, quality}
   │   same head · own-diff hash           │ posts 1 review per reviewer, marker in body
   │   trivial · hold · rounds · too big   ▼
   │                          ~/.local/state/pr-loop/state.db (SQLite, WAL)
   │                                       │ my PR, reviewers done, new feedback_key
   │                                       ▼
   ├────────── fix pool (3 workers) ────── pr_fix.py run: codex (sandbox) → fix.gates → commit
   │                                       ▼
   │                           push = new head → next review round
   └─ prune thread: every 30 min, the worktrees of merged or approved PRs in every project
```

- **Projects are detected** (`daemon/pr_loop/projects.py`, api.md §4.7): the repos of every open PR I authored, that requests me,
  that is assigned to me or that I reviewed, plus the keys of `projects` in the config. A project is worked only with a
  checkout: a main checkout under `detect.roots/*/` whose git remote is the repo, or `projects[repo].root`. Without one it
  is listed `no-checkout`, and its PRs are `skipped` rows. The daemon logs `projects: …` when the list changes.
- **New projects take the defaults:** both lanes on. Built-in overrides: `iprally/gitops` has review off, `iprally/iprally` has its fixer gates.
- **Review lane:** my PRs, PRs that request my review, PRs assigned to me, PRs I reviewed before, in every active project.
- **Fix lane:** my PRs only. Input = unresolved threads, review bodies on the head, colleagues' PR comments after the head commit, failed Actions jobs, base conflict.
- **Pools:** one shared review pool and one shared fix pool. `lanes.separate` gives each active project its own pair,
  sized by its effective `workers`. The switch is live: running passes finish in their old pool (`daemon/pr_loop/pools.py`).
- Every PR dict carries `repo`. Lanes, locks and state key on `(repo, number)`: PR numbers of two repos overlap.
- Children run with `PR_LOOP_REPO` and `PR_LOOP_REPO_ROOT` set to the PR's repo, `cwd` = its checkout.
  The scripts and the CLI read `IPR_REPO` / `IPR_REPO_ROOT` when the new names are unset. The daemon ignores both.

## Ground truth (never change)

One daemon process runs for the whole system. Never more than one. This rule does not change.

- That one process watches every configured repo.
- Every PR the owner opened goes into the review queue or the fix queue inside that process.
- Every PR assigned to the owner, or that requests the owner's review, goes into those queues too.
- The workers are threads inside that process.
- The commands a worker runs for one pass are child processes of that pass: `pr_review.py`, `pr_fix.py`, `claude -p`, `codex exec`. They are not daemons.
- Do not add a second launchd job, a per-repo process, or a per-repo socket.
- To support a new repo, add it to the one daemon.

## Config

One JSON file. The chezmoi source is the source of truth (api.md §4.1):

```text
 ~/.config/pr-loop/config.json ──symlink (chezmoi)──▶ ~/.local/share/chezmoi/.pr-loop/config.json (dotfiles git)
```

- The daemon re-reads it by mtime on every refresh. No config change needs a restart. Pools resize live.
- A save (API, app) writes temp + rename beside the real file, so the symlink stays. The daemon never runs git or chezmoi:
  after a change, the owner commits and pushes the dotfiles repo.
- An invalid file never crashes anything: everything runs on defaults, and `GET /v1/config` shows `error`.
- No file = `config.DEFAULTS` = the behaviour before the overhaul.

Three override levels, then the labels (api.md §4.10). Unset keys inherit. Objects merge, arrays replace whole.

```text
 defaults (top-level review / fix, "All repos")   config file
   ⊕ projects["owner/name"]                       config file      any review.* / fix.* key, plus root
   ⊕ PR override (repo, number)                   state.db         any review.* / fix.* key except workers
   ⊗ labels no-auto-review / no-auto-fix          GitHub           can only turn a lane off
   = config.effective_for(repo, number)           the daemon and both scripts read this
```

A PR override drops when the PR merges or closes. A push keeps it.

**Project conventions, not iprally conventions.** The prompts are generic. Each run reads the project's own agent files,
contributing doc, editorconfig, formatter and linter configs and skill list from the checkout at the PR head, and puts
them in `{CONVENTIONS}` (`daemon/pr_loop/conventions.py`, api.md §4.8). The fixer gates (`fix.gates`, api.md §4.9) are per-project config:
iprally's cljfmt and Karma live in its built-in override. A project with no gates runs none, and CI stays its gate.

## Files

The daemon and each UI are separate trees. They share only the API contract.

```text
 daemon/      the backend: pr_loop/ package, review/ runners + prompts, bin/, launchd/, tests/   (Python, stdlib)
 ui/          PR Loop.app, the macOS front end: SwiftPM package, script/                         (Swift)
 contract/    api/v1/ wire fixtures + oracle/ config vectors: both sides test against them
 docs/        the design
 claude/      the pr-review-loop skill for agent-delegator
 install.py   links.json: installs both sides into $HOME
 bin review pr_loop   temporary symlinks into daemon/, for a checkout that still runs the old links;
                        drop them once install.py has re-linked (docs/status.md)
```

| Path | Role |
| --- | --- |
| `daemon/pr_loop/queue.py` | Daemon, queue fetch, gates, both lanes, the local paths of the CLI (`--wait` loop, `-l` and `--next` with the daemon down, `--pr`, tick, `--prune`) |
| `daemon/pr_loop/pools.py` | The worker pools (api.md §4.7): shared, or one review + fix pair per project; `held` spans every pool so no PR runs twice |
| `daemon/pr_loop/cli.py` | The CLI (api.md §5): `-l`, `--next`, `--bg`, `--wait`'s bump, `--pause`, `--resume`, `config` go to the API; daemon down: `-l`/`--next` run on `state.db`, `--bg`/`--wait` kickstart `names.LABEL` |
| `daemon/pr_loop/client.py` | `client.call(method, path, body)` over `api.sock`; raises `Down` (no daemon) or `Failed` (api.md §2 error) |
| `daemon/pr_loop/api.py` | Control API (`api.md`): HTTP/1.1 + JSON on `api.sock`, a server thread in the daemon; `python3 -m pr_loop.api --fake [--socket PATH]` serves the fixtures; `--fake-speed S` and `--fake-empty` (or `PRL_FAKE_SPEED`, `PRL_FAKE_EMPTY=1`) set its knobs |
| `daemon/pr_loop/fake.py` | The stateful in-memory runtime behind `--fake` |
| `daemon/pr_loop/snapshot.py` | The queue snapshot (`GET /v1/queue`, `-l`): rows, groups, ranks, findings digests |
| `daemon/pr_loop/history.py` | `GET /v1/history` (api.md §3.13): a row per review or fix result, written in the result's transaction; merged/closed lookup of PRs that left the fetch (one batched `pullRequest(number:)` query per 20 PRs, ~1 point, only for open rows, an open PR is asked again after 30 min); the one-time seed from the stored results (`meta.history_seeded`) |
| `daemon/pr_loop/projects.py` | Project detection: the checkout scan of `detect.roots` and the project list with its status |
| `daemon/pr_loop/config.py` | `DEFAULTS`, load (never raises), validate, atomic save, `effective_for()` |
| `daemon/pr_loop/db.py` | `state.db`: schema by `user_version`, one connection per thread, every write `BEGIN IMMEDIATE` |
| `daemon/pr_loop/names.py` | Repos, the label and every state, log and skill path; `migrate()` / `reverse()` of the old JSON state |
| `daemon/bin/pr-loop` | CLI entry point: puts `daemon/` on `sys.path`, runs `pr_loop.cli.main()`. `daemon/bin/review-queue` is a symlink to it |
| `daemon/review/pr_review.py` | One reviewer on one PR: scope the round, run the engine, post the review |
| `daemon/review/pr_fix.py` | One fix pass on one PR: collect feedback, Codex, gate, land, reply/resolve |
| `daemon/review/prompts/*.md` | Prompt templates. `{PR}`, `{REPO}`, `{HEAD}`, `{BASE}`, `{DIFF_RANGE}`, `{ROUND_NOTE}`, `{BRIEF}`, `{SCHEMA}`, `{FEEDBACK}`, `{FILES}`, `{CONVENTIONS}`; a `{SKILL name}…{/SKILL}` block stays only when the project lists that skill (`{PATH}` = its SKILL.md). No project's rules belong in a prompt |
| `daemon/pr_loop/gates.py` | The project's `fix.gates` (format, then test) run after Codex, `{GATES}` in `fix.md`, the retry prompt. iprally's cljfmt and Karma are its built-in override in `config.DEFAULTS`; a project without gates runs none |
| `daemon/pr_loop/conventions.py` | A project's own conventions read from the checkout at the PR head (agent files and their `@` includes, contributing doc, editorconfig, formatter configs, skills) → `{CONVENTIONS}`. None found: `needs_conventions` reviewers skip (`no-conventions`) |
| `daemon/review/*-schema.json` | JSON schemas the engines must return |
| `claude/skills/pr-review-loop/` | Claude Code PR watch skill + `scan.py` (used by agent-delegator) |
| `daemon/launchd/local.pr-loop.plist.tmpl` | The one service template, `{{ .chezmoi.homeDir }}` placeholder |
| `install.py`, `links.json` | The one install step: check the tools on the plist PATH, symlink the repo into `$HOME`, render the plist into `.local/`, link the config (chezmoi from `chezmoi source-path`), bootstrap or restart the daemon, `ui/script/install` + open (`--no-app`, `--no-chezmoi`, `--dry-run`) |
| `docs/` | The design: architecture, the API contract (`api.md`, cited by § in the code), the app, decisions, open items |
| `ui/` | PR Loop.app: one SwiftPM package, `PRLoopKit` library (models, no SwiftUI) + thin `PRLoop` app target |
| `contract/api/v1/` | Control API responses. The Swift tests decode them; `daemon/tests/test_api_read.py` asserts the server against them |
| `.github/workflows/test.yml` | Every push and PR: the daemon suite, then the app's tests, lint and contract test |
| `.github/workflows/release.yml` | A `v*` tag push: app test + lint, `ui/script/package`, `ui/script/notes`, `gh release create` with the dmg, zip and `SHA256SUMS` |

Python 3.10+, standard library only. No `requirements.txt`, no packaging. Keep it that way unless a new entry in `docs/decisions.md` changes it.
The app: Swift 6, macOS 26, Command Line Tools only (no Xcode), Swift Testing, no dependencies.

## Installed paths and state

The live service runs the code in the **main checkout** (`~/workdir/review-queue`) through symlinks:

```text
~/.local/bin/pr-loop                         → daemon/bin/pr-loop (launchd runs it)
~/.local/bin/{review-queue,pr-wizard}        → daemon/bin/… → daemon/bin/pr-loop (compat aliases)
~/.claude/skills/delegator/{pr_review.py,pr_fix.py,prompts,*-schema.json} → review/
~/.claude/skills/pr-review-loop              → claude/skills/pr-review-loop
~/Library/LaunchAgents/local.pr-loop.plist   → .local/local.pr-loop.plist (rendered by install.py)
~/.config/pr-loop/config.json                → chezmoi source .pr-loop/config.json
```

`~/.local/state/pr-loop/state.db` holds every piece of state (SQLite, WAL, written through `daemon/pr_loop/db.py` only).
One code path owns each table:

| Table | Owner | Key → shape |
| --- | --- | --- |
| `reviews` | review lane | `(repo, number)` → `{sha, status, verdict, note, rounds, hold, at, files}` |
| `reviewer_results` | review lane | `(repo, number, sha, reviewer)` → `{result, engine, round, digest, conventions, url}`, latest head only |
| `fixes` | fix lane | `(repo, number)` → `{sha, key, status, note, errors, gate, at}` |
| `next` | `--next`, `--wait`, `POST /v1/next` | bumped PRs in order |
| `runs` | live runs | `(repo, number)` → `{pid, lane, since, reviewers}` for `-l` ▶ rows; dead pids ignored |
| `events` | daemon | `ready_for_approval` / `ready_withdrawn` for `GET /v1/events`, last 1000 |
| `history` | both lanes | one row per PR worked on, for `GET /v1/history`; 30 days, at most 500 rows |
| `pr_overrides` | API (`PATCH`/`DELETE …/config`) | `(repo, number)` → partial `review.*`/`fix.*` config |
| `paused_prs` | API (`POST …/pause`, `…/resume`) | `(repo, number)` → `at`; neither lane takes the PR, its row is `paused` |
| `fix_state` | pr_fix.py | Codex session, handled reviews/jobs, deferred threads, `ci_tries`, `reruns`, `red` |
| `clean_reviews` | pr_review.py | `(repo, number, sha, reviewer)` heads a reviewer cleared; 30 days |
| `meta` | daemon | `paused`, `events_epoch`, `imported_at`, `history_seeded` |
| `migration_log` | `migrate()` | every old JSON file moved to `legacy/` |

What stays a file:

| Path | Owner | Role |
| --- | --- | --- |
| `~/.local/state/pr-loop/daemon.{lock,pid}` | daemon | single-daemon flock, pid for SIGUSR1 |
| `~/.local/state/review-queue.lock` | daemon | the pre-rename daemon lock, also held: an old-code daemon and a new one refuse to run together |
| `~/.local/state/pr-loop/api.sock` | daemon | control API socket, `0600` in a `0700` dir; SIGTERM unlinks it, a stale one goes at start |
| `~/.local/state/pr-loop/launchd-label` | daemon | the label to `launchctl kickstart` (`local.pr-loop`), written at every start; the app reads it |
| `~/.local/state/pr-loop/locks/<owner>/<name>/<N>` | both lanes | per-PR flock across processes (`<N>.fix`: a pr_fix.py run) |
| `~/.local/state/pr-loop/slot.{0,1}.lock` | pr_fix.py | 2 `slot: true` gate runs (iprally's Karma) machine-wide |
| `~/.local/state/pr-loop/scratch/<N>-*` | pr_fix.py | Codex scratch dirs |
| `~/.local/state/pr-loop/legacy/<ts>/` | `migrate()` | the old JSON state, moved once |
| `~/.claude/skills/delegator/briefs/<N or branch>.md` | agent-delegator | task brief; branch name with `/` → `+` |
| `~/Library/Logs/pr-loop.log` | all | one shared log; lines of other repos read `gitops#N` |

Every entry point runs `names.migrate()` first. It imports the old JSON files once (`pr-loop migrate -n` shows what),
and `pr-loop migrate --reverse` exports the db back to them.
Review worktrees: `<repo>/.claude/worktrees/.review-<N>` (one per PR, shared by its reviewers).
Fix worktrees: the PR branch's existing worktree, else `<repo>/.claude/worktrees/<branch / → +>`.

## Control API

[docs/api.md](docs/api.md) is the contract. Routes under `/v1`, one request per connection, JSON both ways.

```text
GET    info · queue (long-poll ?since=<rev>&wait=<s>) · events (long-poll) · history · config · prompts/<name>
PUT    config                         PATCH  config                   (base_rev, else 412)
POST   refresh · next · pause · resume
POST   prs/<o>/<n>/<N>/review         review now, past every gate and label, not past review.enabled false
POST   prs/<o>/<n>/<N>/fix            re-arm: fixes.key = NULL, errors = 0, then refresh
POST   prs/<o>/<n>/<N>/pause · resume one PR: no new pass in either lane, a running pass finishes
GET · PUT · PATCH · DELETE   prs/<o>/<n>/<N>/config   the PR override and its effective config
```

**Events.** The daemon has no UI. It records `ready_for_approval` (a colleague's PR reviewed READY) and `ready_withdrawn`
(a new head on it). The app posts the macOS notification from them and catches up on launch with its stored cursor.

**History.** Each review or fix result writes a `history` row. The app shows it as "Recently worked on" when the queue is empty.

## The app

`ui/` builds `PR Loop.app`: the queue window (project sidebar, table, inspector, findings peek), Settings (⌘,: General,
Lanes, Reviewers, Fixer, with a scope dropdown: All repos, then each project), the menu bar extra and the "Ready for your
approval" notification. It is a client only: it talks to the daemon over `api.sock`, and "Start Daemon" kickstarts the
label in `launchd-label` (default `local.pr-loop`). `python3 -m pr_loop.api --fake` (from `daemon/`) serves it without the live daemon.
The ready alert must stay until the owner dismisses it: `NSUserNotificationAlertStyle = alert` makes Persistent the
default on first registration, and General shows a fix-it row while System Settings has PR Loop on Temporary.

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
  The queue maps "every enabled reviewer stops" to `clean`.
- **`feedback_key`.** `head:reviews:unresolved-threads:their-comments[:comments-N][:conflict][:ci-red-N[-running]]`.
  The fix lane runs when the key differs from the last recorded one. Any new kind of input must move the key.
- **Codex never writes git.** It runs `workspace-write` with no network. `pr_fix.py` commits, pushes, replies, resolves.
- **No AI attribution.** `land()` strips `Co-Authored-By` and "Generated with Claude" lines from commit messages.
- **CLI.** `review-queue --wait/--next/--pr/-l` stay as they are: the delegator skill and the `github` agent call them.
  `--pr` ends with `#N  <status>: <note>`.

Status vocabulary:

```text
review status   posted · clean · failed · limited · baseline · unchanged · trivial · held · needs-human · too-big · skipped
                skipped = no enabled reviewer, or the lane is off
review verdict  clean · quality-only · posted          (READY = clean, quality-only)
fix status      pushed · refuted-only · no-changes · nothing-to-fix · ci-stuck · tests-red · limited · error
                SETTLED = nothing-to-fix, refuted-only, no-changes
```

## Change workflow

1. Work in a worktree: `git worktree add .worktrees/<branch> -b <branch> origin/main`. Never edit the main checkout: the daemon runs it.
2. Test the daemon from `daemon/`: `python3 -m unittest discover -s tests -v` (about 1 min; one module: `-p test_paths.py`).
   App (from `ui/`): `script/test` (`--filter <Suite>` for one suite), `script/lint`, `script/bundle` → `build/PR Loop.app`, `script/run`.
   `script/contract` runs `ContractTests` (the real client) against `python3 -m pr_loop.api --fake` on a temp socket; run it after any change to a wire shape, either side.
   `script/install` quits the installed copy and puts a fresh bundle at `/Applications/PR Loop.app` (`~/Applications` is root-owned here).
   `script/icon` renders `arrow.triangle.2.circlepath` into `Resources/AppIcon.icns`; commit the result. "Open at login" survives a reinstall.
   `VERSION=X.Y.Z script/package` → `build/PR-Loop-X.Y.Z.{dmg,zip}` + `build/SHA256SUMS`; without `VERSION` the app reads `1.0.<commit count>`.
   `script/notes vX.Y.Z` prints the release body: install steps + commits since the previous tag.
   Never plain `swift test`: under the Command Line Tools it runs 0 tests and exits 0.
3. Dry-run what you can: `pr-loop -n`, `pr_review.py run --pr N --reviewer opus --dry-run`, `pr_fix.py dump --pr N`.
4. Push straight to `main` (`git push origin HEAD:main`). Open no PRs here. Then `git -C ~/workdir/review-queue pull --ff-only`.
   Release the app: `git tag -a vX.Y.Z -m vX.Y.Z && git push origin vX.Y.Z` (the git config refuses a bare tag). CI builds and publishes it; tag only a commit on `main`.
5. Restart only for daemon code (`daemon/pr_loop/*.py`). Check `pr-loop -l` for ▶ rows first: a restart kills in-flight passes.
   `launchctl kickstart -k gui/$(id -u)/local.pr-loop`
   `pr_review.py`, `pr_fix.py`, prompts and the config load fresh per run: no restart.
6. Plist template or `links.json` change: `~/workdir/review-queue/install.py --no-app` (boots the daemon out, then in).

Commit style: `~/.gitmessage` (type prefix, 50-char imperative subject, body says what broke and why this fix).

## Operate and debug

```sh
pr-loop -l                             # ▶ in work, 1..n review order, ✓ ready (review-queue -l is the same)
pr-loop --wait 16400                   # block until settled at the current head, print JSON
pr-loop --next 16400                   # bump; counts as a review request
pr-loop --pr iprally/gitops#42         # review now, past every gate and label (N alone: --repo, $PR_LOOP_REPO, else iprally)
pr-loop --bg                           # refresh now, or start the daemon
pr-loop --pause                        # workers take no new PR until --resume
pr-loop config --patch '{"review": {"workers": 2}}'   # merge-patch the config (config alone prints it)
pr-loop --prune -n                     # which worktrees the daemon would prune (every repo)
tail -f ~/Library/Logs/pr-loop.log
curl -s --unix-socket ~/.local/state/pr-loop/api.sock http://x/v1/info       # label, pid, config path and error
sqlite3 -readonly ~/.local/state/pr-loop/state.db \
  "SELECT repo, number, status, verdict, note, at FROM reviews ORDER BY at DESC LIMIT 10"
```

Re-arm a parked fix pass (fix status stuck after `fix.max_errors` = 3). No CLI flag does it:

```sh
curl -s --unix-socket ~/.local/state/pr-loop/api.sock -X POST http://x/v1/prs/iprally/iprally/16400/fix
```

It sets `key = NULL, errors = 0` on the `fixes` row and refreshes. Daemon down: run the same `UPDATE fixes` with `sqlite3`, then `pr-loop --bg`.

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
  The queue query costs 10 points (4 searches; logged as `search cost N points` on each refresh line). A tight `watch pr-loop -l` drains it; `-l` caches for 30 s for that reason.
- **Nested `claude -p`.** Drop `ANTHROPIC_API_KEY`/`ANTHROPIC_AUTH_TOKEN` (a harness key outranks the login and 401s
  on stdout) and pass `stdin=DEVNULL`. `child_env()` does this.
- **No slash commands headless.** `/review` in `claude -p` returns `(none)` without a review. Send a plain prompt.
- **Codex stderr.** `codex exec` echoes the prompt to stderr, so a truncated error tail can hide the cause.
  Re-run the command by hand and keep all of stderr.
- **Codex and worktrees.** Codex obeys a global "always work in a worktree" rule. Every prompt that runs
  outside a worktree must say "work here, do not create a worktree or branch".
- **Round ranges.** A round diffs `last-reviewed..head` only when that range is linear. A merge or rebase
  falls back to `origin/<base>...head`, or the reviewer blames other PRs' code.
- **Stale generated packages.** iprally's Karma gate runs the root `npm run postinstall` first: a base merge leaves
  `loyto/packages/*/output/` stale and the gate runs 0 tests.
- **No `@Environment(Model.self)` in a table cell.** A `Table` with a conditional `TableColumn` (Project, shown
  for "All repos" only) rebuilds its cells without the window's environment when the column set changes, and the
  lookup traps ("No Observable object of type PeekModel found"). Read the model in the table view and pass it in.
- **Inspector is an `HStack` column.** On macOS 26 `.inspector` floats over the table in a narrow window, and
  `HSplitView` lays a SwiftUI child out at its `maxWidth`, so the content clips. Keep the column; `ResizeHandle`
  sets its width, from 280 pt up to what leaves the table `QueueTable.minWidth`.
- **No `@FocusState` in a toolbar item.** It never takes focus from there. ⌘F calls `NSWindow.focusToolbarField()`.
  The filter goes before the buttons: NSToolbar overflows from the trailing end, and SwiftUI has no visibility priority.

## Scope rules

- Only the daemon runs `pr_review.py` and `pr_fix.py`. Agents do not run reviewers or wait on reviews by default.
  A push is the hand-off; `--wait` only on request.
- The owner wants one notification only: "Ready for your approval" on a colleague's PR. Do not add more.
- Labels opt out per PR: `no-auto-review`, `no-auto-fix` (both exist in `iprally/iprally`).

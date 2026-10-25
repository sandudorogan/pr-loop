# Architecture

PR Wizard is one backend and many front ends. The backend is one daemon process. It owns all work and all state.
Each front end (the CLI, the macOS app, a later UI for another OS) is a client. A client reads and changes the
daemon's state through the control API ([api.md](api.md)), and through nothing else.

```text
 front ends (clients)                                    backend (one process)
 ───────────────────────                                 ─────────────────────────────────────────────────────────
 PR Wizard.app   (macOS)  ┐                              pr-wizard --daemon   launchd local.pr-wizard
 pr-wizard CLI            ├─ HTTP/1.1 + JSON ──▶ api.sock ──▶ api.py ──▶ Runtime
 curl, later UIs          ┘   one request per connection        │
                                                                ├─ refresh thread  one GraphQL call / 5 min
                                                                ├─ review pool ×3  ─▶ pr_review.py × {opus, codex, quality}
                                                                ├─ fix pool ×3     ─▶ pr_fix.py ─▶ codex exec, fix.gates
                                                                └─ prune thread    every 30 min
                                                                        │
                                                                        ▼
                                              ~/.local/state/pr-wizard/state.db   (SQLite, WAL)
                                              ~/.config/pr-wizard/config.json     (chezmoi symlink)
```

## 1. The one rule

**One daemon process for the whole system. Never more.** This rule does not change.

- One process watches every project, runs both lanes as threads, and serves one socket.
- `pr_review.py`, `pr_fix.py`, `claude -p` and `codex exec` are child processes of one pass. They are not daemons.
- To support a new repo, add it to the one daemon. Do not add a second launchd job, a per-repo process or a per-repo socket.

Two locks enforce it. The daemon takes `pr-wizard/daemon.lock` and the pre-rename `review-queue.lock` with
`flock(LOCK_NB)`. A second daemon, of new or old code, fails to take them and exits.

## 2. Backend and front ends

| | Backend (daemon) | Front end (client) |
| --- | --- | --- |
| Owns | the queue, the lanes, `state.db`, the config file, the GitHub calls, every child process | nothing durable; only view state and per-viewer settings (`UserDefaults`) |
| Talks | serves `api.sock` | calls `api.sock` |
| UI | none. It is system-agnostic: no notification, no window, no OS UI call | all UI, including the "Ready for your approval" notification |
| Started by | launchd (`KeepAlive`) | the owner. A client starts a stopped daemon with `launchctl kickstart gui/<uid>/<label>`; the label is in `~/.local/state/pr-wizard/launchd-label` |
| Language | Python 3.10+, standard library only | per OS. macOS: Swift 6, SwiftUI ([ui-macos.md](ui-macos.md)) |

Rules for every front end, present and future:

- Talk only to `api.sock`. Never read `state.db`, the config file or the log. The CLI is the one exception, because
  it ships with the daemon: `-l` and `--next` read `state.db` when the daemon is down, and `--wait`'s loop reads it (§5).
- Treat the API as versioned (`/v1`). Ignore unknown fields. Keep unknown enum strings.
- Live updates are long-polls: `GET /v1/queue?since=<rev>&wait=<s>` and `GET /v1/events?since=<cursor>&wait=<s>`.
- Daemon down = `connect()` fails with `ENOENT` or `ECONNREFUSED`. Show that state and offer to start the daemon.
- The daemon reports events (`ready_for_approval`, `ready_withdrawn`). The front end decides how to show them, and
  catches up on launch from its stored cursor.

## 3. Daemon components

| Module | Role |
| --- | --- |
| `pr_wizard/queue.py` | the daemon: `Runtime`, the refresh, the gates, both lanes, prune; and the CLI's local paths |
| `pr_wizard/pools.py` | the worker pools: shared, or one review + fix pair per project; `held` spans every pool, so no PR runs twice |
| `pr_wizard/projects.py` | project detection and the checkout scan of `detect.roots` |
| `pr_wizard/api.py` | the control API server and its route table; `--fake` serves `fake.py` |
| `pr_wizard/fake.py` | a stateful in-memory runtime for client tests and UI work without the live daemon |
| `pr_wizard/snapshot.py` | the queue snapshot (`GET /v1/queue`, `-l`) |
| `pr_wizard/history.py` | `GET /v1/history` and the merged/closed lookup of PRs that left the fetch |
| `pr_wizard/config.py` | defaults, load (never raises), validate, atomic save, `effective_for()` |
| `pr_wizard/db.py` | `state.db`: schema by `user_version`, one connection per thread, `BEGIN IMMEDIATE` writes |
| `pr_wizard/conventions.py` | a project's own conventions, read from the checkout at the PR head → `{CONVENTIONS}` |
| `pr_wizard/gates.py` | the project's fixer gates (format, then test) |
| `pr_wizard/names.py` | repos, the label, every state, log and skill path; the one-time JSON → SQLite migration |
| `pr_wizard/cli.py`, `client.py` | the CLI and its socket client |
| `review/pr_review.py` | one reviewer on one PR: scope the round, run the engine, post the review |
| `review/pr_fix.py` | one fix pass on one PR: collect feedback, run Codex, run the gates, commit, push, reply, resolve |
| `review/prompts/*.md`, `review/*-schema.json` | prompt templates and the JSON the engines must return |

## 4. The lanes

```text
 refresh (one GraphQL call, 4 searches, ~10 points)
   my PRs + review requested + assigned + reviewed by me, in any repo
   └─▶ group by repo ─▶ project (has a checkout? lane on?) ─▶ pool
                                                         │
     review gates: same head · own-diff hash · trivial · hold · rounds · too big · labels
                                                         ▼
 review pool ── pr_review.py run × enabled reviewers ── posts one review per reviewer (agent marker in the body)
                                                         │  my PR, reviewers done, new feedback_key
                                                         ▼
 fix pool ───── pr_fix.py run: codex (sandbox, no network) ─▶ fix.gates ─▶ commit ─▶ push
                                                         │
                                                         └─▶ new head ─▶ next review round
```

- **Review lane:** my PRs, PRs that request my review, PRs assigned to me, PRs I reviewed before.
- **Fix lane:** my PRs only. Input: unresolved threads, review bodies on the head, failed Actions jobs, a base conflict.
- **Projects** are detected from those PRs, plus the keys of `projects` in the config. A project is worked only with a
  main checkout under `detect.roots/*/` (or `projects[repo].root`). Without one, it is `no-checkout` (api.md §4.7).
- **Pools** are shared by default: one review pool and one fix pool, because the real limits are per machine.
  `lanes.separate` gives each project its own pair. The switch is live: running passes finish in their old pool.
- **PR identity** is `(repo, number)`. PR numbers of two repos overlap, so every lock, row and key carries `repo`.
- Children run with `cwd` = the PR's checkout and `PR_WIZARD_REPO` / `PR_WIZARD_REPO_ROOT` set.

## 5. State

`~/.local/state/pr-wizard/state.db` holds every piece of state. Schema and tables: AGENTS.md › Installed paths and state.

| Rule | Why |
| --- | --- |
| WAL, `synchronous=NORMAL` | readers never block the writer; a power loss loses at most the last commit |
| every write is `BEGIN IMMEDIATE … COMMIT` | takes the write lock up front, so no read-to-write upgrade deadlocks |
| `busy_timeout` 10 s, one connection per thread | a write takes milliseconds; `sqlite3` connections are not thread-safe |
| one owning code path per table | the scripts also write (`pr_fix.py`: `fix_state`, `pr_review.py`: `clean_reviews`), so two code paths never race on the same rows |
| the daemon polls `PRAGMA data_version` once a second | a commit by a child process wakes the long-pollers |
| schema by `user_version`, created or upgraded by any entry point | the first process to start may be a script run by hand |

What stays a file, and why: the socket; `flock` locks (`daemon.lock`, `locks/<o>/<n>/<N>`, `slot.{0,1}.lock`),
because a lock must release on process death; `daemon.pid`; `launchd-label`, which a client reads to start the
daemon; Codex scratch dirs; the config (durable policy, in dotfiles); the log.

Reads with the daemon down: `-l` reads `state.db` and makes one cached GraphQL call. `--wait` reads `reviews`, `fixes`
and `runs`. `pr_review.py scope` and `pr_fix.py dump` read their own tables.

## 6. Config

One JSON file. The chezmoi source is the source of truth (api.md §4.1):

```text
 ~/.config/pr-wizard/config.json ──symlink──▶ ~/.local/share/chezmoi/.pr-wizard/config.json (dotfiles git)
```

```text
 defaults ("All repos")          config file     top-level review / fix
   ⊕ projects["owner/name"]      config file     any review.* / fix.* key, plus root
   ⊕ PR override (repo, number)  state.db        any review.* / fix.* key except workers
   ⊗ labels no-auto-review / no-auto-fix         can only turn a lane off
   = config.effective_for(repo, number)          the daemon and both scripts read this
```

- The daemon re-reads the file by mtime on every refresh. No config change needs a restart. Pools resize live.
- A save writes temp + rename beside the real file, so the symlink stays. The daemon never runs git or chezmoi.
- An invalid file never crashes anything: everything runs on the defaults, and `GET /v1/config` shows `error`.
- Unset keys inherit. Objects merge. Arrays replace whole. An explicit `null` picks the built-in default (PUT keeps
  it; a merge patch deletes the key instead).
- PR overrides live in `state.db`, not dotfiles: they are short-lived and tied to one PR. They drop when the PR
  merges or closes. A push keeps them.

## 7. Contracts outside the code

Other code depends on these. Break one and something outside this repo breaks quietly. The full list with formats
is in AGENTS.md › Contracts.

| Contract | Who depends on it |
| --- | --- |
| agent marker `<!-- agent-review: reviewer=<id> round=<n> sha=<head> -->`, FYI marker | `scope()`, `pr_fix.py`, `scan.py`; markers already on GitHub PRs, so a new format must still read the old one |
| `feedback_key` | the fix lane runs when it moves; any new kind of input must move it |
| `review-queue --wait/--next/--pr/-l` and their output | the delegator skill, the `github` agent |
| symlinked entry points in `links.json` | agent-delegator (`~/.claude/skills/delegator/{pr_review.py, pr_fix.py, prompts}`, `~/.local/bin/review-queue`) |
| the control API v1 | every front end; `tests/fixtures/api/v1/` pins it on both sides |

## 8. Platform coupling

The backend is macOS-bound in these places only: the launchd plist, `launchctl kickstart`/`bootstrap`,
`ProcessType Standard`, `lsof` for in-use worktrees (needs `/usr/sbin` on `PATH`), and `fcntl` flocks. A port to
another OS replaces the service manager and keeps the API. A front end for another OS needs only the API.

# Decisions

Every settled design decision, with its reason. The owner made or approved each one. Change a decision only with a
stated reason, and record the change here. Most date from the overhaul of 2026-10-25, which turned the
`review-queue` script (`review-queue@3dc9b3f`) into PR Wizard, renamed PR Loop on 2026-11-04 (D31).

## Before and after the overhaul

| What | Before | Now |
| --- | --- | --- |
| Processes | 2 daemons (`IPR_REPO` per process) + a prune job | 1 daemon (`local.pr-loop`), prune is a thread |
| Repos | `iprally/iprally`, `iprally/gitops`, hard-coded | detected from my PRs, worked where a checkout exists |
| Knobs | constants in 3 files | one config file in chezmoi, three override levels |
| Conventions | iprally's, in the prompts | each project's own files, read at the PR head |
| Fixer checks | cljfmt + Karma in `pr_fix.py` | per-project `fix.gates`; iprally's are its built-in override |
| State | `review-queue*.json`, `pr-fix*/`, `.clean-reviews.json`, `now.d/` | `~/.local/state/pr-loop/state.db` |
| Control | SIGUSR1, a shell snippet to re-arm | HTTP/1.1 + JSON on `api.sock` |
| Ready alert | terminal-notifier | `ready_for_approval` events; the app notifies |
| UI | `review-queue -l` | `pr-loop -l` and `PR Loop.app` |
| Code | `daemon/bin/review-queue`, 841 lines | `daemon/pr_loop/` package; `daemon/bin/review-queue` → `daemon/bin/pr-loop` |
| Name | review-queue (repo, label, paths) | PR Loop (D31); `review-queue` and `pr-wizard` stay as CLI aliases |

## Process and transport

**D1. One daemon process for the whole system. Never more.** One process watches every repo, runs the lanes as
threads and serves one socket. *Why:* two daemons worked the same PRs twice and needed per-repo plumbing. Pass
children (`pr_review.py`, `pr_fix.py`, `claude -p`, `codex exec`) are not daemons. This is a permanent invariant.

**D2. The daemon is a server with a control API, like the Docker daemon.** Clients read and change its state
only through the API. *Why:* the CLI, the app and later UIs share one contract ([api.md](api.md)).

**D3. Transport: HTTP/1.1 + JSON over a Unix socket, mode 0600.** No TCP port. *Why:* a localhost port is open to
every local process and to browser CSRF. Only the owner's uid can connect to the socket. Python serves it with the
standard library; Swift talks to it with a POSIX socket.

**D4. Live updates are long-polls, not SSE or WebSockets.** *Why:* one request, one response. A hand-rolled
client needs no streaming parser.

**D5. Prune is a thread of the daemon.** No separate launchd job. *Why:* D1.

**D6. The daemon has no UI and stays system-agnostic.** It reports `ready_for_approval` and `ready_withdrawn`
events. A front end posts the notification. terminal-notifier and `Review Queue.app` are gone. *Why:* other UIs
come later; the daemon must not depend on one OS's notification system.

**D7. One notification only: "Ready for your approval" on a colleague's PR.** It stays on screen until dismissed
(alert style Persistent). Do not add more notifications. *Why:* the owner wants to act on that event only.

## Projects and conventions

**D8. Projects are detected, not hard-coded.** Every repo with an open PR I authored, that requests me, that is
assigned to me or that I reviewed is a candidate. It is worked when a main checkout of it exists under
`detect.roots`. *Why:* the old repo list needed a code change for each new repo.

**D9. A new project inherits the "All repos" defaults, with both lanes on.** A project has specifics only where the
owner overrides them. Built-in overrides: `iprally/gitops` has review off; `iprally/iprally` has its fixer gates.

**D10. Project conventions, not iprally conventions.** The prompts are generic. Each run reads the project's own
agent files, contributing doc, editorconfig, formatter and linter configs and skill list at the PR head. No iprally
rule applies to another project. *Why:* PR Loop now works any repo.

**D11. Fixer gates are per-project config (`fix.gates`).** iprally's cljfmt and Karma are config in its built-in
override, not code. A project without gates runs none, and CI stays its gate.

## Config and state

**D12. One JSON config file; the chezmoi source is the source of truth.** `~/.config/pr-loop/config.json` is a
chezmoi symlink. The daemon saves with temp + rename beside the real file, so the link survives. The daemon never
runs git or chezmoi: the owner commits the dotfiles. *Why:* the config is durable policy and belongs in dotfiles.

**D13. With no config file, the defaults reproduce the old behaviour exactly.** An invalid file never crashes
anything: the daemon runs on the defaults and reports the error.

**D14. Three override levels: All repos → project → PR, then the labels.** Unset keys inherit. Labels
(`no-auto-review`, `no-auto-fix`) can only turn a lane off.

**D15. PR overrides live in `state.db`, not in the config file.** *Why:* they are short-lived and tied to one PR;
in dotfiles they would churn commits and leave stale keys. They drop when the PR merges or closes.

**D16. All state lives in one SQLite database (`state.db`, stdlib `sqlite3`, WAL).** It replaced every JSON state
file. One owning code path per table. *Why:* several processes write state; SQLite transactions make that safe.

**D17. Pools are shared by default.** One review pool (3) and one fix pool (3). `lanes.separate` gives each
project its own pair. *Why:* the real limits (CPU, model quotas) are per machine, not per repo.

**D18. Pause one PR, not only every lane** (`POST …/pause`). *Why:* parking a PR by turning its lanes off hid why
it sat still and mixed a temporary hold into its settings.

**D19. A PR can pick the built-in default over a project value** (2026-10-25). The app sends `PUT …/config` when a
picker's "default" sets `null`; PATCH `null` still means "inherit". *Why:* a merge patch deletes a `null` key, so
the PR inherited the project's model and "Codex default" could not win at the PR level.

## Reviewers and fixer

**D20. Keep the three default reviewers: opus, codex, quality.** *Why:* they work well together.

**D21. Codex never writes git.** It runs `workspace-write` with no network. `pr_fix.py` commits, pushes, replies
and resolves. *Why:* one place controls what lands, and it strips AI attribution.

**D22. No AI attribution anywhere.** No `Co-Authored-By`, no "Generated with". `land()` strips them from commits.

## The macOS app

**D23. A SwiftUI app, proper macOS style, no dependencies, Command Line Tools only.** Details: [ui-macos.md](ui-macos.md).

**D24. The main window has a project sidebar ("All repos", then each project).** Settings has a scope dropdown at
the top instead; each pane shows the selected scope only. The owner settled this over three mockup rounds: a
toolbar project picker replaced the sidebar in round 1, and round 3 brought the sidebar back.

**D25. An empty queue shows "Recently worked on" (history), not a blank view.**

**D26. The hover findings peek is gone.** Space and ⌘Y toggle the peek on the selected row. A non-empty selection
opens the inspector, which shows the same findings. *Why:* the popover opened over any row the pointer crossed
and said little.

**D27. Releases: a `v*` tag publishes a dmg and a zip.** CI builds them from the tag. *Why:* there was no way to
get the app without cloning and building it.

## Process of work

**D28. No PRs in this repo.** Each change lands as commits pushed straight to `main` from a worktree. The main
checkout only fast-forwards, because the live daemon runs it.

**D29. Commits of about 700 changed lines or less, tests included.**

**D30. The GitHub repo is `sandudorogan/pr-loop`** (renamed from `review-queue`, then `pr-wizard`; GitHub
redirects the old URLs). It is public. The local checkout moves to `~/workdir/pr-loop` in the second half of
cutover B ([status.md](status.md)).

**D31. The name is PR Loop** (was PR Wizard): package `pr_loop`, CLI `pr-loop`, label `local.pr-loop`, state
`~/.local/state/pr-loop`, app `PR Loop.app` (`local.pr-loop.app`), icon `arrow.triangle.2.circlepath`. *Why:* in
software a wizard is a step-by-step setup dialog; this is a daemon that loops review → fix → push → review.
`pr-wizard` stays a CLI alias. The daemon still holds `review-queue.lock`, so an old daemon and a new one never run
together. The name sits close to the `pr-review-loop` skill, which is the delegator's watch loop, not this daemon.

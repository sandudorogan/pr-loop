# PR Wizard

A macOS daemon that reviews and fixes your GitHub PRs with Claude Code and Codex. MIT licensed.

It watches every open PR you opened, that requests your review or that is assigned to you, in any repo.
Three reviewers post findings as inline comments.
On your own PRs, headless Codex then fixes the feedback, red CI and base conflicts, and pushes.
The push starts the next review round.

```text
  your PR head ──▶ review ×3 ──settled──▶ fix ──pushed──▶ new head ─┐
       ▲          opus · codex · quality   │ nothing to push → ready │
       └───────────────────────────────────┴─────────────────────────┘
```

| Reviewer | Engine | Looks for |
| --- | --- | --- |
| `opus` | Claude Opus | bugs and risk; checks the change against the task brief when one exists |
| `codex` | Codex (read-only) | adversarial review of the same diff |
| `quality` | Claude Haiku | breaches of the project's documented conventions (skipped when it documents none) |

When one engine hits its usage limit, the reviewer runs on the other.
A round reviews only the commits since the last round.
After 8 rounds in a row with findings, the PR waits for a human.

## How it works

```text
 PR Wizard.app · pr-wizard CLI · curl
        │  HTTP/1.1 + JSON
        ▼
 ~/.local/state/pr-wizard/api.sock ──▶ pr-wizard --daemon (launchd local.pr-wizard, the only process)
                                          │ detects projects from your PRs, finds their checkouts under ~/workdir
                                          │ review pool ×3 · fix pool ×3 (threads), prune every 30 min
                                          ▼
                                 ~/.local/state/pr-wizard/state.db (SQLite)
```

- **Projects.** A repo becomes a project when one of your PRs is in it. PR Wizard works it when it finds a main
  checkout of that repo under `~/workdir/*/`. A new project gets the defaults: review and fix on.
- **Conventions.** The prompts are generic. Each run reads the project's own `AGENTS.md` / `CLAUDE.md`,
  contributing doc, editorconfig, formatter and linter configs and skills from the checkout at the PR head.
- **Gates.** After Codex, the fix pass runs the project's `fix.gates` (format, then test). A project without gates
  runs none, and its CI stays the gate.
- **Config.** `~/.config/pr-wizard/config.json` is a chezmoi-managed symlink to `.pr-wizard/config.json` in your
  chezmoi source. Three levels: all repos → project → PR. The PR level lives in `state.db` and drops when the PR closes.
  Labels opt a PR out: `no-auto-review` skips the reviewers, `no-auto-fix` skips the fix lane.
- **API.** The daemon has no UI. It serves the queue, history, config and `ready_for_approval` events on its socket.
- **App.** `PR Wizard.app` shows the queue and the PRs it worked on recently, edits the config, and posts the
  "Ready for your approval" notification for a colleague's PR.

## Install

Requirements: macOS 26, the Command Line Tools (`xcode-select --install`), Python 3.10+, `gh` (logged in),
Claude Code, Codex.

```sh
git clone git@github.com:sandudorogan/pr-wizard.git ~/workdir/pr-wizard
~/workdir/pr-wizard/install.py
```

```text
 install.py
   1 check   python3 ≥ 3.10 · git · gh logged in · claude · codex      on the daemon's PATH, not your shell's
   2 link    commands, runners, launchd plist, config → $HOME          replaced files → ~/.local/state/review-queue/backups/
   3 start   launchd local.pr-wizard                                   restart when it already runs
   4 app     build PR Wizard.app → /Applications, open it
```

Step 1 stops on any gap and prints the command that fixes it. Run the installer again after a `git pull`:
it restarts the daemon (a restart kills passes in work, see `pr-wizard -l`) and rebuilds the app.

- `--dry-run` prints each step and changes nothing.
- With chezmoi set up (`chezmoi source-path`), the installer writes the default config into the source once and
  applies only the paths it owns. `--no-chezmoi` links straight into `$HOME`.
- `--no-app` installs the daemon only.

Each [release](https://github.com/sandudorogan/pr-wizard/releases) also carries the app as a `.dmg`. It is ad-hoc
signed, so allow its first launch in System Settings → Privacy & Security → **Open Anyway**. The installer builds the
same app from the checkout, with no such step.

The task briefs come from [agent-delegator](https://github.com/sandudorogan/agent-delegator), which also uses the PR watch skill in `claude/`.
PR Wizard runs without either.

## Use

```sh
pr-wizard -l                 # the queue: ▶ in work, 1..n review order, ✓ ready to approve
pr-wizard --pr 16400         # review one PR now (owner/name#N for another repo)
pr-wizard --next 16400       # move a PR to the front
pr-wizard --wait 16400       # block until the PR settles at its head, print JSON
pr-wizard --pause            # workers take no new PR until --resume
pr-wizard config             # print the config (--patch JSON, --put FILE)
pr-wizard -n                 # dry run: print each PR's gate decision
pr-wizard --prune            # remove worktrees of merged or approved PRs (the daemon does it every 30 min)
```

`review-queue` is the same command. A bare `N` is a PR of `--repo`, else `$PR_WIZARD_REPO`, else `iprally/iprally`.

PR Wizard posts reviews, replies and commits with your GitHub credentials.
Log: `~/Library/Logs/pr-wizard.log`. State: `~/.local/state/pr-wizard/`.

## Develop

Read [AGENTS.md](AGENTS.md) first: layout, state, contracts, workflow and gotchas.

```sh
python3 -m unittest discover -s tests -v
cd app && script/test && script/lint
```

### Release

A `v*` tag publishes a GitHub release:

```text
 git push origin v1.2.0 ──▶ .github/workflows/release.yml (macos-26)
                              app/script/test · lint
                              VERSION=1.2.0 app/script/package ──▶ PR-Wizard-1.2.0.dmg   app + Applications link
                                                                  PR-Wizard-1.2.0.zip
                                                                  SHA256SUMS
                              app/script/notes v1.2.0 ──▶ install steps + commits since the last tag
                              gh release create v1.2.0
```

```sh
git tag -a v1.2.0 -m v1.2.0 && git push origin v1.2.0
cd app && VERSION=1.2.0 script/package    # the same files locally, in app/build/
```

The tag sets the app's version (`CFBundleShortVersionString`). The commit count sets its build number.
A local build without `VERSION` reads `1.0.<commit count>`.

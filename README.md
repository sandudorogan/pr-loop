# Review queue

A macOS daemon that reviews and fixes your GitHub PRs with Claude Code and Codex. MIT licensed.

It watches your own PRs and the PRs that request your review.
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
| `quality` | Claude Haiku | breaches of the repo's documented conventions |

When one engine hits its usage limit, the reviewer runs on the other.
A round reviews only the commits since the last round.
After 8 rounds in a row with findings, the PR waits for a human.

The defaults target `iprally/iprally` in `~/workdir/iprally`, and the prompts and the fix lane's test gate carry its conventions.
See [docs/overhaul.md](docs/overhaul.md) for every repo-specific part.

## Install

Requirements: macOS, Python 3.10+, `gh` (logged in), `git`, Claude Code, Codex.

```sh
git clone git@github.com:sandudorogan/review-queue.git ~/workdir/review-queue
cd ~/workdir/review-queue
python3 install.py --dry-run
python3 install.py --chezmoi-source ~/.local/share/chezmoi   # omit the flag without chezmoi
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/local.review-queue.plist
```

The installer symlinks the command, the runners and the launchd plists into `$HOME`.
It backs up what it replaces under `~/.local/state/review-queue/backups/`. It does not start the service.

The "ready" notification uses a copy of `terminal-notifier` at `~/.local/share/review-queue/Review Queue.app`.
The task briefs come from [agent-delegator](https://github.com/sandudorogan/agent-delegator), which also uses the PR watch skill in `claude/`.
The queue runs without either.

## Use

```sh
review-queue -l            # the queue: ▶ in work, 1..n review order, ✓ ready to approve
review-queue --pr 16400    # review one PR now
review-queue --next 16400  # move a PR to the front
review-queue --wait 16400  # block until the PR settles at its head, print JSON
review-queue -n            # dry run: print each PR's gate decision
review-queue --prune       # remove worktrees of merged or approved PRs
```

Labels opt a PR out: `no-auto-review` skips the reviewers, `no-auto-fix` skips the fix lane.
`IPR_REPO=owner/name` runs the queue on another repo (fix lane only), with its own state.

The queue posts reviews, replies and commits with your GitHub credentials.
Log: `~/Library/Logs/review-queue.log`. State: `~/.local/state/review-queue*` and `~/.local/state/pr-fix*`.

## Develop

Read [AGENTS.md](AGENTS.md) first: layout, state files, contracts, workflow and gotchas.

```sh
python3 -m unittest discover -s tests -v
```

# Review queue

Personal PR review and fix service. MIT licensed.
The queue runs Claude Code and Codex reviewers, then fixes actionable feedback on authored PRs.
Its current defaults target `iprally/iprally` in `~/workdir/iprally`.
The prompts and fix checks also contain IPRally conventions.

```text
GitHub PR -> review-queue -> Claude + Codex + quality reviews
                        -> fix authored PRs -> push -> next review round

bin/                 queue command
review/              review and fix runners, schemas, prompts
claude/              Claude Code PR watch skill and scanner
launchd/             macOS service templates
```

## Install

Clone this repository into `~/workdir/review-queue`.
Python 3.10 or later, `gh`, `git`, Claude Code and Codex are required.
Keep the existing notification application at `~/.local/share/review-queue/Review Queue.app`.

```sh
python3 install.py --dry-run
python3 install.py --chezmoi-source ~/.local/share/chezmoi
review-queue --help
```

Omit `--chezmoi-source` if you do not use chezmoi.
The installer backs up replaced files under `~/.local/state/review-queue/backups/`.
It links the command and the old `~/.claude/skills/delegator/` runner paths to this repository.
It renders the launchd templates into the ignored `.local/` directory and links the installed plists there.
With chezmoi, it updates the source first and applies only this repository's paths.
It does not start or restart the service.

Install [agent-delegator](https://github.com/sandudorogan/agent-delegator) separately for the orchestration agents.
The review command can also run without those agents.
The PR watch skill in `claude/` requires Claude Code and the delegator's `pr-fixer` agent.

## Use

```sh
review-queue --list
review-queue --dry-run
review-queue --pr 16400
review-queue --wait 16400
```

The dry run prints queue decisions without running reviewers.
Review and fix commands can publish GitHub feedback and push changes using your existing credentials.
Run `review-queue --help` for the full command list.
The existing launchd service continues to use `~/.local/bin/review-queue`.

Task briefs and `.clean-reviews.json` stay under `~/.claude/skills/delegator/`.
Queue and fix state stay under `~/.local/state/`. Logs stay under `~/Library/Logs/`.
These files remain outside Git. Authentication stays in the existing CLI stores.

## Check

```sh
python3 -m unittest discover -s tests -v
```

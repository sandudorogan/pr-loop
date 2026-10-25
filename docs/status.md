# Status: open items

What is still open after the overhaul. Each item says who acts. Remove an item when it is done, and record any
decision it produced in [decisions.md](decisions.md).

The build of the overhaul is complete: plan units 1–27, app units U1–U18, cutover A (the `local.pr-wizard` label)
and the GitHub half of cutover B (the repo is `sandudorogan/pr-wizard`).

## Owner: needs a decision

**"No ship" with zero findings counts as clean.** Codex can return `verdict: needs-attention`, `findings: []` and a
summary like "No ship: the round 5 blocker remains". `post()` records `no-findings` (clean, stop). `false_clean()`
checks only the summary's length and error words, so the run can count toward clean and the ready alert.
Option: treat a non-ship verdict with zero findings as a false clean, and retry with `--force`.

## Owner: cutover B, the checkout half

The checkout and the install backups keep the old name until then: `~/workdir/review-queue`,
`~/.local/state/review-queue/backups`.

1. Wait until `pr-wizard -l` shows no ▶ rows, then `launchctl bootout gui/$(id -u)/local.pr-wizard`.
2. `mv ~/workdir/review-queue ~/workdir/pr-wizard`, then `git -C ~/workdir/pr-wizard worktree repair`.
3. `ln -s pr-wizard ~/workdir/review-queue`. The link is temporary. The checkout scan reads only real directories,
   so the link adds no second match.
4. `python3 ~/workdir/pr-wizard/install.py`, then commit and push the dotfiles repo.
5. Check: `pgrep -fl -- '--daemon'` shows one process; `curl -s --unix-socket ~/.local/state/pr-wizard/api.sock
   http://x/v1/info` shows `"label": "local.pr-wizard"`; `review-queue --wait <settled N>` returns at once.
6. Optional: point agent-delegator at the new path. The alias keeps it working without this.
7. A week later: when `grep -rn workdir/review-queue ~/.local/share/chezmoi ~/.claude ~/Library/LaunchAgents`
   finds nothing, remove the symlink.

## Owner: dotfiles and system settings

- Commit the dotfiles repo: `symlink_local.pr-wizard.plist.tmpl` (new), the deleted review-queue plist template,
  `.pr-wizard/config.json` and the two `symlink_*` templates.
- System Settings › Notifications › PR Wizard: alert style **Persistent**. General shows a fix-it row while it is Temporary.
- Settings › General › **Open at login** on.

## Owner: checks at the screen

An agent session cannot activate apps or capture the screen, so these wait for the owner.

1. `open "/Applications/PR Wizard.app"`: the window shows the live queue.
2. Menu bar extra › Settings… brings Settings to the front, with the main window open and closed.
3. Select a row, press Space and ⌘Y: the findings peek toggles. Click the table, then type in Filter: spaces type.
4. ⌘0…⌘9, ⏎ opens the PR, the context menu works, VoiceOver reads the sidebar badges.
5. Notifications: a banner click opens the PR; a click with the app quit launches it and opens the PR; deny in
   System Settings → the warning row shows in General.
6. The Fixer pane opens about 1200 pt tall, partly off-screen. Confirm, then cap its height.
7. Inspector at the window minimum: once, the split stuck at detail 820 / inspector 0 and did not recover. It did not
   repeat in a sweep. Open the inspector in a narrow window a few times.
8. Reviewer drag reorder, the gate token field, sheet Cancel/Done, the confirmation dialogs.

## Known limits (app)

- ⇧⌘, switches the inspector to its Settings tab but does not move keyboard focus into it.
- The history table's column minimums can overflow a narrow detail column.

## Known gaps (daemon)

- A `no-auto-fix` PR of mine: `scan.py` drops review threads on my PRs, so nobody acts on them.
- Briefs resolve by bare PR number, so a PR of another repo can pick up an iprally brief with the same number.

## Coupling that remains

| Where | What |
| --- | --- |
| `pr_wizard/names.py` `MONOREPO` | the default repo of a bare `N` on the CLI and in the scripts |
| `pr_wizard/names.py` `REPOS` | the two repos of the old JSON layout, for `migrate()` / `--reverse` only |
| `pr_wizard/config.py` `DEFAULTS` | iprally's gates and gitops' review-off, as built-in project overrides |
| `claude/skills/pr-review-loop/scan.py` | hard-coded `iprally/iprally`; reads `IPR_REPO_ROOT` only |
| `review/pr_review.py` | briefs under `~/.claude/skills/delegator/briefs/`, by bare PR number or branch |
| `claude/skills/pr-review-loop/SKILL.md` | needs agent-delegator's `pr-fixer` and `github` agents |
| `links.json` | the symlinked entry points agent-delegator calls; keep them until it stops calling them |

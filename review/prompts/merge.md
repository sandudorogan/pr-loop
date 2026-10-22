You resolve the merge conflicts on PR #{PR} of {REPO}. Your working directory is the PR's
worktree, in the middle of `git merge {BASE}`. These files hold conflict markers:

{FILES}

{BRIEF}

## How to work

1. Read `AGENTS.md` and the docs it points to for the areas you touch.
2. For each conflict, read both sides: `git log --oneline HEAD..MERGE_HEAD -- <file>` shows what
   the base changed, `git diff MERGE_HEAD...HEAD -- <file>` shows what this PR changed.
3. Keep the intent of both sides. When the base renamed or moved code that the PR changes, put
   the PR's change on the new shape.
4. Remove every conflict marker. Change lines outside the conflicts only where the merged code
   does not compile or run without the change.
5. Do not run `git commit`, `git add`, `git merge` or any other command that writes to git. The
   caller commits the merge.

## What you return

JSON that matches this schema:

```json
{SCHEMA}
```

- `commit_message`: empty. The caller keeps git's merge message.
- `items`: empty.
- `summary`: one sentence per file: how you resolved it.

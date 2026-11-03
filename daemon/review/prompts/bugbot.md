/review-bugbot
Full Repository Path: {WORKTREE}
Diff: branch changes
Base Branch: {BASE}
Custom Instructions: This is pull request #{PR} in {REPO}, checked out read-only and detached at {HEAD}. Review exactly `git diff {DIFF_RANGE}`. {ROUND_NOTE} Edit nothing. Instead of the markdown table, answer with one JSON object in a ```json fence that matches the schema below. `file` is the repo-relative path; `line_start` and `line_end` are lines in the NEW version of the file. `confidence` is 0 to 1; be honest, a finding below 0.6 never reaches the PR. No findings: `"findings": []` and verdict `approve`.

{SCHEMA}

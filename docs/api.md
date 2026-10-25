# PR Wizard control API, v1

This file is the contract between the daemon (`pr-wizard --daemon`, Python) and its clients: the CLI, the SwiftUI app and
later UIs. Code cites it by section (`api.md §3.14`): keep the numbers stable. Where a row says *today*, it names the
code before the overhaul (`review-queue@3dc9b3f`, `queue.py` was `bin/review-queue`). With no config file, the defaults
reproduce that behaviour.

Invariant: **one daemon process for the whole system.** It detects projects from the owner's PRs, works
every project that has a local checkout and a lane on, runs its lanes as threads, and serves one socket. Reviewer and fixer CLIs are children of a
pass, not daemons.

## 1. Transport

```text
 client ──HTTP/1.1 + JSON──▶ ~/.local/state/pr-wizard/api.sock ──▶ pr-wizard --daemon (launchd local.pr-wizard)
        one request per connection, server closes after the response
```

| Item | Rule |
| --- | --- |
| Socket | `~/.local/state/pr-wizard/api.sock`. One fixed path: clients need no discovery. |
| Permissions | Directory `0700`, socket `0600` (bind under `umask 0o177`). No other auth: only the owner's uid can connect. No TCP port. |
| Create | The daemon, after it holds `daemon.lock` (`flock`, one daemon). It holds the lock, so a socket file already there is stale: unlink, then bind. |
| Remove | On SIGTERM (launchd `bootout`, `kickstart -k`): unlink the socket, then `os._exit(143)`. Do not raise `SystemExit`: `ThreadPoolExecutor.__exit__` would wait hours for running passes, and today SIGTERM kills at once. A crash or SIGKILL leaves the file; the next start unlinks it. |
| Daemon down | `connect()` fails with `ENOENT` (no file) or `ECONNREFUSED` (stale file). Both mean "down". |
| Start it | `launchctl kickstart gui/<uid>/<label>`. `<label>` is the one line in `~/.local/state/pr-wizard/launchd-label`. The daemon writes that file at every start, and it stays when the daemon stops. When the file is missing (the daemon has never run API code), the client uses `local.pr-wizard`. `GET /v1/info` also returns `label`. |
| Server | stdlib `socketserver.ThreadingUnixStreamServer` (`daemon_threads = True`) + `http.server.BaseHTTPRequestHandler`. Override `log_message` (`client_address` is `''` on AF_UNIX, the default logger crashes). |
| Request | `Host:` any value (ignored). Body: JSON, `Content-Type: application/json`, `Content-Length` required, max 1 MiB (else 413). |
| Response | Always a JSON body, `Content-Type: application/json; charset=utf-8`, `Content-Length` set, `Connection: close`, never chunked. No 204, no 304. A client reads to EOF and decodes. |
| PR identity | `repo` (`"owner/name"`) + `number`. String form `key` = `"iprally/iprally#17190"`. Numbers alone collide across repos. |
| Times | ISO 8601 with the local offset, seconds precision: `"2026-10-25T12:01:02+03:00"`. `state.db` stores the same ISO strings. The migration converts today's naive local `"%F %T"` values by attaching the local offset. |
| Versioning | Routes under `/v1`. Within v1 the daemon only adds fields and enum values. Clients ignore unknown fields and keep unknown enum strings (Swift: enums with an `.unknown(String)` case). A breaking change is `/v2`. |
| Smoke test | `curl -s --unix-socket ~/.local/state/pr-wizard/api.sock http://pr-wizard/v1/info` |

Live updates use **long-polls** (`GET /v1/queue?since=<rev>&wait=<s>`, `GET /v1/events?since=<cursor>&wait=<s>`).
A long-poll is one ordinary request and one ordinary response, so a hand-rolled `NWConnection` client needs no
SSE or chunked parser.

## 2. Errors

Every 4xx/5xx body:

```json
{"error": {"code": "invalid_config", "message": "2 problems in the config", "details": [
  {"path": "review.workers", "message": "must be an integer from 1 to 8"},
  {"path": "projects[\"iprally/gitops\"].fix.workers", "message": "must be an integer from 1 to 8"}]}}
```

| Field | Type | Note |
| --- | --- | --- |
| `code` | string | stable, machine-readable (table below) |
| `message` | string | one line for a human |
| `details` | array of `{path: string, message: string}` | only for `invalid_config`, else omitted |

| HTTP | `code` | When |
| --- | --- | --- |
| 400 | `bad_request` | malformed JSON, wrong type in a body, bad query value |
| 404 | `not_found` | unknown route, unknown prompt name |
| 404 | `unknown_repo` | `{owner}/{name}` is not a known project (detected in the last fetch or in `config.projects`) |
| 404 | `not_in_queue` | the PR is not in the daemon's last queue fetch |
| 405 | `method_not_allowed` | known route, other method (`Allow:` header set) |
| 409 | `busy` | a live run already holds the PR |
| 409 | `not_mine` | fix action on a PR the owner did not author |
| 409 | `no_auto_fix` | fix action on a PR labeled `no-auto-fix` |
| 409 | `fix_lane_off` | fix action on a project whose `fix` lane is off |
| 409 | `review_lane_off` | review action on a PR whose effective `review.enabled` is false (project or PR override) |
| 409 | `no_checkout` | review or fix action on a project with no local checkout |
| 412 | `stale_config` | `base_rev` does not match the current config `rev` |
| 413 | `payload_too_large` | body over 1 MiB |
| 422 | `invalid_config` | config fails validation (`details` lists every problem) |
| 500 | `internal` | unexpected exception; the daemon logs the traceback |

## 3. Endpoints

| Method | Path | Purpose | CLI today |
| --- | --- | --- | --- |
| GET | `/v1/info` | daemon health and identity | — |
| GET | `/v1/queue` | queue snapshot across every repo, long-poll | `-l` |
| GET | `/v1/events` | `ready_for_approval` events, long-poll | terminal-notifier |
| GET | `/v1/config` | effective config, defaults, choices | — |
| PUT | `/v1/config` | replace the config | — |
| PATCH | `/v1/config` | merge-patch the config | — |
| GET | `/v1/history` | PRs the wizard worked on that settled, merged or closed | — |
| GET | `/v1/prompts/{name}` | one prompt template's text | — |
| POST | `/v1/refresh` | refetch the queue now | `--bg` (SIGUSR1) |
| POST | `/v1/next` | move PRs to the front of the review order | `--next`, `--wait` bump |
| POST | `/v1/prs/{owner}/{name}/{n}/review` | review now, past every gate and label | `--pr` |
| POST | `/v1/prs/{owner}/{name}/{n}/fix` | run a fix pass at the next refresh; re-arms a parked pass | AGENTS.md re-arm snippet |
| GET | `/v1/prs/{owner}/{name}/{n}/config` | the PR's override and effective config (three levels) | new |
| PUT | `/v1/prs/{owner}/{name}/{n}/config` | replace the PR's override (keeps a `null`) | new |
| PATCH | `/v1/prs/{owner}/{name}/{n}/config` | merge-patch the PR's override | new |
| DELETE | `/v1/prs/{owner}/{name}/{n}/config` | drop the PR's override | new |
| POST | `/v1/prs/{owner}/{name}/{n}/pause` | neither lane takes this PR; a running pass finishes | new |
| POST | `/v1/prs/{owner}/{name}/{n}/resume` | undo the PR's pause | new |
| POST | `/v1/pause` | workers take no new PR | new |
| POST | `/v1/resume` | undo pause | new |

Every write wakes all long-pollers.

### 3.1 `GET /v1/info` → 200

```json
{
  "name": "pr-wizard",
  "version": "1.0.0",
  "commit": "3dc9b3f",
  "api": 1,
  "pid": 48973,
  "started_at": "2026-10-25T09:00:00+03:00",
  "uptime_s": 10862,
  "label": "local.review-queue",
  "paused": false,
  "projects": ["…same objects as in GET /v1/queue…"],
  "lanes": {"separate": false, "pools": ["…same as in GET /v1/queue…"]},
  "refresh": {"interval_s": 300, "idle_s": 60, "last_at": "2026-10-25T12:00:41+03:00", "last_error": null},
  "config": {"path": "/Users/sandu.dorogan/.config/pr-wizard/config.json",
             "real_path": "/Users/sandu.dorogan/.local/share/chezmoi/.pr-wizard/config.json",
             "rev": "3f9a0c1d2e4b", "error": null},
  "paths": {
    "socket": "/Users/sandu.dorogan/.local/state/pr-wizard/api.sock",
    "state": "/Users/sandu.dorogan/.local/state/pr-wizard",
    "db": "/Users/sandu.dorogan/.local/state/pr-wizard/state.db",
    "log": "/Users/sandu.dorogan/Library/Logs/pr-wizard.log"
  }
}
```

| Field | Type | Source |
| --- | --- | --- |
| `version` | string | `pr_wizard.__version__` |
| `commit` | string \| null | `git rev-parse --short HEAD` of the checkout at start |
| `api` | int | always `1` in v1 |
| `label` | string | the launchd label this daemon runs under (also in `launchd-label`) |
| `paused` | bool | `POST /v1/pause` state, survives restarts |
| `projects`, `lanes` | | the snapshot's objects (§3.2) |
| `refresh.last_at` | string \| null | end of the last queue fetch; null before the first |
| `refresh.last_error` | string \| null | tail of the last failed fetch, null after a good one |
| `config.real_path` | string | the symlink resolved (the chezmoi source file) |
| `config.error` | string \| null | the file exists but does not parse or validate; the daemon runs on defaults |

### 3.2 `GET /v1/queue` → 200

Query: `since` (string, optional: a `rev` from an earlier response), `wait` (int seconds 0–60, default 0).

- No `since`, or `since` ≠ current `rev`: respond at once.
- `since` = current `rev`: hold until the snapshot changes or `wait` runs out, then respond with the
  current snapshot (same `rev` on timeout). The daemon wakes waiters on its own writes, and once a second it checks
  `PRAGMA data_version` for commits by other processes (a script, a manual `--pr` run).

Client loop: `rev = nil; loop { s = GET /v1/queue?since=rev&wait=55; render(s); rev = s.rev }`.
On a connect error, back off 2 s → 30 s and show "daemon down".

```json
{
  "rev": "b71e09c4d2a35f18",
  "generated_at": "2026-10-25T12:03:10+03:00",
  "fetched_at": "2026-10-25T12:00:41+03:00",
  "paused": false,
  "lanes": {
    "separate": false,
    "pools": [
      {"id": "review", "lane": "review", "repo": null, "workers": 3, "busy": 1, "pending": 1},
      {"id": "fix", "lane": "fix", "repo": null, "workers": 3, "busy": 0, "pending": 0}
    ]
  },
  "projects": [
    {"repo": "iprally/iprally", "status": "active", "available": true, "review": true, "fix": true,
     "checkout": {"path": "/Users/sandu.dorogan/workdir/iprally", "source": "detected"}, "prs": 3, "error": null,
     "conventions": {"ref": "origin/main",
                     "files": ["AGENTS.md", "CLAUDE.md", "api/AGENTS.md", "api/CLAUDE.md", "ui/AGENTS.md", "ui/CLAUDE.md", ".clj-kondo/config.edn"],
                     "skills": ["add-phosphor-icon", "adr", "…", "quality-self-review", "…"]},
     "gates": [{"name": "cljfmt", "kind": "format", "source": "default"}, {"name": "Karma", "kind": "test", "source": "default"}]},
    {"repo": "iprally/gitops", "status": "active", "available": true, "review": false, "fix": true,
     "checkout": {"path": "/Users/sandu.dorogan/workdir/gitops", "source": "detected"}, "prs": 1, "error": null,
     "conventions": {"ref": "origin/main", "files": ["CLAUDE.md"], "skills": ["…from .claude/skills…"]}, "gates": []},
    {"repo": "sandudorogan/dataspex", "status": "active", "available": true, "review": true, "fix": true,
     "checkout": {"path": "/Users/sandu.dorogan/workdir/dataspex", "source": "detected"}, "prs": 1, "error": null},
    {"repo": "clojure/clojurescript-site", "status": "no-checkout", "available": false, "review": false, "fix": false,
     "checkout": null, "prs": 1, "error": null}
  ],
  "refresh": {"last_at": "2026-10-25T12:00:41+03:00", "last_error": null},
  "counts": {"active": 1, "queued": 1, "ready": 1, "idle": 1, "paused": 0},
  "items": [
    {
      "key": "iprally/iprally#17190",
      "repo": "iprally/iprally",
      "number": 17190,
      "title": "feat(search): keep filters on back navigation",
      "url": "https://github.com/iprally/iprally/pull/17190",
      "author": "sandudorogan",
      "mine": true,
      "draft": false,
      "labels": [],
      "head": "5e0c2d9a41b7c3f0e8d6a2b9c4f1e7d3a0b5c8e2",
      "base": "main",
      "additions": 212,
      "deletions": 40,
      "pushed_at": "2026-10-25T11:58:40+03:00",
      "updated_at": "2026-10-25T12:00:03+03:00",
      "requested": false,
      "bumped": false,
      "group": "active",
      "rank": null,
      "status": "reviewing",
      "detail": "since 12:01:02",
      "active": {"lane": "review", "since": "2026-10-25T12:01:02+03:00", "reviewers": [
        {"id": "opus", "state": "running", "attempt": 1, "since": "2026-10-25T12:01:03+03:00"},
        {"id": "codex", "state": "waiting", "attempt": 2, "since": "2026-10-25T12:02:10+03:00"},
        {"id": "quality", "state": "clean", "attempt": 1, "since": "2026-10-25T12:02:41+03:00"}]},
      "review": {"sha": "0aa1c3e9b2d4f6a8c0e2b4d6f8a0c2e4b6d8f0a2", "current": false, "status": "posted",
                 "verdict": "posted", "note": "opus, codex", "rounds": 1, "hold": false,
                 "at": "2026-10-25T10:40:12+03:00"},
      "findings": {"…": "the digest of round 1 at 0aa1c3e9, current: false"},
      "fix": {"sha": "0aa1c3e9b2d4f6a8c0e2b4d6f8a0c2e4b6d8f0a2", "current": false, "status": "pushed",
              "note": "pushed 5e0c2d9a41b7: 3 fixed, 1 refuted, 0 deferred", "errors": 0, "parked": false,
              "at": "2026-10-25T11:58:52+03:00"},
      "fix_queued": false, "override": []
    },
    {
      "key": "iprally/iprally#17201", "repo": "iprally/iprally", "number": 17201,
      "title": "fix(api): retry the export job once", "url": "https://github.com/iprally/iprally/pull/17201",
      "author": "colleague", "mine": false, "draft": false, "labels": [],
      "head": "c3d4e5f60718293a4b5c6d7e8f90a1b2c3d4e5f6", "base": "main", "additions": 35, "deletions": 4,
      "pushed_at": "2026-10-25T11:20:00+03:00", "updated_at": "2026-10-25T11:31:09+03:00",
      "requested": true, "bumped": true, "group": "queued", "rank": 1, "status": "queued",
      "detail": "pushed Sun 11:20", "active": null, "review": null, "findings": null, "fix": null, "fix_queued": false,
      "override": ["review.reviewers"]
    },
    {
      "key": "iprally/iprally#17166", "repo": "iprally/iprally", "number": 17166,
      "title": "refactor(ui): one sub per hop in the filters", "url": "https://github.com/iprally/iprally/pull/17166",
      "author": "colleague", "mine": false, "draft": false, "labels": [],
      "head": "9f8e7d6c5b4a39281706f5e4d3c2b1a098f7e6d5", "base": "main", "additions": 120, "deletions": 98,
      "pushed_at": "2026-10-24T16:02:11+03:00", "updated_at": "2026-10-24T17:44:30+03:00",
      "requested": true, "bumped": false, "group": "ready", "rank": null, "status": "ready",
      "detail": "quality notes only", "active": null,
      "review": {"sha": "9f8e7d6c5b4a39281706f5e4d3c2b1a098f7e6d5", "current": true, "status": "posted",
                 "verdict": "quality-only", "note": "quality", "rounds": 1, "hold": false,
                 "at": "2026-10-24T17:40:02+03:00"},
      "findings": {
        "head": "9f8e7d6c5b4a39281706f5e4d3c2b1a098f7e6d5", "current": true, "round": 2, "at_floor": 2,
        "conventions": ["AGENTS.md", "CLAUDE.md", "ui/AGENTS.md", "ui/CLAUDE.md", ".clj-kondo/config.edn"],
        "reviewers": [
          {"id": "opus", "label": "Claude Opus 5.5", "result": "clean", "engine": "claude",
           "counts": {"critical": 0, "high": 0, "medium": 0, "low": 0}, "at_floor": 0, "top": [], "url": null,
           "at": "2026-10-24T17:38:10+03:00"},
          {"id": "codex", "label": "Codex", "result": "clean", "engine": "codex",
           "counts": {"critical": 0, "high": 0, "medium": 0, "low": 0}, "at_floor": 0, "top": [], "url": null,
           "at": "2026-10-24T17:39:20+03:00"},
          {"id": "quality", "label": "Claude Haiku 5.5 · quality self-review", "result": "posted", "engine": "claude",
           "counts": {"critical": 0, "high": 0, "medium": 2, "low": 1}, "at_floor": 2,
           "top": [{"severity": "medium", "title": "Sub reads app-db with a get-in path", "file": "ui/src/cljs/iprally_ui/filters/subs.cljs", "line": 41},
                   {"severity": "medium", "title": "Event does two things", "file": "ui/src/cljs/iprally_ui/filters/events.cljs", "line": 88},
                   {"severity": "low", "title": "Comment restates the code", "file": "ui/src/cljs/iprally_ui/filters/views.cljs", "line": 12}],
           "url": "https://github.com/iprally/iprally/pull/17166#pullrequestreview-2211", "at": "2026-10-24T17:40:02+03:00"}
        ],
        "top": [
          {"severity": "medium", "title": "Sub reads app-db with a get-in path", "file": "ui/src/cljs/iprally_ui/filters/subs.cljs", "line": 41,
           "reviewer": "quality", "url": "https://github.com/iprally/iprally/pull/17166#pullrequestreview-2211"},
          {"severity": "medium", "title": "Event does two things", "file": "ui/src/cljs/iprally_ui/filters/events.cljs", "line": 88,
           "reviewer": "quality", "url": "https://github.com/iprally/iprally/pull/17166#pullrequestreview-2211"},
          {"severity": "low", "title": "Comment restates the code", "file": "ui/src/cljs/iprally_ui/filters/views.cljs", "line": 12,
           "reviewer": "quality", "url": "https://github.com/iprally/iprally/pull/17166#pullrequestreview-2211"}
        ]
      },
      "fix": null, "fix_queued": false
    },
    {
      "key": "iprally/gitops#412", "repo": "iprally/gitops", "number": 412,
      "title": "chore: bump the search image", "url": "https://github.com/iprally/gitops/pull/412",
      "author": "sandudorogan", "mine": true, "draft": false, "labels": [],
      "head": "77aa0c1e2f3d4b5a69788796a5b4c3d2e1f00f1e", "base": "main", "additions": 2, "deletions": 2,
      "pushed_at": "2026-10-25T10:02:00+03:00", "updated_at": "2026-10-25T10:30:00+03:00",
      "requested": false, "bumped": false, "group": "idle", "rank": null, "status": "skipped",
      "detail": "review lane off", "active": null, "review": null, "findings": null,
      "fix": {"sha": "77aa0c1e2f3d4b5a69788796a5b4c3d2e1f00f1e", "current": true, "status": "nothing-to-fix",
              "note": "nothing-to-fix", "errors": 0, "parked": false, "at": "2026-10-25T10:31:12+03:00"},
      "fix_queued": false
    }
  ]
}
```

Snapshot rules (they reproduce `show()` and `row()` in `queue.py`):

- Source: the daemon's last queue fetch (`fetched_at`), the `state.db` tables `reviews`, `reviewer_results`, `fixes`,
  `next`, `runs` (live passes of living pids; `run_reviewer()` updates each reviewer's state there) and
  `pr_overrides`, and the `Runtime` (lanes, projects, refresh). `GET /v1/queue` costs no GitHub call. A push shows up
  at the next refresh. A client that needs it sooner sends `POST /v1/refresh`.
- Items: every fetched PR of every detected project, including projects that are `off` or `no-checkout`
  (as `idle` `skipped` rows), except the ones `approved()` hides (my approval stands, no re-request),
  unless a live run holds it. Order = `-l` order: `(group, priority(), number < max(active), number, repo)` (repo only breaks ties, so `-l` order stays as today; unit 12).
  `priority()` is global: bumped first, then mine, across repos.
- Projects live in the snapshot, not behind a `/v1/projects` endpoint: the project sidebar, the Project column and the Settings scope dropdown
  all change with the same fetch, and one long-poll already delivers them.
- `rev`: first 16 hex of `sha1` over the canonical JSON (`sort_keys`, no spaces) of the snapshot
  without `rev` and `generated_at`. Opaque to clients. Equal snapshots have equal revs across restarts.

| Field | Type | Meaning |
| --- | --- | --- |
| `lanes.separate` | bool | config `lanes.separate` |
| `lanes.pools[]` | `{id, lane, repo, workers, busy, pending}` | one entry per worker pool. Shared mode: exactly `review` and `fix`, `repo: null`. Separate mode: `review:<repo>` / `fix:<repo>` for each project with a checkout and that lane on |
| `lanes.pools[].workers` | int | the configured size |
| `lanes.pools[].busy` | int | PRs a worker of this pool runs now |
| `lanes.pools[].pending` | int | review: `queued` items routed to this pool; fix: fixable PRs no worker took yet |
| `projects[]` | object | every project in the last fetch or in `config.projects`. This feeds the app's project sidebar and the Settings scope dropdown |
| `projects[].available` | bool | `status` is `active` or `off`: a valid checkout exists, so lanes can be turned on |
| `projects[].repo` | string | `owner/name` |
| `projects[].status` | `active` \| `off` \| `no-checkout` \| `error` | `active` = checkout and at least one lane on; `off` = checkout, both lanes off; `no-checkout` = listed, cannot be worked; `error` = a configured `root` that is not a checkout of this repo |
| `projects[].review`, `fix` | bool | effective `review.enabled` / `fix.enabled` (defaults merged with the project's override) |
| `projects[].checkout` | `{path, source: "detected" \| "config"}` \| null | the local checkout the lanes run in |
| `projects[].prs` | int | PRs of this project in the last fetch |
| `projects[].error` | string \| null | why `status` is `error` |
| `projects[].conventions` | `{ref, files, skills}` \| null | what the reviewers and the fixer follow (§4.8), as found on the checkout's default branch at the last scan (`git ls-tree` names, no checkout change): the root sources plus every `AGENTS.md` / `CLAUDE.md` up to 2 levels deep. Per run they are read again at the PR head. Null without a checkout. Settings shows "Follows: AGENTS.md, CLAUDE.md, .editorconfig" |
| `projects[].gates` | [`{name, kind, source}`] | the effective fixer gates (§4.9); `source` = `default` (built-in), `config` (the owner's override) |
| `refresh` | `{last_at, last_error}` | same as `GET /v1/info` `refresh` |
| `key` | string | `"<repo>#<number>"`: unique across repos; use it as the SwiftUI `id` |
| `repo` | string | `repository { nameWithOwner }` (added to the fragment) |
| `number`, `title`, `draft`, `additions`, `deletions` | int/string/bool | GraphQL fragment `pr` |
| `url` | string | `https://github.com/<repo>/pull/<n>` |
| `author` | string | `author { login }` (added to the fragment) |
| `mine` | bool | `viewerDidAuthor` |
| `labels` | [string] | label names |
| `head`, `base` | string | `headRefOid`, `baseRefName` |
| `pushed_at` | string | last commit's `committedDate` |
| `updated_at` | string | PR `updatedAt` (added to the fragment): last activity on GitHub |
| `requested` | bool | my review is requested on GitHub |
| `bumped` | bool | the PR is in the `next` table (counts as a request) |
| `group` | `active` \| `queued` \| `ready` \| `idle` \| `paused` | `row()` groups 0, 1, 3, 4; `paused` (5) = a paused PR without a live run, listed last |
| `paused` | bool | the PR is in `paused_prs` (§3.17), also while its live run finishes |
| `rank` | int \| null | 1..n review order, `queued` only (the `-l` number) |
| `status` | string | the `-l` status column (table below) |
| `detail` | string | the `-l` detail column, human text; do not parse |
| `active` | `{lane: "review" \| "fix", since: string, reviewers: [reviewer progress] \| null}` \| null | a live run holds the PR; `reviewers` is null on the fix lane |
| `active.reviewers[].id` | string | reviewer id from the config |
| `active.reviewers[].state` | `running` \| `waiting` \| `posted` \| `clean` \| `failed` \| `limited` | `running` = an attempt is in flight; `waiting` = backoff before the next attempt; `posted` = left findings to fix; `clean` = `stop: true` (no findings or notes only); `failed` = all `ATTEMPTS` failed; `limited` = both engines at their usage limit |
| `active.reviewers[].attempt` | int 1–3 | current or last attempt (`run_reviewer()` loop) |
| `active.reviewers[].since` | string | when this state began |
| `review` | object \| null | the PR's `reviews` row without `files`, plus `current` (= `sha == head`) |
| `review.status` | string | review status vocabulary (AGENTS.md) |
| `review.verdict` | `clean` \| `quality-only` \| `posted` \| null | |
| `review.rounds` | int | rounds in a row with findings |
| `review.hold` | bool | my PR came out clean: later pushes wait for a request |
| `findings` | object \| null | the findings digest of the last reviewed head (row hover, inspector); null before the first review. Bodies never pass through the API: they stay on GitHub |
| `findings.head`, `current`, `round` | string, bool, int | the reviewed head, `head == item.head`, the marker round |
| `findings.at_floor` | int | findings at or above the fix floor, all reviewers |
| `findings.conventions` | [string] | the convention files injected into that round's prompts (§4.8); `[]` = the project documents none |
| `findings.reviewers[]` | object | one per reviewer that ran on `findings.head` |
| `findings.reviewers[].result` | `posted` \| `notes-only` \| `clean` \| `skipped` \| `failed` \| `limited` | `posted` = findings at the fix floor; `notes-only` = only findings below it (FYI review); `clean` = no findings; `skipped` = a `needs_conventions` reviewer on a project with no conventions (§4.8) |
| `findings.reviewers[].engine` | string | engine that ran (the other one after a fallback) |
| `findings.reviewers[].counts` | `{critical, high, medium, low}` | findings by severity (`review-schema.json` enum) |
| `findings.reviewers[].at_floor` | int | findings at or above the fix floor for that round (`pr_review.to_fix()`) |
| `findings.reviewers[].top` | [`{severity, title, file, line}`] ≤ 3 | that reviewer's worst findings (severity, then confidence) |
| `findings.reviewers[].url` | string \| null | the posted review; null when nothing was posted |
| `findings.top` | [`{severity, title, file, line, reviewer, url}`] ≤ 3 | the worst 3 across reviewers, ranked by the daemon |
| `fix` | object \| null | the PR's `fixes` row without `key`, plus `current` and `parked` |
| `fix.status` | string | fix status vocabulary (AGENTS.md) |
| `fix.errors` | int | errored or red passes in a row |
| `fix.parked` | bool | `errors >= fix.max_errors`: no pass until the feedback key moves or `POST …/fix` |
| `fix_queued` | bool | `fixing()`: the fix lane still owes this head a pass |
| `override` | [string] | config paths the PR overrides (§4.10), e.g. `["review.enabled", "review.reviewers"]`; `[]` = none. The row shows a badge |

| `group` | `status` values | `detail` example |
| --- | --- | --- |
| `active` | `reviewing`, `fixing` | `since 12:01:02` |
| `queued` | `queued` | `pushed Sun 11:20` |
| `ready` | `ready` | `fix nothing-to-fix`, `quality notes only`, `2026-10-24 17:40:02` |
| `paused` | `paused` | `since Sun 14:02` |
| `idle` | a result at this head: the verdict when set, else the review status (`posted`, `quality-only`, `failed`, `limited`, `unchanged`, `trivial`, `baseline`, `held`, `needs-human`, `too-big`); no result at this head: `skipped` (label `no-auto-review`, the project's review lane is off, both lanes off, or no checkout), `new` (baseline on the next run), `held` | `fix queued`, `fix tests-red`, `no-auto-fix`, `no-auto-review`, `review lane off`, `lanes off`, `no checkout`, `--next 17001 to review` |

Everything the app shows comes from this one response: it needs `GET /v1/info` only for identity and paths.
`lanes.pools[].busy` and `refresh.last_at` are part of `rev`, so the snapshot also changes when a refresh ends.

The menu bar's "top 5" = the first 5 `items` (active first, then queued by rank, then ready).

### 3.3 `GET /v1/events` → 200

The daemon reports; UIs notify. One event kind notifies: `ready_for_approval`, which is "Ready for your
approval" on a colleague's PR. `ready_withdrawn` only lets a UI remove a notification it posted earlier. Its id carries the new head (the one whose review started); a UI removes the notification by `key`, whatever head it was posted for.
It never notifies by itself.

Query: `since` (cursor string, optional), `wait` (int seconds 0–60, default 0).

| `since` | Response |
| --- | --- |
| omitted | `events: []` and the current `cursor`: "subscribe from now" (first launch ever) |
| a cursor of this store, behind the head | every retained event after it, at once |
| the current cursor | hold until an event lands or `wait` runs out (`events: []`, same cursor) |
| a cursor of another store (state wiped), or older than the oldest retained event | every retained event, `reset: true` |

```json
{
  "cursor": "k3f9a2.58",
  "reset": false,
  "events": [
    {"id": "ready_for_approval:iprally/iprally#17166@9f8e7d6c5b4a", "seq": 57, "type": "ready_for_approval",
     "key": "iprally/iprally#17166", "repo": "iprally/iprally", "number": 17166,
     "title": "refactor(ui): one sub per hop in the filters", "url": "https://github.com/iprally/iprally/pull/17166",
     "author": "colleague", "head": "9f8e7d6c5b4a39281706f5e4d3c2b1a098f7e6d5", "verdict": "quality-only", "at": "2026-10-24T17:40:02+03:00"},
    {"id": "ready_withdrawn:iprally/iprally#17120@1b2c3d4e5f60", "seq": 58, "type": "ready_withdrawn",
     "key": "iprally/iprally#17120", "repo": "iprally/iprally", "number": 17120,
     "title": "feat(ui): sticky table header", "url": "https://github.com/iprally/iprally/pull/17120",
     "author": "colleague", "head": "1b2c3d4e5f60718293a4b5c6d7e8f90a1b2c3d4e", "verdict": null, "at": "2026-10-25T12:02:00+03:00"}
  ]
}
```

| Field | Type | Meaning |
| --- | --- | --- |
| `cursor` | string | `"<epoch>.<seq>"`. `epoch` is random and is created with the store. Store it and send it back as `since`. |
| `reset` | bool | `since` did not belong to this store: the client replays what it gets and keeps the new cursor |
| `events[].id` | string | `"<type>:<key>@<head[:12]>"`. Stable: the same PR head made ready twice has the same id, so a UI posts it once. Use it as the notification identifier. |
| `events[].seq` | int | order within the store |
| `events[].type` | `ready_for_approval` \| `ready_withdrawn` | more types may come; ignore unknown ones |
| `events[].key`, `repo`, `number`, `title`, `url`, `author`, `head` | | the PR at the moment of the event (`author` = login, for the banner subtitle) |
| `events[].verdict` | `clean` \| `quality-only` \| null | null on `ready_withdrawn` |
| `events[].at` | string | when the daemon recorded it |

When the daemon emits events (the same points where `queue.py` calls terminal-notifier today):

- `ready_for_approval`: `handle()` records `clean` or `posted` with a READY verdict on a PR I did not author.
- `ready_withdrawn`: `handle()` starts a review of a new head on a PR whose last result was READY and not mine
  (today `drop_ready_alert`). A UI removes delivered notifications with the same `key`.

Store: the `events` table in `state.db` (`seq` = `INTEGER PRIMARY KEY AUTOINCREMENT`, so a sequence number is never
reused) and `meta.events_epoch`. It keeps the last 1000 rows, and the insert transaction trims older ones.

Catch-up after an app restart: send the stored cursor. Before posting a `ready_for_approval` from a
catch-up, a UI checks `GET /v1/queue`: post it only when that `key` is still `group: "ready"` at the same `head`.

### 3.4 `GET /v1/config` → 200

```json
{
  "rev": "3f9a0c1d2e4b",
  "path": "/Users/sandu.dorogan/.config/pr-wizard/config.json",
  "real_path": "/Users/sandu.dorogan/.local/share/chezmoi/.pr-wizard/config.json",
  "source": "file",
  "error": null,
  "config": { "...": "the effective config, schema in §4" },
  "defaults": { "...": "the defaults, same schema" },
  "effective": {
    "iprally/iprally": {"root": "/Users/sandu.dorogan/workdir/iprally", "review": {"enabled": true, "workers": 3, "…": "…"}, "fix": {"enabled": true, "…": "…"}},
    "iprally/gitops": {"root": "/Users/sandu.dorogan/workdir/gitops", "review": {"enabled": false, "…": "…"}, "fix": {"enabled": true, "…": "…"}}
  },
  "choices": {
    "engines": ["claude", "codex"],
    "fix_engines": ["codex"],
    "gate_kinds": ["format", "test"],
    "claude_efforts": ["low", "medium", "high", "xhigh", "max"],
    "codex_efforts": ["low", "medium", "high", "xhigh", "max", "ultra"],
    "claude_models": ["opus", "sonnet", "haiku"],
    "codex_default": {"model": "gpt-6.1-sol", "effort": "high"},
    "codex_models": [
      {"model": "gpt-6-astra", "efforts": ["low", "medium", "high", "xhigh", "max", "ultra"], "default_effort": "medium"},
      {"model": "gpt-5.6-sol", "efforts": ["low", "medium", "high", "xhigh", "max", "ultra"], "default_effort": "medium"},
      {"model": "gpt-5.6-luna", "efforts": ["low", "medium", "high", "xhigh", "max"], "default_effort": "medium"}
    ],
    "prompts": ["codex.md", "fix.md", "merge.md", "opus.md", "quality.md"]
  }
}
```

| Field | Type | Meaning |
| --- | --- | --- |
| `rev` | string | first 12 hex of `sha1` over the canonical JSON of `config` |
| `effective` | object keyed `"owner/name"` | for every project in the snapshot: the defaults merged with its override, plus the resolved `root` (null without a checkout). The app shows it and keeps its own resolver only for the "Overridden" markers |
| `real_path` | string | `os.path.realpath(path)`: the chezmoi source file when the symlink is in place |
| `source` | `defaults` \| `file` | `defaults` when the file is missing or invalid |
| `error` | string \| null | why the file was not used (parse error or the first validation problem) |
| `choices.*` | [string] | the app builds pickers from these, never from hard-coded lists. `prompts` = `*.md` in `review/prompts/` |
| `choices.claude_efforts` | [string] | `claude --help` of Claude Code 2.1.310: `low, medium, high, xhigh, max` |
| `choices.codex_efforts` | [string] | the levels codex-cli 0.164.0's model catalog offers. Its parser also takes `none` and `minimal`, but no listed model supports them, so they are left out. Validation accepts only this list |
| `choices.claude_models` | [string] | suggestions; any non-empty string is valid |
| `choices.codex_models` | [`{model, efforts, default_effort}`] | read per request from `~/.codex/models_cache.json` (`slug`, `supported_reasoning_levels`, `default_reasoning_level`); `[]` when the file is missing or unreadable. Suggestions only. Today the cache lists `gpt-6-astra`, `gpt-reserve`, `gpt-5.6-{sol,terra,luna}` and `codex-auto-review`, not the configured `gpt-6.1-sol`. |
| `choices.codex_default` | `{model, effort}` \| null | what a `null` model/effort means: the top-level `model` and `model_reasoning_effort` lines of `~/.codex/config.toml` (today `gpt-6.1-sol`, `high`), read with a line match, so `tomllib` is not needed; null when unreadable. The app shows it as "Codex default (gpt-6.1-sol, high)". The app narrows the effort picker to `efforts` when the chosen model is listed. The daemon does not validate a model/effort pair: codex rejects a bad pair at run time, and the reviewer ends `failed` |

### 3.5 `PUT /v1/config` → 200 (same body as `GET /v1/config`)

```json
{"base_rev": "3f9a0c1d2e4b", "config": {"version": 1, "review": {"workers": 2}}}
```

- `config` is deep-merged over the defaults (objects merge, arrays and scalars replace), then
  validated. So a missing key means "default", and an older client cannot drop a newer knob.
- `base_rev` (optional): when set and ≠ current `rev` → 412 `stale_config` (a hand edit, a
  `chezmoi apply`, or another client saved first). The app sends it. The CLI may leave it out.
- Unknown keys → 422. On success the daemon saves the full merged document (§4.3) and applies it (§4.5).

### 3.6 `PATCH /v1/config` → 200 (same body as `GET /v1/config`)

```json
{"base_rev": "3f9a0c1d2e4b", "patch": {"fix": {"workers": 1}, "review": {"reviewers": ["…full list…"]}}}
```

`patch` is an RFC 7396 merge patch over the current effective config: objects merge, `null` deletes a
key (= back to default; `{"projects": {"o/n": null}}` drops a whole override), arrays replace whole. To change one
reviewer, send the whole `reviewers` list.
Same validation and errors as PUT.

### 3.7 `GET /v1/prompts/{name}` → 200

```json
{"name": "opus.md", "path": "/Users/sandu.dorogan/workdir/review-queue/review/prompts/opus.md",
 "placeholders": ["PR", "REPO", "HEAD", "DIFF_RANGE", "ROUND_NOTE", "BRIEF", "CONVENTIONS", "SCHEMA"],
 "text": "You are reviewing …"}
```

`placeholders`: the known placeholders (`PR`, `REPO`, `HEAD`, `BASE`, `DIFF_RANGE`, `ROUND_NOTE`, `BRIEF`,
`SCHEMA`, `FEEDBACK`, `FILES`, `CONVENTIONS`, `GATES`) that occur as `{NAME}` in `text`, in order of first occurrence.
404 `not_found` when `name` is not in `choices.prompts`. Read-only: prompts change through git.

### 3.8 `POST /v1/refresh` → 202

Body: none or `{}`. Same as SIGUSR1 today: the refresh thread fetches the queue now.

```json
{"accepted": true}
```

### 3.9 `POST /v1/next` → 200

```json
{"prs": [{"repo": "iprally/iprally", "number": 17201}, {"repo": "iprally/iprally", "number": 17190}], "only_queued": true}
```

| Field | Type | Meaning |
| --- | --- | --- |
| `prs` | [`{repo, number}`], 1–20 items | in the wanted order; the first ends up first |
| `only_queued` | bool, default `true` | `true` = `--next`: bump only a PR whose row is `queued` once bumped (a bump counts as a review request, so a `held` PR does get bumped). `false` = `--wait`: prepend every listed PR as given |

```json
{
  "next": ["iprally/iprally#17201", "iprally/iprally#16950"],
  "results": [
    {"key": "iprally/iprally#17201", "bumped": true, "reason": null},
    {"key": "iprally/iprally#17190", "bumped": false, "reason": "active"}
  ]
}
```

`reason` ∈ `null`, `unknown-repo`, `not-in-queue` (not fetched, or approved by me), `active` (in review
or fix), `nothing-new` (a result at this head already), `review-lane-off`. Any bump triggers a refresh.
Bumps live in the `next` table; each bump is one transaction, so no bump is lost.

### 3.10 `POST /v1/prs/{owner}/{name}/{n}/review` → 202

Body: none. Same as `--pr N`: fetch that one PR, review its head past every gate (same head, own-diff,
trivial, held, rounds, too big) and the `no-auto-review` label, in a thread outside the worker pools (as `--pr` runs
beside the daemon today). Runs while paused. It does not override config: a PR whose effective `review.enabled`
is false (project or PR override) returns 409 `review_lane_off`, and a project with no checkout returns 409 `no_checkout`. The app disables Review Now on those
rows. The local CLI `--pr N` keeps today's behaviour and reviews anyway.

```json
{"key": "iprally/iprally#17190", "accepted": true}
```

404 `unknown_repo`. 409 `busy` when a live run holds the PR, `review_lane_off`, `no_checkout`. A closed PR is accepted and logged as "not
an open PR" (the fetch is async). The snapshot shows no change.

### 3.11 `POST /v1/prs/{owner}/{name}/{n}/fix` → 202

Body: none. Sets the PR's `fixes` row to `key = NULL, errors = 0` in one transaction (the AGENTS.md re-arm
snippet), then refreshes. The next refresh sees `key ≠ feedback_key()` and queues a pass, provided
the reviewers are done with the head (or the repo's review lane is off).

```json
{"key": "iprally/gitops#412", "accepted": true}
```

404 `unknown_repo`, `not_in_queue`. 409 `not_mine`, `no_auto_fix`, `fix_lane_off`, `busy`.

### 3.12 `POST /v1/pause`, `POST /v1/resume` → 200

```json
{"paused": true}
```

Pause: review and fix workers take no new PR, running passes finish, and refreshes go on. `review` and
`next` actions still work. The daemon stores pause as `meta.paused` in `state.db`, so a launchd restart stays paused.

### 3.13 `GET /v1/history` → 200

Query: `limit` (int 1–100, default 20), `repo` (optional `owner/name` filter). This is the queue window's empty state.

```json
{
  "entries": [
    {"key": "iprally/iprally#17120", "repo": "iprally/iprally", "number": 17120,
     "title": "feat(ui): sticky table header", "url": "https://github.com/iprally/iprally/pull/17120",
     "author": "colleague", "mine": false, "state": "merged", "outcome": "ready",
     "rounds": 2, "fixes_pushed": 0, "head": "1b2c3d4e5f60718293a4b5c6d7e8f90a1b2c3d4e",
     "first_at": "2026-10-23T09:12:00+03:00", "at": "2026-10-24T15:40:00+03:00",
     "closed_at": "2026-10-24T16:05:00+03:00",
     "findings": {"…": "same digest object as items[].findings in §3.2"}}
  ]
}
```

| Field | Type | Meaning |
| --- | --- | --- |
| `state` | `settled` \| `merged` \| `closed` | `settled` = still open, and its snapshot row is `ready` or `idle` with no `fix_queued` (computed at request time). PRs still `active` or `queued` are left out: they are in the queue |
| `outcome` | string (open enum) | `approved` when my approval stands; else the last result: the review verdict or status (`ready`, `clean`, `posted`, `needs-human`, `too-big`, …), or the fix status when a fix pass ran last (`pushed`, `ci-stuck`, `tests-red`, …) |
| `rounds` | int | the highest marker round reviewed (`pr_review.py` `round`) |
| `fixes_pushed` | int | fix passes that pushed a commit |
| `first_at`, `at` | string | the first and the latest pass on the PR |
| `closed_at` | string \| null | when the daemon saw it merged or closed |
| `findings` | object \| null | the findings digest at the last reviewed head |

Order: `at` descending. Store: the `history` table in `state.db`, upserted in the same transaction as every
review or fix result (daemon, and a local `--pr` run). The daemon keeps 30 days of `at`, at most 500 rows, and trims on
write. When an open entry's PR leaves the queue fetch, the next refresh asks GitHub for its state with one batched
`pullRequest(number:)` query (≤ 20 PRs, not a search), then sets `state` and `closed_at` and drops the PR's override (§4.10).

### 3.14 `GET /v1/prs/{owner}/{name}/{n}/config` → 200

```json
{
  "key": "iprally/iprally#17201",
  "rev": "51c0de9a7b2e",
  "override": {"review": {"reviewers": ["…opus only…"]}, "fix": {"enabled": false}},
  "layers": {"project": ["fix.gates"], "pr": ["review.reviewers", "fix.enabled"]},
  "labels": ["no-auto-review"],
  "effective": {"review": {"enabled": false, "…": "…"}, "fix": {"enabled": false, "…": "…"}},
  "created_at": "2026-10-25T12:10:00+03:00",
  "updated_at": "2026-10-25T12:12:30+03:00"
}
```

| Field | Type | Meaning |
| --- | --- | --- |
| `rev` | string | 12 hex `sha1` of the override's canonical JSON (`null` override → rev of `{}`) |
| `override` | object \| null | the stored PR-level partial override (`review.*`, `fix.*`), null when none |
| `layers.project`, `layers.pr` | [string] | leaf paths set at the project level and at the PR level, for the app's "Overridden" markers |
| `labels` | [string] | `no-auto-review` / `no-auto-fix` on the PR; they force the matching `enabled` to false in `effective` |
| `effective` | object | defaults ⊕ project ⊕ PR, then the labels. This is exactly what the scripts run with |

404 `unknown_repo`, `not_in_queue` (the PR is not in the last fetch).

### 3.15 `PATCH`, `PUT /v1/prs/{owner}/{name}/{n}/config` → 200 (same body as GET)

```json
{"base_rev": "51c0de9a7b2e", "patch": {"review": {"enabled": false}}}
```

An RFC 7396 merge patch over the PR's override (`null` deletes a key, arrays replace whole). It is validated as
the merged effective config. Allowed keys: `review.*` and `fix.*` except `workers` (pools are not per PR);
`root` is not allowed. Errors: 412 `stale_config`, 422 `invalid_config` (`details[].path` like `review.workers`).

`PUT` takes `{"base_rev": …, "override": {…}}` and stores the whole override, with the same rules and errors.
Use it to keep an explicit `null`: `{"fix": {"model": null}}` picks the built-in Codex default over a project's
model. A merge patch cannot say that, because its `null` deletes the key and the PR inherits the project's value.

### 3.16 `DELETE /v1/prs/{owner}/{name}/{n}/config` → 200 (same body as GET, `override: null`)

Drops the override. The daemon also drops it when it sees the PR merged or closed (§3.13 lookup). It keeps an
override across pushes: a new head does not clear it.

### 3.17 `POST /v1/prs/{owner}/{name}/{n}/pause`, `…/resume` → 200

```json
{"key": "iprally/iprally#17201", "paused": true}
```

Pauses one PR: neither lane takes a new pass on it, and its row moves to `group: paused`. A running pass finishes,
and the row stays `active` until then. Resume puts the PR back in both lanes at once, with no GitHub fetch. Review
Now (§3.10) still runs on a paused PR, and `POST /v1/next` leaves it with reason `paused`. The pause is a
`paused_prs` row in `state.db`: it survives restarts and pushes, and the §3.13 lookup drops it when the PR merges or
closes. A PR outside the last fetch is 404 `not_in_queue`.

## 4. Config

### 4.1 Where it lives (chezmoi is the source of truth)

```text
 ~/.config/pr-wizard/config.json ──symlink (chezmoi-managed)──▶ <chezmoi source>/.pr-wizard/config.json
        daemon reads this path                                      real file, in the dotfiles git repo
```

| Piece | Path |
| --- | --- |
| Real file | `{{ .chezmoi.sourceDir }}/.pr-wizard/config.json`, here `~/.local/share/chezmoi/.pr-wizard/config.json`. chezmoi ignores source entries that start with `.`, so it treats the file as data, not as a target. The file still lives in the dotfiles git repo. |
| Symlink template | `{{ .chezmoi.sourceDir }}/dot_config/pr-wizard/symlink_config.json.tmpl`, one line: `{{ .chezmoi.sourceDir }}/.pr-wizard/config.json` |
| What the daemon opens | `~/.config/pr-wizard/config.json` (`PR_WIZARD_CONFIG` env overrides it, for tests) |
| Setup | `install.py --chezmoi-source <dir>` writes the template and, when the real file is missing, seeds it with the defaults, then `chezmoi apply`s the link. Without chezmoi, `install.py` writes a plain file at the target. |

### 4.2 Defaults: today's behaviour exactly

```json
{
  "version": 1,
  "detect": {"roots": ["~/workdir"]},
  "lanes": {"separate": false},
  "projects": {
    "iprally/iprally": {"fix": {"gates": [
      {"name": "cljfmt", "kind": "format", "when": ["*.clj", "*.cljs", "*.cljc", "*.edn"], "requires": "cljfmt",
       "run": "cljfmt fix {files}"},
      {"name": "Karma", "kind": "test", "when": ["ui/src/cljs/*.cljs", "ui/test/*_test.cljs"], "cwd": "ui",
       "prelude": ". ~/.config/nvm/nvm.sh && nvm use 22.15.1 >/dev/null", "needs": ["ui/node_modules"],
       "targets": {"map": [["^ui/src/cljs/(.+)\\.cljs$", "ui/test/\\1_test.cljs"]], "keep": "^ui/test/(.+_test)\\.cljs$",
                   "exists": true, "item": {"/": ".", "_": "-"}, "valid": "^[\\w.-]+$"},
       "setup": {"name": "shadow-cljs compile karma-test",
                 "run": "(cd .. && npm run postinstall) && npx shadow-cljs compile karma-test"},
       "run": "npx karma start --single-run --client.args iprally_ui.karma_runner_test.init --client.args {item}",
       "timeout_s": 1800, "slot": true, "protect": ["shadow-cljs.edn", "karma.conf.js", "package.json"],
       "note": "Do not run tests that need a JVM or a browser (lein, Karma): they abort in this sandbox. The caller runs the Karma namespaces you touch after you finish and sends any failure back to you."}
    ]}},
    "iprally/gitops": {"review": {"enabled": false}}
  },
  "review": {
    "enabled": true,
    "workers": 3,
    "rounds": 8,
    "max_added": 4000,
    "trivial": ["*.lock", "*lock.json", "*.lockb", "*.md", "*.png", "*.jpg", "*.svg"],
    "timeout_s": 2700,
    "reviewers": [
      {"id": "opus", "enabled": true, "label": "Claude Opus 5.5", "prompt": "opus.md",
       "engine": "claude", "fallback": true, "advisory": false,
       "claude": {"model": "opus", "effort": "high", "incremental": {"model": "opus", "effort": "medium"}},
       "codex": {"model": null, "effort": null}},
      {"id": "codex", "enabled": true, "label": "Codex", "prompt": "codex.md",
       "engine": "codex", "fallback": true, "advisory": false,
       "claude": {"model": "opus", "effort": null, "incremental": null},
       "codex": {"model": null, "effort": null}},
      {"id": "quality", "enabled": true, "label": "Claude Haiku 5.5 · quality self-review", "prompt": "quality.md",
       "engine": "claude", "fallback": true, "advisory": true,
       "claude": {"model": "haiku", "effort": "xhigh", "incremental": null},
       "codex": {"model": null, "effort": null}}
    ]
  },
  "fix": {
    "enabled": true,
    "workers": 3,
    "engine": "codex",
    "model": null,
    "effort": null,
    "prompt": "fix.md",
    "merge_prompt": "merge.md",
    "turn_timeout_s": 2700,
    "pass_timeout_s": 14400,
    "max_errors": 3,
    "test_retries": 2,
    "ci_tries": 3,
    "ci_apps": ["github-actions"],
    "gates": []
  },
  "refresh": {"interval_s": 300, "idle_s": 60}
}
```

The top-level `review` and `fix` objects are the defaults for every project ("All projects" in Settings).
`projects["owner/name"]` is a partial override with the same keys (any `review.*` and `fix.*` knob, including
`reviewers`, `gates`, `enabled` and `workers`) plus `root`. Its effective config is the deep merge of the
defaults and the override (objects merge, arrays such as `reviewers` and `trivial` replace whole). `detect`, `lanes`,
`refresh` and `version` are global only.

With these defaults, iprally gets review and fix plus its own fixer gates (its built-in override holds only
`fix.gates`), gitops gets fix only (its built-in override turns review off), and both share one review queue (`review.workers` = 3) and one fix queue (`fix.workers` = 3): today's
behaviour. A newly detected project gets the defaults like any other: both lanes on. Nothing special-cases a
new project. It has its own values only where the owner overrides them in Settings.

### 4.3 Save

1. `real = os.path.realpath(path)` (follows the chezmoi symlink; equals `path` without one).
2. Write `real + f".tmp-{pid}"` in `dirname(real)`, `fsync`, copy the mode of `real` (`0644` when new).
3. `os.replace(tmp, real)`. The symlink is left untouched, and chezmoi sees only a changed source file.
4. Format: `json.dumps(doc, indent=2)` + `"\n"`, keys in default order, so git diffs stay small.

The daemon never runs git or chezmoi. After a settings change the owner commits and pushes the
dotfiles repo. A `chezmoi apply` or `git pull` there changes the file under the daemon, which picks it up
by mtime (§4.5).

### 4.4 Fields

| Path | Type, range | Today | Effect |
| --- | --- | --- | --- |
| `version` | `1` | — | schema version |
| `detect.roots` | [path] 1–10, `~` allowed | `~/workdir/<name>` | dirs whose direct children are scanned for checkouts (§4.7) |
| `lanes.separate` | bool | off | off = one shared review pool + one shared fix pool; on = per-project pools (§4.7) |
| `projects` | object keyed `"owner/name"`, ≤ 50 | two daemons, `IPR_REPO` | per-project partial overrides of `review` and `fix`, plus `root` |
| `projects[…].root` | path \| absent | `IPR_REPO_ROOT` | checkout override; absent = detected. A root that is not a checkout of that repo gives project `status: "error"`, never a validation error |
| `review.enabled` | bool | `MONOREPO` | review lane for a project's PRs (off = `unreviewed()` true) |
| `fix.enabled` | bool | on in both daemons | fix lane for the owner's PRs in a project |
| `review.workers` | int 1–8 | `WORKERS = 3` | shared pool size (separate off); per-project pool size from the effective config (separate on) |
| `review.rounds` | int 1–50 | `ROUNDS = 8` | rounds in a row with findings before `needs-human` |
| `review.max_added` | int 1–100000 | `MAX_ADDED = 4000` | added lines over this → `too-big` |
| `review.trivial` | [glob] ≤ 50, non-empty | `TRIVIAL` | a change to only these files → `trivial` |
| `review.timeout_s` | int 60–14400 | `IPR_REVIEW_TIMEOUT` (2700) | per engine call in `pr_review.py` |
| `review.reviewers` | [reviewer] 1–8, unique `id` | `REVIEWERS` (both files) | the daemon runs every `enabled` one in parallel per PR |
| `fix.workers` | int 1–8 | `FIX_WORKERS = 3` | as `review.workers`, for the fix lane |
| `fix.engine` | `codex` | Codex only | `pr_fix.py` needs Codex sessions (`exec resume`, `thread.started`) |
| `fix.model` | string \| null | null | null = Codex's own config; else `-c model="<m>"` on `exec` and `exec resume` |
| `fix.effort` | codex effort \| null | null | null = Codex's own config; else `-c model_reasoning_effort="<e>"` |
| `fix.prompt`, `fix.merge_prompt` | prompt name | `fix.md`, `merge.md` | templates for the fix turn and the conflict merge |
| `fix.turn_timeout_s` | int 60–14400 | `pr_fix.TIMEOUT = 2700` | per Codex turn |
| `fix.pass_timeout_s` | int 600–86400 | `FIX_TIMEOUT = 14400` | daemon kills a pass after this |
| `fix.max_errors` | int 1–10 | `FIX_ERRORS = 3` | errored/red passes in a row before the PR parks |
| `fix.test_retries` | int 0–5 | `TEST_RETRIES = 2` | Codex retries after a red test gate |
| `fix.ci_apps` | [string] | `checks()` keeps `github-actions` only | GitHub App slugs whose check runs count as CI |
| `fix.ci_tries` | int 1–10 | `CI_TRIES = 3` | refuted looks at one red job before `ci-stuck` |
| `fix.gates` | [gate] ≤ 10 | `gate()`, `karma()`, `namespaces()`, `NODE` in `pr_fix.py` | the fixer's local checks, in order (§4.9). Default `[]`; iprally's built-in override reproduces today's cljfmt + Karma |
| `refresh.interval_s` | int 60–3600 | `REFRESH = 300` | queue fetch period |
| `refresh.idle_s` | int 15–`interval_s` | `IDLE_REFRESH = 60` | fetch period while a review worker idles |

Reviewer object:

| Field | Type | Today (`pr_review.REVIEWERS`) | Effect |
| --- | --- | --- | --- |
| `id` | `^[a-z][a-z0-9-]{0,31}$` | dict key | goes into the agent marker `reviewer=<id>` and the clean cache. Renaming an id makes it re-review heads it already did |
| `enabled` | bool | all three on | the daemon runs enabled reviewers only; `pr_review.py run --reviewer <id>` still runs a disabled one by hand |
| `label` | string 1–80 | `label` | review heading and inline footer; the clean notice lists enabled labels |
| `prompt` | prompt name | `prompt` | template rendered with `{PR}` `{REPO}` `{HEAD}` `{BASE}` `{DIFF_RANGE}` `{ROUND_NOTE}` `{BRIEF}` `{SCHEMA}` |
| `engine` | `claude` \| `codex` | `engine` | primary engine |
| `fallback` | bool | always (`OTHER`) | at the primary's usage limit, run on the other engine; label gets "· run on <Engine>" |
| `needs_conventions` | bool | quality: true, others false | the reviewer reviews only against the project's own rules, so on a project with no conventions (§4.8) `pr_review.py` skips it: `{"posted": false, "stop": true, "reason": "no-conventions"}`, recorded clean at that head, no engine call |
| `advisory` | bool | `note == "quality"` | when only advisory reviewers post findings, the verdict is `quality-only` (READY). The verdict string stays `quality-only`, because the delegator reads it |
| `claude.model` | string \| null | `claude[0]` | `claude -p --model`. Required when `engine` is `claude`, or `codex` with `fallback` |
| `claude.effort` | claude effort \| null | `claude[1]` | `--effort`; null = flag omitted |
| `claude.incremental` | `{model, effort}` \| null | `fix_round` | used instead when the round diffs only the commits since the last round (`base_sha` set); null = same as above |
| `codex.model` | string \| null | none | `codex exec -c model="<m>"`; null = Codex's own config |
| `codex.effort` | codex effort \| null | none | `-c model_reasoning_effort="<e>"` |

`claude effort` = a value of `choices.claude_efforts`; `codex effort` = a value of `choices.codex_efforts`.

Fixed in code, not config (contracts or mechanics): the fix floor (medium/0.6, high from round 4), markers,
`ATTEMPTS = 3` and `BACKOFF` per reviewer, 2 machine-wide slots for `slot: true` gates, `WAIT_POLL`, Codex
sandbox flags, `claude -p --disallowedTools`.

Validation also requires: at least one enabled reviewer in every effective config whose `review.enabled` is true; `prompt`
names that exist; no unknown keys. An invalid or unparsable file never crashes anything: daemon and scripts log the
error and run on defaults, and `GET /v1/config` shows it in `error`. A crash loop under launchd `KeepAlive`
would stop every lane.

### 4.5 When a change takes effect

| Change | Takes effect |
| --- | --- |
| `review.workers`, `fix.workers` | live: a larger pool starts workers at once; a smaller one retires workers as their running pass ends. No pass is killed |
| `review.enabled`, `fix.enabled`, `projects[…].root`, `detect.roots` | the next refresh: lanes route the next fetch; running passes finish |
| `lanes.separate`, per-project `workers` | live, see §4.7 |
| `refresh.*`, `rounds`, `max_added`, `trivial` | the next refresh / next gate decision |
| `review.reviewers` | the next PR a worker takes (the daemon reads the enabled list per PR); `pr_review.py` loads its reviewer definition fresh per run |
| `review.timeout_s`, every `fix.*` knob | the next script run (`pr_review.py`, `pr_fix.py` read the file per run) |
| edit of the real file (hand, `chezmoi apply`, `git pull`) | the daemon notices the mtime on the next refresh or `GET /v1/config` |

No config change needs a daemon restart.

### 4.6 Scripts and repos

The daemon runs each `pr_review.py` / `pr_fix.py` child with `PR_WIZARD_REPO=<owner/name>` and
`PR_WIZARD_REPO_ROOT=<checkout path>` in its env (`IPR_REPO` / `IPR_REPO_ROOT` until the rename unit). The scripts
read and write their own `state.db` tables (`pr_review.py`: `clean_reviews`, `pr_fix.py`: `fix_state`), and use `config.effective_for(repo, number)` (§4.10). Their args stay as they are today.
`pr_review.py run` adds one key to its stdout JSON, `digest` (`{counts, at_floor, top}`), from which the daemon builds `findings`. Its other keys are unchanged.

### 4.7 Projects: detection and lanes

```text
 GraphQL (one call, no repo: qualifier)                   checkout scan (start, every 30 min, on an unknown repo ≤ 1/min)
  mine       is:pr is:open author:@me                       for d in detect.roots/*/ with a .git directory:
  requested  is:pr is:open user-review-requested:@me          git -C d config --get-regexp '^remote\..*\.url$'
  assigned   is:pr is:open assignee:@me                       github.com[:/]owner/name(.git) → repo ↦ d
  reviewed   is:pr is:open reviewed-by:@me -author:@me      override: projects[repo].root
        │ group by repository.nameWithOwner                        │
        └──────────────▶ project = repo ∪ config key ◀─────────────┘
                          status: active | off | no-checkout | error
```

- **Candidates.** Every open PR that I authored, that requests me, or that is assigned to me, in any repo.
  Plus PRs I reviewed before (today's `reviewed` search, since a posted review drops the request). The
  `assigned` search is new.
- **Cost.** 4 searches instead of 3, about 10 points per fetch instead of 8. At most one fetch a minute,
  so it stays far below the hourly GraphQL budget. Each search asks for `issueCount` and
  `pageInfo { hasNextPage endCursor }`. When `issueCount > 50`, that search alone fetches the next page
  (the rare case pays for itself), and the daemon logs "search page 2 for <alias>". The 50-result cap no longer drops PRs.
- **Checkout match.** A remote URL of `git@github.com:owner/name(.git)`, `https://github.com/owner/name(.git)` or
  `ssh://git@github.com/owner/name` maps `owner/name` to the dir. Only main checkouts count (`.git` is a
  directory; worktrees are skipped). When two dirs match, the one named like the repo wins, else the first
  in sort order. `projects[repo].root` overrides the scan; the daemon checks that its remotes include the repo.
- **Working.** A project is worked when it has a checkout and its lane is on. Its PRs enter that lane's pool.
  PRs of `off`, `no-checkout` and `error` projects show as `idle` `skipped` rows, and actions on them return 409 `no_checkout` or `*_lane_off`.
- **Pools.** With `lanes.separate` off there are two pools, `review` (default `review.workers`) and `fix`
  (default `fix.workers`), shared by every active project; per-project `workers` overrides are ignored. With it on,
  every active project gets `review:<repo>` and `fix:<repo>` pools sized by its effective `review.workers` /
  `fix.workers`. Either way there is one process, the pools are thread sets, and the bump/mine
  priority applies within each pool.
- **Live switch.** On a config change the daemon builds the new pool set. Pools that keep their id are resized,
  new pools start, and removed pools retire their workers after the running pass. The `busy` set is global (by `key`) across pools,
  so a PR running in a retiring pool is never taken by its new pool. The next refill routes every pending PR to its new pool.
  No pass is killed and no restart is needed.

### 4.8 Project conventions

The prompts are project-agnostic. Each run injects the conventions of the project it works on, read from the
checkout at the PR head (the review worktree, or the fix worktree), as `{CONVENTIONS}`. No iprally rule
reaches another project, because iprally's rules live in iprally's own files and in its built-in override.

| Order | Source | How |
| --- | --- | --- |
| 1 | `AGENTS.md` (root) | inlined |
| 2 | `CLAUDE.md` (root) | inlined. `@path` lines expand in place, relative to the including file, at most 3 levels deep, and only inside the checkout (`@~/…` is the owner's personal config, which the engines load themselves). A file already included (by realpath, e.g. `@AGENTS.md`) is not repeated |
| 3 | nearest `AGENTS.md` / `CLAUDE.md` above each changed path (e.g. `ui/AGENTS.md`), closest first | inlined; the changed paths are the diff range (review) or the feedback paths plus `git diff {BASE}...HEAD` (fix) |
| 4 | `CONTRIBUTING.md`, else `.github/CONTRIBUTING.md`, else `docs/CONTRIBUTING.md` | inlined |
| 5 | `.editorconfig` | inlined |
| 6 | formatter and linter configs: `.cljfmt.edn`, `cljfmt.edn`, `.clj-kondo/config.edn`, `.prettierrc*`, `prettier.config.*`, `.eslintrc*`, `eslint.config.*`, `biome.json`, `.stylelintrc*`, `ruff.toml`, `.ruff.toml`, `pyproject.toml` (`[tool.ruff]`/`[tool.black]`/`[tool.isort]` tables only), `.flake8`, `rustfmt.toml`, `.rustfmt.toml`, `.golangci.yml`, `.rubocop.yml`, `.swiftformat`, `.swift-format`, `.swiftlint.yml` | inlined when ≤ 2 KB, else listed by path ("read it when it applies") |
| 7 | project skills: `.agents/skills/*/SKILL.md`, `.claude/skills/*/SKILL.md` | listed as `name — description` (frontmatter), never inlined |

- **Cap.** 32 KB in all, 12 KB per document. A cut document ends with `[… truncated: read <path> for the rest]`.
  Once the cap is reached, the remaining sources are listed by path only. The order above is the priority.
- **Rendering.** A `<conventions>` block holds one `### <path>` section per inlined file, then
  `Formatter and linter configs: …` and `Project skills: …` lines. `pr_review.py` and `pr_fix.py` both
  render it, and `findings.conventions` records the file list.
- **None found.** The block reads `<conventions none="true">This project documents no conventions. Judge the
  change against the code around it, and report no convention findings.</conventions>`. A reviewer with
  `needs_conventions: true` (quality) is skipped (§4.4).
- **Quality reviewer.** It reviews against the rules in `<conventions>` and the docs they point to. It follows the
  steps of a project skill named `quality-self-review` only when the conventions list one; for iprally that is
  `.agents/skills/quality-self-review/SKILL.md`, as today. It drops what the listed linters and formatters enforce.
- **Other prompts.** `opus.md` judges "breaches of the project's documented conventions" against the block (the iprally
  doc paths `docs/tech/`, `ui/docs/`, `api/docs/` go). `codex.md`, `fix.md` and `merge.md` get the block in place of
  "Read `AGENTS.md` and the docs it points to".
- **Both engines see the same context.** `claude -p` and `codex exec` also auto-load the checkout's `CLAUDE.md` /
  `AGENTS.md`. The injected copy keeps a fallback run on the other engine equal, and its cost is within the cap.

### 4.9 Fixer gates

`fix.gates` lists the local checks `pr_fix.py` runs after Codex, in order. Format gates run first and never go
red; test gates go red and feed their logs back to Codex (`test_retries`).

| Field | Type | Meaning |
| --- | --- | --- |
| `name` | string | shown in the app, in `fix.note` (`"<name> red in <items>"`) and in the Codex retry prompt |
| `kind` | `format` \| `test` | |
| `when` | [glob] | changed paths that trigger the gate (`fnmatch`, `*` crosses `/`) |
| `run` | string | `bash -c` command (a plain word list, `shlex.join(shlex.split(run)) == run`, runs as that argv directly; same effect, keeps cljfmt's argv golden; unit 11). `{files}` = the matching changed paths (shell-quoted); `{item}` = one target item (test gates) |
| `cwd` | path | relative to the worktree; default `.` |
| `prelude` | string \| absent | prefixed as `<prelude> && <run>` (iprally: the nvm line) |
| `requires` | string \| absent | an executable that must be on PATH, else the gate is skipped silently (today's `shutil.which("cljfmt")`) |
| `needs` | [path] | paths that must exist, else every item reports `ok: null` "`<path>` missing, CI grades it" |
| `targets` | object \| absent | test gates: `map` (regex rewrites of each path), `keep` (the regex a target must match; group 1 is the item), `exists` (the target file must exist), `item` (character replacements on the item), `valid` (the regex an item must match). Absent = one run with `{files}` |
| `setup` | `{name, run}` \| absent | runs once before the items; failure = one red entry named `name` |
| `timeout_s` | int | per command; a timeout is red, and the process group is killed |
| `slot` | bool | takes one of 2 machine-wide slots (cold JVM builds, browsers) |
| `protect` | [path] | files the retry prompt forbids Codex to edit to make a gate pass |
| `note` | string \| absent | the gate's sentence in `{GATES}` of `fix.md` |

- **iprally.** A built-in override `projects["iprally/iprally"].fix.gates` (§4.2) holds today's cljfmt and Karma. It
  produces the same commands, cwd, prelude, order, namespace list, slot use, timeouts, failure names and retry
  prompt text as `pr_fix.py` at `3dc9b3f`. It is config, not code: the steps are explicit, the owner can see and
  edit them in Settings, and nothing about Karma, shadow-cljs or loyto stays in `pr_fix.py`. Detecting them from
  iprally's checkout cannot derive the namespace mapping or the postinstall step.
- **Other projects.** No gates unless the owner adds them. The daemon does not guess commands from `AGENTS.md` or
  `package.json`: a guessed `npm test` can be slow, can need the network, or can be wrong. Instead `{GATES}` tells
  Codex: "The caller runs no checks after you. Run the formatter, linter and tests that the conventions name,
  when they work offline in this sandbox." CI stays the project's real gate: red jobs come back as `ci` feedback.
- **`{GATES}`.** It renders the `note` of each gate, joined by spaces, or the no-gates sentence. For iprally the
  rendered `fix.md` step 6 equals today's text.
- **`pr_fix.py` output.** It is unchanged, plus `gate` (the red gate's name) on `tests-red`. `tests[].ns` keeps its key and holds the item.

### 4.10 Three override levels

```text
 defaults (top-level review / fix, "All repos")      chezmoi config file
   ⊕ projects["owner/name"]                          chezmoi config file
   ⊕ PR override (repo, number)                      state.db table pr_overrides
   ⊗ labels no-auto-review / no-auto-fix              GitHub, forces enabled = false
   = effective(repo, number)
```

- Unset keys inherit from the level above. Objects merge, and arrays (`reviewers`, `gates`, `trivial`) replace whole.
- **PR overrides live in SQLite, not in chezmoi.** They are short-lived and tied to one PR's lifetime, and they
  change often from the app. In the dotfiles repo they would churn commits and leave stale keys for merged PRs.
  The defaults and project overrides are durable policy, which belongs in versioned dotfiles. A PR override is a working
  note about one PR.
- **Allowed per PR:** every `review.*` and `fix.*` key except `workers`. Examples: skip review for this PR
  (`review.enabled: false`), run only opus (`review.reviewers`), turn off a gate, or use another fixer model.
- **Labels keep working.** `no-auto-review` and `no-auto-fix` act as a fourth, highest layer that can only turn a lane
  off. `--pr N` (CLI) still reviews a labeled PR anyway, as today. `POST …/review` still bypasses the label, but not a config
  `review.enabled: false`.
- **Lifetime:** created by `PATCH`; dropped by `DELETE`, or when the daemon sees the PR merged or closed.
- **Scripts.** `pr_review.py` and `pr_fix.py` call `pr_wizard.config.effective_for(repo, number)` themselves. It reads
  the config file and the PR's `pr_overrides` row, so a run by hand (the `github` agent) gets the same config as a
  daemon run. The daemon uses the same function for gates, lanes and the reviewer list.

## 5. CLI over the API

PR arguments take `N` (repo = `--repo`, else `PR_WIZARD_REPO`/`IPR_REPO`, else `iprally/iprally`) or the full form `owner/name#N`.

| Command | Path after the overhaul |
| --- | --- |
| `-l` | `GET /v1/queue`, every project, rendered as today (same columns, OSC 8 links on a tty, `gitops#N` for other repos). Daemon down: prints `daemon down — pr-wizard --bg starts it` to stderr and computes the same snapshot locally (one cached GraphQL call). |
| `--next N` | `POST /v1/next {"prs":[{repo, number}],"only_queued":true}`, prints the reason when not bumped, then the `-l` list |
| `--bg` | `POST /v1/refresh`; daemon down: `launchctl kickstart gui/<uid>/<names.LABEL>` (the CLI ships with the daemon, so it knows its label) |
| `--wait N…` | the bump is `POST /v1/next {"only_queued": false}` (daemon down: kickstart, then retry for 30 s); the wait loop stays local (`heads()` GraphQL + reads of `state.db`), so merged/closed PRs and its JSON output are unchanged |
| `config` | new: `GET /v1/config` → prints `config`; `config --patch '<json>'` → `PATCH`; `config --put FILE` → `PUT` |
| `--pause`, `--resume` | new: `POST /v1/pause`, `/v1/resume` |
| `--pr N` | stays local and blocking: the `github` agent reads its last line for `#N` |
| `-n`, (no args) tick, `--prune`, `--daemon`, `migrate` | local |

## 6. Out of the API

- The menu bar toggle, the notification toggle and the event cursor: app-local (`UserDefaults`).
- Finding bodies and review text: on GitHub, never through the API. Only the digest (`findings`) passes.
- Logs: `~/Library/Logs/pr-wizard.log`, not served.

## 7. Test fixtures

`tests/fixtures/api/v1/` holds one JSON file per response above (`info.json`, `queue.json`,
`events.json`, `history.json`, `config.json`, `pr-config.json`, `prompt.json`, `next.json`, `accepted.json`, `paused.json`,
`error-invalid-config.json`, `error-busy.json`). Python tests assert the server's output for a fixed fake
runtime equals them. Swift tests decode the same files. `python3 -m pr_wizard.api --fake --socket /tmp/prw.sock`
serves that fake runtime. It is stateful and in memory, it starts from the fixtures, and it uses the real route table, validator and
long-poll code. Every accepted action changes the snapshot and wakes the waiters:

| Action | Fake behaviour |
| --- | --- |
| `POST /v1/refresh` | bumps `fetched_at`/`refresh.last_at`; appends one `ready_for_approval` for the first `ready` colleague item |
| `POST /v1/next` | reorders `items` and `rank` as the daemon would |
| `POST …/review` | item → `active` review with three `reviewers` that step `running` → `clean` over ~3 s, then `ready` (colleague: a `ready_for_approval` event) or `idle` `clean` (mine). On a READY item, a `ready_withdrawn` event comes first |
| `POST …/fix` | item → `active` fix for ~3 s, then `fix.status: nothing-to-fix`, `parked: false` |
| `POST /v1/pause`, `/v1/resume` | flips `paused` |
| `PUT`/`PATCH /v1/config` | validated and kept in memory; `rev`, `effective`, `lanes.pools` and `projects` follow |
| `GET /v1/history` | serves the history fixture; a fake PR that reaches `ready` or `clean` is upserted |
| `GET`/`PUT`/`PATCH`/`DELETE …/config` (PR) | kept in memory; `override` on the item and `effective` follow |

`--fake-speed <s>` sets the ~3 s step (`0` = instant, for tests). With the fake, the app exercises every view and notification
without the live daemon.

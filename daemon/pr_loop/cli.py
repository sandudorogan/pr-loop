"""The command line of the one PR Loop daemon. review-queue is the same command.

Usage:
  pr-loop --daemon     launchd job local.pr-loop: 3 workers review, 3 fix my PRs, the queue refreshes every 5 min
  pr-loop              run one review tick now, in this terminal, beside the daemon
  pr-loop --pr 16400   review one PR now, even if its own diff is unchanged
  pr-loop -n           dry run: print each PR's gate decision, review nothing
  pr-loop -l           list the queue: ▶ in review or fix, 1..n review order, ✓ ready to approve
  pr-loop --next 16400 move a PR to the front of the review order
  pr-loop --wait 16400 16401   block until one of these PRs settles at its current head, print it
  pr-loop --bg         refresh the daemon's queue now (starts the daemon if it is down)
  pr-loop --pause      workers take no new PR until --resume
  pr-loop config       print the daemon's config (--patch JSON: merge-patch it, --put FILE: replace it)
  pr-loop --prune      remove the worktrees of PRs that merged or that I approved (-n: dry run)
  pr-loop migrate      import today's JSON state into state.db (-n: dry run, --reverse: export it back)

-l, --next, --bg, --wait, --pause, --resume and config ask the daemon on its socket. With the daemon down, -l and
--next work on state.db here, --bg and --wait start the daemon. --pr, -n, the tick, --prune and migrate run here.
A PR is N (of --repo, else $PR_LOOP_REPO, else $IPR_REPO, else iprally/iprally) or owner/name#N.
State: ~/.local/state/pr-loop/state.db. Log: ~/Library/Logs/pr-loop.log.
"""
import argparse, json, os, re, subprocess, sys, time

from pr_loop import client, names, queue as q, snapshot
from pr_loop.names import LABEL, LOG, MONOREPO

DOWN = "daemon down — pr-loop --bg starts it"
UP_WITHIN = 30
REF = re.compile(r"(?:(?P<repo>[^/#\s]+/[^/#\s]+)#)?(?P<n>\d+)")


def listed(snap):
    print(snapshot.render(snap, sys.stdout.isatty()), end="")


def label():
    """The label the last daemon wrote at its start: the job that is loaded, also before cutover A."""
    try:
        with open(names.LABEL_FILE) as fh:
            return fh.read().strip()
    except FileNotFoundError:
        return LABEL


def start():
    subprocess.run(["launchctl", "kickstart", f"gui/{os.getuid()}/{label()}"], check=True)


def up(method, path, body=None):
    """The daemon's answer. A daemon that is down is started, then asked once a second for UP_WITHIN s."""
    for attempt in range(UP_WITHIN + 1):
        try:
            return client.call(method, path, body)
        except client.Down:
            if attempt == UP_WITHIN:
                raise
            if not attempt:
                start()
            time.sleep(1)


def show():
    try:
        snap = client.call("GET", "/v1/queue")
    except client.Down:
        print(DOWN, file=sys.stderr)
        return q.show()
    listed(snap)


def why(result, snap):
    if result["reason"] == "not-in-queue":
        return "not in the queue"
    item = next(i for i in snap["items"] if i["key"] == result["key"])
    return "already in review" if item["group"] == "active" else f"nothing new to review ({item['status']})"


def bump(repo, n):
    try:
        result = client.call("POST", "/v1/next", {"prs": [{"repo": repo, "number": n}], "only_queued": True})["results"][0]
    except client.Down:
        print(DOWN, file=sys.stderr)
        return q.bump(repo, n)
    snap = client.call("GET", "/v1/queue")
    if not result["bumped"]:
        print(f"#{n}: {why(result, snap)}")
    listed(snap)


def wait(repo, numbers, timeout):
    if pending := q.unsettled(repo, numbers):
        up("POST", "/v1/next", {"prs": [{"repo": repo, "number": n} for n in pending], "only_queued": False})
    else:
        up("POST", "/v1/refresh")
    q.settle(repo, numbers, timeout)


def refresh():
    try:
        client.call("POST", "/v1/refresh")
    except client.Down:
        start()
    print(f"queue refresh requested — tail -f {LOG}")


def configure(patch, put):
    if patch:
        doc = client.call("PATCH", "/v1/config", {"patch": json.loads(patch)})
    elif put:
        with open(put) as fh:
            doc = client.call("PUT", "/v1/config", {"config": json.load(fh)})
    else:
        doc = client.call("GET", "/v1/config")
    print(json.dumps(doc["config"], indent=2))


def pause(on):
    print("paused: workers take no new PR" if client.call("POST", "/v1/pause" if on else "/v1/resume")["paused"]
          else "resumed")


def failed(e):
    details = "".join(f"\n  {d['path']}: {d['message']}" for d in e.error.get("details", []))
    return f"{e.status} {e.error['code']}: {e}{details}"


def ref(ap, text, repo):
    if not (m := REF.fullmatch(text)):
        ap.error(f"{text}: a PR is N or owner/name#N")
    if m["repo"] and m["repo"] not in q.checkouts():
        ap.error(f"{m['repo']}: no local checkout of it under detect.roots or projects[repo].root")
    return m["repo"] or repo, int(m["n"])


def parser():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", nargs="?", choices=["migrate", "config"],
                    help="migrate: import today's JSON state into state.db; config: print the daemon's config")
    ap.add_argument("--reverse", action="store_true", help="migrate: export state.db back to today's JSON files")
    ap.add_argument("--patch", metavar="JSON", help="config: merge-patch the config with this JSON")
    ap.add_argument("--put", metavar="FILE", help="config: replace the config with this JSON file")
    ap.add_argument("--pr", metavar="PR", help="review this PR now, even if its own diff is unchanged")
    ap.add_argument("-n", "--dry-run", action="store_true", help="print gate decisions, review nothing")
    ap.add_argument("-l", "--list", action="store_true", help="list the queue and each PR's last result")
    ap.add_argument("--next", metavar="PR", help="move this PR to the front of the review order")
    ap.add_argument("--wait", nargs="+", metavar="PR",
                    help="block until one of these PRs has a result for its current head, print it as JSON")
    ap.add_argument("--timeout", type=int, default=7200, help="seconds --wait blocks before it prints the pending state")
    ap.add_argument("--bg", action="store_true", help="refresh the daemon's queue now, or start the daemon")
    ap.add_argument("--pause", action="store_true", help="workers take no new PR, running passes finish")
    ap.add_argument("--resume", action="store_true", help="undo --pause")
    ap.add_argument("--daemon", action="store_true", help="review nonstop, refreshing the queue every 5 min")
    ap.add_argument("--prune", action="store_true",
                    help="remove the worktrees of PRs that merged or that I approved, in every repo")
    ap.add_argument("--repo", help="the repo of --pr, --next and --wait (default "
                                                         f"$PR_LOOP_REPO, $IPR_REPO, else {MONOREPO}); --prune: only this repo")
    return ap


def main():
    ap = parser()
    a = ap.parse_args()
    if a.repo and a.repo not in q.checkouts():
        ap.error(f"--repo {a.repo}: no local checkout of it under detect.roots or projects[repo].root")
    repo = a.repo or names.env_repo()
    if a.cmd == "migrate":
        return print("\n".join(names.reverse()) if a.reverse else q.migrated(names.migrate(a.dry_run), a.dry_run))
    if not (a.prune or a.bg):
        names.migrate()
    try:
        if a.cmd == "config":
            return configure(a.patch, a.put)
        if a.pause or a.resume:
            return pause(a.pause)
        if a.list:
            return show()
        if a.next:
            return bump(*ref(ap, a.next, repo))
        if a.wait:
            prs = [ref(ap, text, repo) for text in a.wait]
            if len({r for r, _ in prs}) > 1:
                ap.error("--wait takes the PRs of one repo")
            return wait(prs[0][0], [n for _, n in prs], a.timeout)
        if a.bg:
            return refresh()
    except client.Down:
        sys.exit(DOWN)
    except client.Failed as e:
        sys.exit(failed(e))
    if a.daemon:
        return q.daemon()
    if a.prune:
        sys.exit(q.prune_all([a.repo] if a.repo else q.active(q.queue("--cache", q.LIST_CACHE)), a.dry_run))
    q.tick(ref(ap, a.pr, repo) if a.pr else None, a.dry_run)


if __name__ == "__main__":
    main()

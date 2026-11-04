"""The control API of api.md: HTTP/1.1 + JSON on a Unix socket, one request per connection.

A runtime serves the bodies: `info()`, `snapshot()`, `config()`, `events(since)`, and `changes`, which every change moves.
`history(repo, limit)`, `pr_labels(repo, n)`, `pr_override(repo, n)`. It acts on `save_config(doc)`, `refetch()`,
`bump(prs, only_queued)`, `review(repo, n)`, `fix(repo, n)`, `put_pr_override(repo, n, doc)`, `pause_pr(repo, n, on)` and `pause(on)`.

Usage:
  python3 -m pr_loop.api --fake [--socket PATH] [--fake-speed S] [--fake-empty]
                                                    serve the fixtures of tests/fixtures/api/v1
"""
import argparse, json, os, re, signal, socket, socketserver, sys, threading, time, traceback
from datetime import datetime
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlsplit

from pr_loop import config, db, names

MAX_WAIT = 60
MAX_BODY = 1 << 20
MAX_BUMPS = 20
WRITE = threading.Lock()
PLACEHOLDERS = ("PR", "REPO", "HEAD", "BASE", "DIFF_RANGE", "ROUND_NOTE", "BRIEF", "SCHEMA", "FEEDBACK", "FILES",
                "CONVENTIONS", "GATES")
PLACEHOLDER = re.compile(r"\{(" + "|".join(PLACEHOLDERS) + r")\}")


class Changes:
    """A counter that every change moves. Long-polls wait for it to move past what they saw."""

    def __init__(self):
        self.seen, self.cond = 0, threading.Condition()

    def touch(self):
        with self.cond:
            self.seen += 1
            self.cond.notify_all()

    def wait(self, seen, timeout):
        with self.cond:
            self.cond.wait_for(lambda: self.seen != seen, timeout)


def watch(changes, stopped, every=1):
    """Moves `changes` when another connection commits to state.db: a script, a manual run, another thread."""
    version = db.data_version()
    while not stopped.wait(every):
        if (now := db.data_version()) != version:
            version = now
            changes.touch()


class Problem(Exception):
    def __init__(self, status, code, message, headers=(), details=None):
        super().__init__(message)
        self.status, self.body, self.headers = status, error(code, message, details), dict(headers)


def error(code, message, details=None):
    return {"error": {"code": code, "message": message, **({"details": details} if details is not None else {})}}


def log(msg):
    sys.stdout.write(f"{datetime.now():%F %T}  api     {msg}\n")
    sys.stdout.flush()


def poll(rt, query, read, ready):
    """`read(since)` at once, or when `ready(body, since)` holds, once a change makes it so or `wait` runs out."""
    since, wait = query.get("since", [None])[-1], query.get("wait", ["0"])[-1]
    if not (wait.isdigit() and int(wait) <= MAX_WAIT):
        raise Problem(400, "bad_request", f"wait must be an integer from 0 to {MAX_WAIT}")
    deadline = time.monotonic() + int(wait)
    while True:
        seen = rt.changes.seen
        body = read(since)
        left = deadline - time.monotonic()
        if ready(body, since) or left <= 0:
            return body
        rt.changes.wait(seen, left)


def queue(rt, query):
    """The snapshot at once, or when `since` is the current rev, once it changes or `wait` runs out."""
    return poll(rt, query, lambda since: rt.snapshot(), lambda snap, since: snap["rev"] != since)


def events(rt, query):
    """The events after the `since` cursor at once, or, when it is the current one, once an event lands."""
    return poll(rt, query, rt.events, lambda page, since: since is None or page["reset"] or bool(page["events"]))


def prompt(rt, query, name):
    if name not in config.prompts():
        raise Problem(404, "not_found", f"no prompt {name}")
    path = os.path.realpath(os.path.join(config.PROMPTS, name))
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    return {"name": name, "path": path, "placeholders": list(dict.fromkeys(PLACEHOLDER.findall(text))), "text": text}


def bad(message):
    return Problem(400, "bad_request", message)


def base_rev(body, key):
    """The `base_rev` of a write body that carries an object `key`."""
    if not isinstance(body, dict) or not isinstance(body.get(key), dict):
        raise bad(f"the body must be a JSON object with an object {key}")
    if not isinstance(base := body.get("base_rev"), (str, type(None))):
        raise bad("base_rev must be a string")
    return base


def checked(base, rev, what="config"):
    if base is not None and base != rev:
        raise Problem(412, "stale_config", f"the {what} is at {rev} now, not {base}")


def valid(problems):
    if problems:
        raise Problem(422, "invalid_config", f"{len(problems)} problem{'s' * (len(problems) > 1)} in the config",
                      details=problems)


def configure(rt, body, key, merged):
    """PUT and PATCH: `merged(current, body[key])` over the defaults, checked against `base_rev`, validated, saved."""
    base = base_rev(body, key)
    with WRITE:
        current = rt.config()
        checked(base, current["rev"])
        doc = config.merge(config.DEFAULTS, merged(current["config"], body[key]))
        valid(config.validate(doc))
        return rt.save_config(doc)


def put_config(rt, query, body):
    return configure(rt, body, "config", lambda current, doc: doc)


def patch_config(rt, query, body):
    return configure(rt, body, "patch", config.merge_patch)


def pr_page(rt, repo, n):
    """api.md §3.14: the PR's override, the levels that set each path, its labels and the config its runs get."""
    labels, row, cfg = rt.pr_labels(repo, n), rt.pr_override(repo, n), rt.config()["config"]
    override, project = row and row["config"], cfg["projects"].get(repo) or {}
    return {"key": f"{repo}#{n}", "rev": config.rev(override or {}), "override": override,
            "layers": {"project": config.paths({k: v for k, v in project.items() if k != "root"}),
                       "pr": config.paths(override or {})},
            "labels": [l for l in labels if l in (config.NO_REVIEW, config.NO_FIX)],
            "effective": config.effective(cfg, repo, override, labels),
            "created_at": row and row["created_at"], "updated_at": row and row["updated_at"]}


def pr_config(rt, query, body, owner, name, n):
    return pr_page(rt, f"{owner}/{name}", int(n))


def write_pr_config(rt, body, owner, name, n, key, merged):
    """PUT and PATCH: `merged(override, body[key])`, checked against `base_rev`, validated as the merged effective
    config, stored. Only PUT can keep a null: it is the "use the built-in default" choice over a project value."""
    repo, n, base = f"{owner}/{name}", int(n), base_rev(body, key)
    with WRITE:
        page = pr_page(rt, repo, n)
        checked(base, page["rev"], "override")
        doc = merged(page["override"] or {}, body[key])
        valid(config.validate(doc, "pr", base=config.effective(rt.config()["config"], repo)))
        rt.put_pr_override(repo, n, doc or None)
        return pr_page(rt, repo, n)


def put_pr_config(rt, query, body, owner, name, n):
    """api.md §3.15: the whole override."""
    return write_pr_config(rt, body, owner, name, n, "override", lambda current, doc: doc)


def patch_pr_config(rt, query, body, owner, name, n):
    """api.md §3.15: an RFC 7396 merge patch over the override."""
    return write_pr_config(rt, body, owner, name, n, "patch", config.merge_patch)


def drop_pr_config(rt, query, body, owner, name, n):
    repo, n = f"{owner}/{name}", int(n)
    with WRITE:
        pr_page(rt, repo, n)
        rt.put_pr_override(repo, n, None)
        return pr_page(rt, repo, n)


def history(rt, query):
    limit = query.get("limit", ["20"])[-1]
    if not (limit.isdigit() and 1 <= int(limit) <= 100):
        raise bad("limit must be an integer from 1 to 100")
    return rt.history(query.get("repo", [None])[-1], int(limit))


def pr_ref(item):
    return isinstance(item, dict) and isinstance(item.get("repo"), str) and type(item.get("number")) is int


def bump(rt, query, body):
    if not isinstance(body, dict) or not isinstance(prs := body.get("prs"), list) \
            or not 1 <= len(prs) <= MAX_BUMPS or not all(map(pr_ref, prs)):
        raise bad(f"prs must be a list of 1-{MAX_BUMPS} {{repo, number}} objects")
    if not isinstance(only := body.get("only_queued", True), bool):
        raise bad("only_queued must be true or false")
    return rt.bump([(p["repo"], p["number"]) for p in prs], only)


def refresh(rt, query, body):
    rt.refetch()
    return 202, {"accepted": True}


def hold(on):
    def at(rt, query, body, owner, name, n):
        repo, n = f"{owner}/{name}", int(n)
        return {"key": f"{repo}#{n}", "paused": rt.pause_pr(repo, n, on)}
    return at


def act(lane):
    def on(rt, query, body, owner, name, n):
        repo, n = f"{owner}/{name}", int(n)
        getattr(rt, lane)(repo, n)
        return 202, {"key": f"{repo}#{n}", "accepted": True}
    return on


PR = r"/v1/prs/(?P<owner>[^/]+)/(?P<name>[^/]+)/(?P<n>\d+)"
ROUTES = {
    "/v1/info": {"GET": lambda rt, query, body: rt.info()},
    "/v1/queue": {"GET": lambda rt, query, body: queue(rt, query)},
    "/v1/events": {"GET": lambda rt, query, body: events(rt, query)},
    "/v1/history": {"GET": lambda rt, query, body: history(rt, query)},
    "/v1/config": {"GET": lambda rt, query, body: rt.config(), "PUT": put_config, "PATCH": patch_config},
    "/v1/prompts/(?P<name>[^/]+)": {"GET": lambda rt, query, body, name: prompt(rt, query, name)},
    "/v1/refresh": {"POST": refresh},
    "/v1/next": {"POST": bump},
    f"{PR}/review": {"POST": act("review")},
    f"{PR}/fix": {"POST": act("fix")},
    f"{PR}/config": {"GET": pr_config, "PUT": put_pr_config, "PATCH": patch_pr_config, "DELETE": drop_pr_config},
    f"{PR}/pause": {"POST": hold(True)},
    f"{PR}/resume": {"POST": hold(False)},
    "/v1/pause": {"POST": lambda rt, query, body: {"paused": rt.pause(True)}},
    "/v1/resume": {"POST": lambda rt, query, body: {"paused": rt.pause(False)}},
}


def route(method, path):
    for pattern, methods in ROUTES.items():
        if m := re.fullmatch(pattern, path):
            if method not in methods:
                raise Problem(405, "method_not_allowed", f"{method} {path}: use {', '.join(methods)}",
                              {"Allow": ", ".join(methods)})
            return methods[method], m.groupdict()
    raise Problem(404, "not_found", f"no route {path}")


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def body(self):
        size = self.headers.get("Content-Length", "0")
        if not size.isdigit():
            raise bad("Content-Length must be a number")
        if int(size) > MAX_BODY:
            raise Problem(413, "payload_too_large", f"the body is over {MAX_BODY} bytes")
        data = self.rfile.read(int(size))
        try:
            return json.loads(data) if data else None
        except ValueError as e:
            raise bad(f"malformed JSON: {e}")

    def dispatch(self):
        url, headers = urlsplit(self.path), {}
        try:
            handler, args = route(self.command, url.path)
            out = handler(self.server.runtime, parse_qs(url.query), self.body(), **args)
            status, body = out if isinstance(out, tuple) else (200, out)
        except Problem as p:
            status, body, headers = p.status, p.body, p.headers
        except Exception:
            log(f"{self.command} {self.path} crashed: {traceback.format_exc().strip()}".replace("\n", " ⏎ "))
            status, body = 500, error("internal", "unexpected error, the daemon log has the traceback")
        finally:
            db.close()
        self.reply(status, body, headers)

    do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = dispatch

    def reply(self, status, body, headers=None):
        data = json.dumps(body).encode()
        self.send_response(status)
        for name, value in {**(headers or {}), "Content-Type": "application/json; charset=utf-8",
                            "Content-Length": str(len(data)), "Connection": "close"}.items():
            self.send_header(name, value)
        try:
            self.end_headers()
            self.wfile.write(data)
        except BrokenPipeError:
            pass
        self.close_connection = True

    def send_error(self, code, message=None, explain=None):
        self.reply(code, error("bad_request", message or self.responses.get(code, ("error",))[0]))

    def log_message(self, format, *args):
        pass


class Server(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True

    def __init__(self, path, runtime):
        self.runtime = runtime
        super().__init__(path, Handler)


def clear(path):
    """Unlinks a socket file that nobody answers on. A live server there keeps it."""
    if not os.path.lexists(path):
        return
    with socket.socket(socket.AF_UNIX) as probe:
        try:
            probe.connect(path)
        except ConnectionRefusedError:
            return os.unlink(path)
    raise SystemExit(f"{path}: another server answers there")


def bind(runtime, path):
    """The server on `path`, a 0600 socket. Run `serve_forever` to serve it."""
    clear(path)
    server = Server(path, runtime)
    os.chmod(path, 0o600)
    return server


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--fake", action="store_true", required=True, help="serve the fixtures, not the daemon state")
    ap.add_argument("--socket", default=names.SOCKET, help=f"the socket path (default {names.SOCKET})")
    ap.add_argument("--fake-speed", type=float, help="seconds one review or fix takes, 0 is instant "
                    "(default $PRL_FAKE_SPEED, else 3)")
    ap.add_argument("--fake-empty", action="store_true", default=None, help="start with an empty queue "
                    "(default: $PRL_FAKE_EMPTY=1)")
    a = ap.parse_args()
    from pr_loop import fake
    server = bind(fake.Runtime(speed=a.fake_speed, empty=a.fake_empty), a.socket)
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))
    log(f"fake daemon on {a.socket}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        os.unlink(a.socket)


if __name__ == "__main__":
    main()

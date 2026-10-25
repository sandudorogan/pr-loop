"""The control API of api.md: HTTP/1.1 + JSON on a Unix socket, one request per connection.

A runtime serves the bodies: `info()`, `snapshot()`, `config()`, `events(since)`, and `changes`, which every change moves.

Usage:
  python3 -m pr_wizard.api --fake [--socket PATH]   serve the fixtures of tests/fixtures/api/v1
"""
import argparse, json, os, re, signal, socket, socketserver, sys, threading, time, traceback
from datetime import datetime
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlsplit

from pr_wizard import config, db, names

MAX_WAIT = 60
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
    def __init__(self, status, code, message, headers=()):
        super().__init__(message)
        self.status, self.body, self.headers = status, error(code, message), dict(headers)


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


ROUTES = {
    "/v1/info": {"GET": lambda rt, query: rt.info()},
    "/v1/queue": {"GET": queue},
    "/v1/events": {"GET": events},
    "/v1/config": {"GET": lambda rt, query: rt.config()},
    "/v1/prompts/(?P<name>[^/]+)": {"GET": prompt},
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

    def dispatch(self):
        url, headers = urlsplit(self.path), {}
        try:
            handler, args = route(self.command, url.path)
            status, body = 200, handler(self.server.runtime, parse_qs(url.query), **args)
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
    a = ap.parse_args()
    from pr_wizard import fake
    server = bind(fake.Runtime(), a.socket)
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

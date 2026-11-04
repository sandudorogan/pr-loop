"""state.db: the PR Loop state in SQLite (plan.md §2). Accessors take and return today's dict shapes."""

import json
import os
import secrets
import sqlite3
import threading
import time
from contextlib import contextmanager
from datetime import datetime

from pr_loop import names

DB = names.DB
BUSY_MS = 10_000
EVENTS_KEEP, HISTORY_KEEP, DAYS = 1000, 500, 30

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS reviews (repo TEXT, number INT, sha TEXT, status TEXT, verdict TEXT, note TEXT,
  rounds INT, hold INT, at TEXT, files TEXT, PRIMARY KEY (repo, number));
CREATE TABLE IF NOT EXISTS reviewer_results (repo TEXT, number INT, sha TEXT, reviewer TEXT, result TEXT,
  engine TEXT, round INT, digest TEXT, conventions TEXT, url TEXT, at TEXT, PRIMARY KEY (repo, number, sha, reviewer));
CREATE TABLE IF NOT EXISTS fixes (repo TEXT, number INT, sha TEXT, key TEXT, status TEXT, note TEXT, errors INT,
  gate TEXT, at TEXT, PRIMARY KEY (repo, number));
CREATE TABLE IF NOT EXISTS fix_state (repo TEXT, number INT, session TEXT, handled_reviews TEXT, handled_jobs TEXT,
  deferred TEXT, ci_tries TEXT, reruns TEXT, red TEXT, at TEXT, PRIMARY KEY (repo, number));
CREATE TABLE IF NOT EXISTS clean_reviews (repo TEXT, number INT, sha TEXT, reviewer TEXT, at TEXT,
  PRIMARY KEY (repo, number, sha, reviewer));
CREATE TABLE IF NOT EXISTS next (pos INTEGER PRIMARY KEY, repo TEXT, number INT, UNIQUE (repo, number));
CREATE TABLE IF NOT EXISTS runs (repo TEXT, number INT, pid INT, lane TEXT, since TEXT, reviewers TEXT,
  PRIMARY KEY (repo, number));
CREATE INDEX IF NOT EXISTS runs_pid ON runs (pid);
CREATE TABLE IF NOT EXISTS events (seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT UNIQUE, type TEXT, repo TEXT,
  number INT, title TEXT, url TEXT, author TEXT, head TEXT, verdict TEXT, at TEXT);
CREATE TABLE IF NOT EXISTS history (repo TEXT, number INT, title TEXT, url TEXT, author TEXT, mine INT, outcome TEXT,
  rounds INT, fixes_pushed INT, head TEXT, first_at TEXT, at TEXT, closed_at TEXT, state TEXT,
  PRIMARY KEY (repo, number));
CREATE INDEX IF NOT EXISTS history_at ON history (at);
CREATE TABLE IF NOT EXISTS pr_overrides (repo TEXT, number INT, config TEXT, created_at TEXT, updated_at TEXT,
  PRIMARY KEY (repo, number));
CREATE TABLE IF NOT EXISTS paused_prs (repo TEXT, number INT, at TEXT, PRIMARY KEY (repo, number));
CREATE TABLE IF NOT EXISTS migration_log (seq INTEGER PRIMARY KEY, old_path TEXT, new_path TEXT, kind TEXT, at TEXT);
"""
# Every statement is IF NOT EXISTS, so a version that only adds tables re-runs the schema. v2: paused_prs.
UPGRADES = [lambda c: [c.execute(s) for s in SCHEMA.split(";\n") if s.strip()]] * 2

_local = threading.local()
COMMITS = []


def now():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _dump(value):
    return None if value is None else json.dumps(value)


def _load(text):
    return None if text is None else json.loads(text)


def _alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        pass
    return True


def close():
    """Drops this thread's connections."""
    for conn in getattr(_local, "conns", {}).values():
        conn.close()
    _local.conns, _local.depth = {}, 0


def _enable_wal(conn):
    """The first switch to WAL needs an exclusive lock and fails at once, with no busy_timeout wait, when
    another process holds the fresh file. Retry until the budget ends."""
    deadline = time.monotonic() + BUSY_MS / 1000
    while True:
        try:
            return conn.execute("PRAGMA journal_mode = WAL")
        except sqlite3.OperationalError as e:
            if "locked" not in str(e) or time.monotonic() > deadline:
                raise
            time.sleep(0.01)


def connect(path=None):
    """The thread's connection: WAL, busy_timeout, synchronous NORMAL, schema created or upgraded."""
    path = path or DB
    conns = _local.__dict__.setdefault("conns", {})
    key = (os.getpid(), path)
    if key not in conns:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        conn = sqlite3.connect(path, isolation_level=None, timeout=BUSY_MS / 1000)
        conn.row_factory = sqlite3.Row
        conn.execute(f"PRAGMA busy_timeout = {BUSY_MS}")
        if conn.execute("PRAGMA journal_mode").fetchone()[0] != "wal":
            _enable_wal(conn)
        conn.execute("PRAGMA synchronous = NORMAL")
        upgrade(conn)
        conns[key] = conn
    return conns[key]


def upgrade(conn):
    if conn.execute("PRAGMA user_version").fetchone()[0] >= len(UPGRADES):
        return
    conn.execute("BEGIN IMMEDIATE")
    try:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        for step in UPGRADES[version:]:
            step(conn)
        conn.execute("INSERT OR IGNORE INTO meta VALUES ('events_epoch', ?)", (secrets.token_hex(3),))
        conn.execute(f"PRAGMA user_version = {len(UPGRADES)}")
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise


@contextmanager
def tx(path=None):
    """BEGIN IMMEDIATE … COMMIT. A nested call joins the open transaction of its thread."""
    conn = connect(path)
    if getattr(_local, "depth", 0):
        yield conn
        return
    conn.execute("BEGIN IMMEDIATE")
    _local.depth = 1
    try:
        yield conn
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    finally:
        _local.depth = 0
    for committed in COMMITS:
        committed()


def _one(sql, *args):
    return connect().execute(sql, args).fetchone()


def _all(sql, *args):
    return connect().execute(sql, args).fetchall()


def data_version():
    return _one("PRAGMA data_version")[0]


def meta_get(key, default=None):
    row = _one("SELECT value FROM meta WHERE key = ?", key)
    return default if row is None else row["value"]


def meta_set(key, value):
    with tx() as c:
        c.execute("INSERT OR REPLACE INTO meta VALUES (?, ?)", (key, str(value)))


def _put(c, table, repo, n, **cols):
    names = ", ".join(("repo", "number", *cols))
    c.execute(f"INSERT OR REPLACE INTO {table} ({names}) VALUES ({', '.join('?' * (2 + len(cols)))})",
              (repo, int(n), *cols.values()))


def _review(row):
    return {k: row[k] for k in ("sha", "status", "verdict", "note", "rounds", "at")} | {
        "hold": bool(row["hold"]), "files": _load(row["files"]) or {}}


def review(repo, n):
    """{sha, status, verdict, note, rounds, hold, at, files}, or {} for a PR with no result."""
    row = _one("SELECT * FROM reviews WHERE repo = ? AND number = ?", repo, int(n))
    return {} if row is None else _review(row)


def reviews(repo):
    """{number: review} of every PR of the repo."""
    return {r["number"]: _review(r) for r in _all("SELECT * FROM reviews WHERE repo = ? ORDER BY rowid", repo)}


def put_review(repo, n, entry):
    e = {"verdict": None, "note": None, "rounds": 0, "hold": False, "at": now(), "files": {}} | entry
    with tx() as c:
        _put(c, "reviews", repo, n, sha=e["sha"], status=e["status"], verdict=e["verdict"], note=e["note"],
             rounds=e["rounds"], hold=int(e["hold"]), at=e["at"], files=_dump(e["files"]))


def reviewer_results(repo, n):
    """{reviewer: {sha, result, engine, round, digest, conventions, url, at}} at the latest reviewed head."""
    return {r["reviewer"]: {k: r[k] for k in ("sha", "result", "engine", "round", "url", "at")}
            | {"digest": _load(r["digest"]), "conventions": _load(r["conventions"])}
            for r in _all("SELECT * FROM reviewer_results WHERE repo = ? AND number = ?", repo, int(n))}


def put_reviewer_result(repo, n, sha, reviewer, entry):
    """Upserts one reviewer's result. The first result for a new head deletes the older heads' results."""
    e = {"engine": None, "round": None, "digest": None, "conventions": None, "url": None, "at": now()} | entry
    with tx() as c:
        c.execute("DELETE FROM reviewer_results WHERE repo = ? AND number = ? AND sha != ?", (repo, int(n), sha))
        _put(c, "reviewer_results", repo, n, sha=sha, reviewer=reviewer, result=e["result"], engine=e["engine"],
             round=e["round"], digest=_dump(e["digest"]), conventions=_dump(e["conventions"]), url=e["url"], at=e["at"])


def _fix(row):
    gate = _load(row["gate"])
    return {k: row[k] for k in ("sha", "key", "status", "note", "errors", "at")} | ({} if gate is None else {"gate": gate})


def fix(repo, n):
    """{sha, key, status, note, errors, at, gate?}, or {} for a PR with no fix pass."""
    row = _one("SELECT * FROM fixes WHERE repo = ? AND number = ?", repo, int(n))
    return {} if row is None else _fix(row)


def fixes(repo):
    """{number: fix} of every PR of the repo."""
    return {r["number"]: _fix(r) for r in _all("SELECT * FROM fixes WHERE repo = ? ORDER BY rowid", repo)}


def put_fix(repo, n, entry):
    e = {"key": None, "note": None, "errors": 0, "gate": None, "at": now()} | entry
    with tx() as c:
        _put(c, "fixes", repo, n, sha=e["sha"], key=e["key"], status=e["status"], note=e["note"],
             errors=e["errors"], gate=_dump(e["gate"]), at=e["at"])


def rearm_fix(repo, n):
    """Clears the key and the error count, so the next refresh queues a fix pass."""
    with tx() as c:
        c.execute("UPDATE fixes SET key = NULL, errors = 0 WHERE repo = ? AND number = ?", (repo, int(n)))


FIX_STATE_JSON = ("handled_reviews", "handled_jobs", "deferred", "ci_tries", "reruns", "red")


def _fix_state(row):
    state = {"session": row["session"]} | {k: _load(row[k]) for k in FIX_STATE_JSON}
    return {k: v for k, v in state.items() if v is not None}


def fix_state(repo, n):
    """The pr-fix/<N>.json dict: only the keys that were saved."""
    row = _one("SELECT * FROM fix_state WHERE repo = ? AND number = ?", repo, int(n))
    return {} if row is None else _fix_state(row)


def fix_states(repo):
    """{number: fix_state} of every PR of the repo."""
    return {r["number"]: _fix_state(r) for r in _all("SELECT * FROM fix_state WHERE repo = ? ORDER BY rowid", repo)}


def put_fix_state(repo, n, state):
    with tx() as c:
        _put(c, "fix_state", repo, n, session=state.get("session"), at=now(),
             **{k: _dump(state.get(k)) for k in FIX_STATE_JSON})


def clean(repo, n, sha):
    """The reviewers that cleared this head, in the order they did."""
    return [r["reviewer"] for r in _all(
        "SELECT reviewer FROM clean_reviews WHERE repo = ? AND number = ? AND sha = ? ORDER BY rowid",
        repo, int(n), sha)]


def cleared():
    """{(repo, number, sha): [reviewer]} of every cleared head, in the order they were cleared."""
    heads = {}
    for r in _all("SELECT * FROM clean_reviews ORDER BY rowid"):
        heads.setdefault((r["repo"], r["number"], r["sha"]), []).append(r["reviewer"])
    return heads


def add_clean(repo, n, sha, reviewer):
    with tx() as c:
        c.execute("INSERT OR IGNORE INTO clean_reviews VALUES (?, ?, ?, ?, ?)", (repo, int(n), sha, reviewer, now()))
        c.execute("DELETE FROM clean_reviews WHERE julianday(at) < julianday('now', ?)", (f"-{DAYS} days",))


def next_list(repo):
    """The bumped PR numbers of one repo, first in line first."""
    return [r["number"] for r in _all("SELECT number FROM next WHERE repo = ? ORDER BY pos", repo)]


def bump(repo, *numbers):
    """Puts the PRs at the front of the line in the given order. A PR already in line moves."""
    with tx() as c:
        for n in numbers:
            c.execute("DELETE FROM next WHERE repo = ? AND number = ?", (repo, int(n)))
        for n in reversed(numbers):
            c.execute("INSERT INTO next (pos, repo, number) VALUES ((SELECT coalesce(min(pos), 1) - 1 FROM next), ?, ?)",
                      (repo, int(n)))


def next_keys():
    """Every bumped PR as "repo#number", first in line first."""
    return [f"{r['repo']}#{r['number']}" for r in _all("SELECT repo, number FROM next ORDER BY pos")]


def drop_next(repo, n):
    with tx() as c:
        c.execute("DELETE FROM next WHERE repo = ? AND number = ?", (repo, int(n)))


def run_start(repo, n, lane, pid=None, since=None, reviewers=None):
    with tx() as c:
        _put(c, "runs", repo, n, pid=pid or os.getpid(), lane=lane, since=since or now(), reviewers=_dump(reviewers))


def run_update(repo, n, reviewers):
    with tx() as c:
        c.execute("UPDATE runs SET reviewers = ? WHERE repo = ? AND number = ?", (_dump(reviewers), repo, int(n)))


def run_end(repo, n):
    with tx() as c:
        c.execute("DELETE FROM runs WHERE repo = ? AND number = ?", (repo, int(n)))


def live_runs(repo=None):
    """{number: {lane, since, reviewers, pid}} of the runs whose process lives. All repos give {(repo, number): …}."""
    rows = [r for r in _all("SELECT * FROM runs WHERE ? IS NULL OR repo = ?", repo, repo) if _alive(r["pid"])]
    return {(r["number"] if repo else (r["repo"], r["number"])):
            {"lane": r["lane"], "since": r["since"], "reviewers": _load(r["reviewers"]), "pid": r["pid"]}
            for r in rows}


def sweep_runs():
    """Deletes the rows of dead pids (the daemon does it at start)."""
    with tx() as c:
        for r in c.execute("SELECT DISTINCT pid FROM runs").fetchall():
            if not _alive(r["pid"]):
                c.execute("DELETE FROM runs WHERE pid = ?", (r["pid"],))


EVENT_FIELDS = ("type", "repo", "number", "title", "url", "author", "head", "verdict", "at")


def _event(row):
    return {"id": row["id"], "seq": row["seq"], "type": row["type"], "key": f"{row['repo']}#{row['number']}",
            **{k: row[k] for k in EVENT_FIELDS[1:]}}


def add_event(type, repo, n, title, url, author, head, verdict=None, at=None):
    """Appends an event and keeps the last EVENTS_KEEP. The id is stable per type, PR and head, so the same
    head made ready twice is the same notification: the older row is replaced and the event moves to the end."""
    id = f"{type}:{repo}#{int(n)}@{head[:12]}"
    with tx() as c:
        c.execute("INSERT OR REPLACE INTO events (id, type, repo, number, title, url, author, head, verdict, at) "
                  "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                  (id, type, repo, int(n), title, url, author, head, verdict, at or now()))
        c.execute("DELETE FROM events WHERE seq NOT IN (SELECT seq FROM events ORDER BY seq DESC LIMIT ?)",
                  (EVENTS_KEEP,))
    return _event(_one("SELECT * FROM events WHERE id = ?", id))


def events_after(cursor=None):
    """{cursor, reset, events} for a "<epoch>.<seq>" cursor (api.md §3.3). No cursor: subscribe from now.
    A cursor of another store or older than the oldest kept event gets every kept event with reset true."""
    epoch = meta_get("events_epoch")
    head = (_one("SELECT seq FROM sqlite_sequence WHERE name = 'events'") or [0])[0]
    oldest = (_one("SELECT min(seq) FROM events")[0] or head + 1)
    now_cursor = f"{epoch}.{head}"
    if cursor is None:
        return {"cursor": now_cursor, "reset": False, "events": []}
    seen_epoch, _, seq = cursor.partition(".")
    seq = int(seq) if seq.isdigit() else -1
    reset = seen_epoch != epoch or not 0 <= seq <= head or seq < oldest - 1
    rows = _all("SELECT * FROM events WHERE seq > ? ORDER BY seq", -1 if reset else seq)
    return {"cursor": now_cursor, "reset": reset, "events": [_event(r) for r in rows]}


HISTORY_FIELDS = ("title", "url", "author", "mine", "outcome", "rounds", "fixes_pushed", "head", "first_at", "at",
                  "closed_at", "state")


def _history(row):
    return {"key": f"{row['repo']}#{row['number']}", "repo": row["repo"], "number": row["number"],
            **{k: row[k] for k in HISTORY_FIELDS}, "mine": bool(row["mine"])}


def upsert_history(repo, n, pushed=0, **fields):
    """Merges the given fields into the PR's row; `first_at` and `at` default to now, `state` to open.
    `pushed` adds to `fixes_pushed`. Trims to HISTORY_KEEP rows and DAYS days."""
    with tx() as c:
        row = c.execute("SELECT * FROM history WHERE repo = ? AND number = ?", (repo, int(n))).fetchone()
        stamp = fields.get("at") or now()
        e = {"mine": False, "rounds": 0, "fixes_pushed": 0, "state": "open", "first_at": stamp, "at": stamp,
             "closed_at": None} | ({} if row is None else {k: row[k] for k in HISTORY_FIELDS}) | fields
        e["fixes_pushed"] += pushed
        _put(c, "history", repo, n, **{k: e.get(k) for k in HISTORY_FIELDS} | {"mine": int(e["mine"])})
        c.execute("DELETE FROM history WHERE julianday(at) < julianday('now', ?)", (f"-{DAYS} days",))
        c.execute("DELETE FROM history WHERE rowid NOT IN (SELECT rowid FROM history ORDER BY at DESC, rowid DESC LIMIT ?)",
                  (HISTORY_KEEP,))


def history(limit=20, repo=None):
    """The newest entries first, optionally of one repo."""
    return [_history(r) for r in _all(
        "SELECT * FROM history WHERE ? IS NULL OR repo = ? ORDER BY at DESC, rowid DESC LIMIT ?", repo, repo, limit)]


def result_repos():
    """The repos that have a stored review or fix row."""
    return [r[0] for r in _all("SELECT repo FROM reviews UNION SELECT repo FROM fixes ORDER BY repo")]


def pr_override(repo, n):
    """{config, created_at, updated_at}, or None."""
    row = _one("SELECT * FROM pr_overrides WHERE repo = ? AND number = ?", repo, int(n))
    return None if row is None else {"config": _load(row["config"]), "created_at": row["created_at"],
                                     "updated_at": row["updated_at"]}


def pr_overrides():
    """{(repo, number): config} of every stored PR override."""
    return {(r["repo"], r["number"]): _load(r["config"]) for r in _all("SELECT * FROM pr_overrides ORDER BY repo, number")}


def put_pr_override(repo, n, config):
    with tx() as c:
        row = c.execute("SELECT created_at FROM pr_overrides WHERE repo = ? AND number = ?", (repo, int(n))).fetchone()
        stamp = now()
        _put(c, "pr_overrides", repo, n, config=_dump(config), created_at=row["created_at"] if row else stamp,
             updated_at=stamp)


def drop_pr_override(repo, n):
    with tx() as c:
        c.execute("DELETE FROM pr_overrides WHERE repo = ? AND number = ?", (repo, int(n)))


def paused_prs():
    """{(repo, number): at} of every paused PR."""
    return {(r["repo"], r["number"]): r["at"] for r in _all("SELECT * FROM paused_prs")}


def pause_pr(repo, n, on):
    with tx() as c:
        if on:
            c.execute("INSERT OR IGNORE INTO paused_prs VALUES (?, ?, ?)", (repo, int(n), now()))
        else:
            c.execute("DELETE FROM paused_prs WHERE repo = ? AND number = ?", (repo, int(n)))


def log_moves(moves, at=None):
    """Records [(old_path, new_path, kind)] of a migration. new_path is None for a deleted file."""
    with tx() as c:
        c.executemany("INSERT INTO migration_log (old_path, new_path, kind, at) VALUES (?, ?, ?, ?)",
                      [(*m, at or now()) for m in moves])

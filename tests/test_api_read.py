import json
import os
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from prs import MONOREPO, ROOT, rq
from test_snapshot import mismatches, spec
import test_snapshot
from pr_wizard import api, config, db, fake, names

FIXTURES = Path(__file__).parent / "fixtures/api/v1"


def fixture(name):
    return json.loads((FIXTURES / f"{name}.json").read_text())


def call(path, sock, method="GET"):
    with socket.socket(socket.AF_UNIX) as s:
        s.connect(sock)
        s.sendall(f"{method} {path} HTTP/1.1\r\nHost: pr-wizard\r\nContent-Length: 0\r\n\r\n".encode())
        data = b"".join(iter(lambda: s.recv(65536), b""))
    head, body = data.split(b"\r\n\r\n", 1)
    lines = head.decode().split("\r\n")
    headers = {k.lower(): v.strip() for k, v in (line.split(":", 1) for line in lines[1:])}
    assert int(headers["content-length"]) == len(body) and "transfer-encoding" not in headers
    return int(lines[0].split()[1]), headers, json.loads(body)


def shape(value, like, skip=()):
    return mismatches({k: v for k, v in value.items() if k not in skip},
                      spec([{k: v for k, v in like.items() if k not in skip}]))


class Server(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(dir="/tmp")
        self.addCleanup(subprocess.run, ["rm", "-rf", self.dir])
        test_snapshot.Snapshot.setUp(self)
        self.sock = f"{self.dir}/api.sock"
        self.rt = rq.Runtime()
        self.rt.refreshed(self.prs)
        self.server = api.bind(self.rt, self.sock)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        db.COMMITS.append(self.rt.changes.touch)
        self.addCleanup(db.COMMITS.remove, self.rt.changes.touch)

    def get(self, path, method="GET"):
        return call(path, self.sock, method)

    def timed(self, path):
        started = time.monotonic()
        return self.get(path)[2], time.monotonic() - started

    def later(self, seconds, action):
        timer = threading.Timer(seconds, action)
        timer.start()
        self.addCleanup(timer.cancel)

    def test_socket_is_owner_only(self):
        self.assertEqual(os.stat(self.sock).st_mode & 0o777, 0o600)

    def test_info_has_the_fixture_shape(self):
        status, headers, info = self.get("/v1/info")
        self.assertEqual((status, headers["content-type"], headers["connection"]),
                         (200, "application/json; charset=utf-8", "close"))
        self.assertEqual(shape(info, fixture("info")), [])
        self.assertEqual((info["label"], info["paths"]["socket"], info["pid"]), (names.LABEL, names.SOCKET, os.getpid()))
        self.assertEqual(info["refresh"], {"interval_s": 300, "idle_s": 60,
                                           **self.rt.refresh})

    def test_queue_serves_the_snapshot(self):
        snap = self.get("/v1/queue")[2]
        self.assertEqual({**snap, "generated_at": None}, {**self.rt.snapshot(), "generated_at": None})
        self.assertEqual(shape(snap, fixture("queue"), ("items", "projects")), [])
        self.assertEqual(snap["fetched_at"], self.rt.fetched_at)

    def test_config_has_the_fixture_defaults_and_effective(self):
        body, like = self.get("/v1/config")[2], fixture("config")
        self.assertEqual(shape(body, like, ("config", "defaults", "effective", "choices")), [])
        self.assertEqual((body["defaults"], body["config"], body["source"]), (like["defaults"], like["defaults"], "defaults"))
        self.assertEqual(body["rev"], like["rev"])
        for repo in (MONOREPO, "iprally/gitops"):
            self.assertEqual({**body["effective"][repo], "root": None}, {**like["effective"][repo], "root": None})
            self.assertEqual(body["effective"][repo]["root"], names.root(repo))
        self.assertEqual(body["choices"].keys(), like["choices"].keys())

    def test_prompt_lists_its_placeholders_in_order(self):
        like = fixture("prompt")
        self.assertEqual(list(dict.fromkeys(api.PLACEHOLDER.findall(like["text"]))), like["placeholders"])
        status, _, body = self.get("/v1/prompts/merge.md")
        self.assertEqual((status, body.keys()), (200, like.keys()))
        self.assertEqual(body["text"], Path(body["path"]).read_text())
        self.assertEqual(body["placeholders"], list(dict.fromkeys(api.PLACEHOLDER.findall(body["text"]))))
        self.assertEqual(self.get("/v1/prompts/nope.md")[::2], (404, api.error("not_found", "no prompt nope.md")))

    def test_error_bodies(self):
        self.assertEqual(api.error("busy", "a live run already holds iprally/iprally#17190"), fixture("error-busy"))
        bad = fixture("error-invalid-config")["error"]
        self.assertEqual(api.error("invalid_config", bad["message"], bad["details"]), fixture("error-invalid-config"))
        self.assertEqual(self.get("/v1/nope")[::2], (404, api.error("not_found", "no route /v1/nope")))
        status, headers, body = self.get("/v1/queue", "POST")
        self.assertEqual((status, headers["allow"], body["error"]["code"]), (405, "GET", "method_not_allowed"))
        self.assertEqual(self.get("/v1/queue?wait=61")[::2],
                         (400, api.error("bad_request", "wait must be an integer from 0 to 60")))
        with patch.object(self.rt, "info", side_effect=RuntimeError("boom")), patch.object(api, "log"):
            self.assertEqual(self.get("/v1/info")[2]["error"]["code"], "internal")

    def test_long_poll_wakes_on_the_daemons_own_write(self):
        rev = self.get("/v1/queue")[2]["rev"]
        self.later(0.2, lambda: db.drop_next(MONOREPO, 12))
        snap, took = self.timed(f"/v1/queue?since={rev}&wait=10")
        self.assertNotEqual(snap["rev"], rev)
        self.assertLess(took, 1)

    def test_long_poll_wakes_on_another_process_commit(self):
        stopped = threading.Event()
        self.addCleanup(stopped.set)
        threading.Thread(target=api.watch, args=(self.rt.changes, stopped, 0.05), daemon=True).start()
        rev = self.get("/v1/queue")[2]["rev"]
        script = "import sqlite3, sys; c = sqlite3.connect(sys.argv[1]); c.execute(\"DELETE FROM next\"); c.commit()"
        self.later(0.2, lambda: subprocess.run([sys.executable, "-c", script, db.DB], check=True))
        snap, took = self.timed(f"/v1/queue?since={rev}&wait=10")
        self.assertNotEqual(snap["rev"], rev)
        self.assertLess(took, 5)

    def test_long_poll_answers_the_same_rev_on_timeout(self):
        rev = self.get("/v1/queue")[2]["rev"]
        snap, took = self.timed(f"/v1/queue?since={rev}&wait=1")
        self.assertEqual(snap["rev"], rev)
        self.assertGreaterEqual(took, 1)
        self.assertLess(self.timed("/v1/queue?since=other&wait=10")[1], 1)

    def test_a_client_that_hangs_up_mid_poll_is_no_error(self):
        rev = self.get("/v1/queue")[2]["rev"]
        with patch.object(self.server, "handle_error") as handle_error:
            with socket.socket(socket.AF_UNIX) as s:
                s.connect(self.sock)
                s.sendall(f"GET /v1/queue?since={rev}&wait=10 HTTP/1.1\r\nContent-Length: 0\r\n\r\n".encode())
                time.sleep(0.2)
            db.drop_next(MONOREPO, 12)
            time.sleep(0.3)
        handle_error.assert_not_called()

    def test_a_live_server_keeps_its_socket(self):
        with self.assertRaises(SystemExit):
            api.bind(self.rt, self.sock)
        self.assertEqual(self.get("/v1/info")[0], 200)


class Lifecycle(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(dir="/tmp")
        self.addCleanup(subprocess.run, ["rm", "-rf", self.dir])

    def test_a_stale_socket_is_replaced(self):
        path = f"{self.dir}/api.sock"
        stale = socket.socket(socket.AF_UNIX)
        stale.bind(path)
        stale.close()
        server = api.bind(fake.Runtime(), path)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        self.assertEqual(call("/v1/queue", path)[2], fixture("queue"))

    def test_the_daemon_serves_writes_the_label_and_unlinks_on_sigterm(self):
        state = f"{self.dir}/pr-wizard"
        os.makedirs(state, mode=0o755)
        child = subprocess.Popen([sys.executable, "-c", f"""
import signal, sys
sys.path.insert(0, {str(ROOT)!r})
from pr_wizard import db, fake, names, queue
names.WIZARD, names.SOCKET, names.LABEL_FILE = {state!r}, {state + '/api.sock'!r}, {state + '/launchd-label'!r}
db.DB = {state + '/state.db'!r}
queue.serve(fake.Runtime())
signal.pause()
"""], stdout=subprocess.PIPE, text=True)
        self.addCleanup(lambda: child.poll() is None and child.kill())
        self.assertIn("api on", child.stdout.readline())
        self.assertEqual(os.stat(state).st_mode & 0o777, 0o700)
        self.assertEqual(Path(f"{state}/launchd-label").read_text(), "local.review-queue\n")
        self.assertEqual(call("/v1/info", f"{state}/api.sock")[2], fixture("info"))
        child.send_signal(signal.SIGTERM)
        self.assertEqual(child.wait(10), 143)
        self.assertFalse(os.path.exists(f"{state}/api.sock"))
        child.stdout.close()

    def test_sigterm_exits_even_when_the_socket_is_already_gone(self):
        state = f"{self.dir}/pr-wizard"
        os.makedirs(state, mode=0o755)
        child = subprocess.Popen([sys.executable, "-c", f"""
import signal, sys
sys.path.insert(0, {str(ROOT)!r})
from pr_wizard import db, fake, names, queue
names.WIZARD, names.SOCKET, names.LABEL_FILE = {state!r}, {state + '/api.sock'!r}, {state + '/launchd-label'!r}
db.DB = {state + '/state.db'!r}
queue.serve(fake.Runtime())
signal.pause()
"""], stdout=subprocess.PIPE, text=True)
        self.addCleanup(lambda: child.poll() is None and child.kill())
        self.assertIn("api on", child.stdout.readline())
        os.unlink(f"{state}/api.sock")
        child.send_signal(signal.SIGTERM)
        self.assertEqual(child.wait(10), 143)
        child.stdout.close()


if __name__ == "__main__":
    unittest.main()

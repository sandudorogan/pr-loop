import contextlib
import io
import json
import os
import socket
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import MagicMock, patch

from prs import GITOPS, MONOREPO, rq
from test_api_read import fixture
from pr_loop import api, cli, client, names, snapshot


class Stub:
    """A runtime that answers from the fixtures and records what the CLI asked of it."""

    def __init__(self):
        self.changes, self.asked = api.Changes(), []
        self.snap, self.results = fixture("queue"), {}

    def snapshot(self):
        return self.snap

    def refetch(self):
        self.asked.append(("refresh",))

    def bump(self, prs, only_queued):
        self.asked.append(("next", prs, only_queued))
        return {"next": [], "results": [{"key": f"{r}#{n}", "bumped": (r, n) not in self.results,
                                         "reason": self.results.get((r, n))} for r, n in prs]}

    def pause(self, on):
        self.asked.append(("pause", on))
        return on

    def config(self):
        return {"rev": "r1", "config": {"review": {"workers": 3}}}

    def save_config(self, doc):
        raise AssertionError("an invalid config is never saved")


class Cli(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(dir="/tmp")
        self.addCleanup(subprocess.run, ["rm", "-rf", self.dir])
        self.sock = f"{self.dir}/api.sock"
        for patcher in (patch.object(names, "SOCKET", self.sock), patch.object(names, "migrate"),
                        patch.object(cli, "start"), patch.object(cli.time, "sleep")):
            self.addCleanup(patcher.stop)
            patcher.start()
        self.rt = Stub()

    def serve(self):
        server = api.bind(self.rt, self.sock)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)

    def run_cli(self, *argv, env=None):
        out, err = io.StringIO(), io.StringIO()
        with patch.object(cli.sys, "argv", ["review-queue", *argv]), patch.dict(os.environ, env or {}), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                cli.main()
                code = 0
            except SystemExit as e:
                code = e.code
        return code, out.getvalue(), err.getvalue()


class Client(Cli):
    def test_a_call_returns_the_body(self):
        self.serve()
        self.assertEqual(client.call("POST", "/v1/pause"), {"paused": True})

    def test_an_error_body_raises_failed(self):
        self.serve()
        with self.assertRaises(client.Failed) as failed:
            client.call("GET", "/v1/nope")
        self.assertEqual((failed.exception.status, failed.exception.error["code"]), (404, "not_found"))

    def test_no_socket_and_a_stale_socket_are_down(self):
        with self.assertRaises(client.Down):
            client.call("GET", "/v1/queue")
        with socket.socket(socket.AF_UNIX) as stale:
            stale.bind(self.sock)
        with self.assertRaises(client.Down):
            client.call("GET", "/v1/queue")


class List(Cli):
    def test_up_renders_the_daemons_snapshot(self):
        self.serve()
        self.assertEqual(self.run_cli("-l"), (0, snapshot.render(fixture("queue")), ""))

    def test_down_says_so_and_lists_locally(self):
        with patch.object(rq, "show") as show:
            code, out, err = self.run_cli("-l")
        show.assert_called_once_with()
        self.assertEqual((code, out, err), (0, "", f"{cli.DOWN}\n"))


class Next(Cli):
    def test_a_bump_asks_for_queued_only_then_lists(self):
        self.serve()
        code, out, _ = self.run_cli("--next", "17201")
        self.assertEqual(self.rt.asked, [("next", [(MONOREPO, 17201)], True)])
        self.assertEqual((code, out), (0, snapshot.render(fixture("queue"))))

    def test_a_refused_bump_prints_todays_reason(self):
        self.serve()
        for n, reason, said in ((17190, "active", "already in review"), (17166, "nothing-new", "nothing new to review (ready)"),
                                (9, "not-in-queue", "not in the queue")):
            self.rt.results[MONOREPO, n] = reason
            self.assertEqual(self.run_cli("--next", str(n))[1].splitlines()[0], f"#{n}: {said}")

    def test_a_lane_off_reads_as_nothing_new(self):
        self.serve()
        self.rt.results[GITOPS, 412] = "review-lane-off"
        self.assertEqual(self.run_cli("--next", f"{GITOPS}#412")[1].splitlines()[0], "#412: nothing new to review (skipped)")

    def test_down_bumps_locally(self):
        with patch.object(rq, "bump") as bump:
            code, _, err = self.run_cli("--next", "5", "--repo", GITOPS)
        bump.assert_called_once_with(GITOPS, 5)
        self.assertEqual((code, err), (0, f"{cli.DOWN}\n"))


class Wait(Cli):
    def wait(self, pending, *argv):
        with patch.object(rq, "unsettled", return_value=pending) as unsettled, patch.object(rq, "settle") as settle:
            code = self.run_cli("--wait", *argv)[0]
        return code, unsettled.call_args.args, settle.call_args and settle.call_args.args

    def test_bumps_the_unsettled_prs_as_given_then_waits_locally(self):
        self.serve()
        self.assertEqual(self.wait([3, 1], "1", "2", "3", "--timeout", "5"), (0, (MONOREPO, [1, 2, 3]), (MONOREPO, [1, 2, 3], 5)))
        self.assertEqual(self.rt.asked, [("next", [(MONOREPO, 3), (MONOREPO, 1)], False)])

    def test_nothing_to_bump_refreshes(self):
        self.serve()
        self.assertEqual(self.wait([], f"{GITOPS}#7")[2][:2], (GITOPS, [7]))
        self.assertEqual(self.rt.asked, [("refresh",)])

    def test_down_starts_the_daemon_and_asks_again(self):
        call = MagicMock(side_effect=[client.Down(), client.Down(), {"next": [], "results": []}])
        with patch.object(client, "call", call):
            self.assertEqual(self.wait([4], "4")[0], 0)
        cli.start.assert_called_once_with()
        self.assertEqual(call.call_count, 3)

    def test_a_daemon_that_stays_down_exits_1(self):
        with patch.object(client, "call", MagicMock(side_effect=client.Down())) as call:
            self.assertEqual(self.wait([4], "4")[0], cli.DOWN)
        self.assertEqual(call.call_count, cli.UP_WITHIN + 1)

    def test_prs_of_two_repos_are_refused(self):
        self.assertEqual(self.run_cli("--wait", "1", f"{GITOPS}#2")[0], 2)


class Actions(Cli):
    def test_bg_refreshes_when_up_and_starts_when_down(self):
        said = f"queue refresh requested — tail -f {names.LOG}\n"
        self.assertEqual(self.run_cli("--bg")[:2], (0, said))
        cli.start.assert_called_once_with()
        self.serve()
        self.assertEqual(self.run_cli("--bg")[:2], (0, said))
        self.assertEqual((self.rt.asked, cli.start.call_count), ([("refresh",)], 1))

    def test_pause_and_resume(self):
        self.serve()
        self.assertEqual([self.run_cli(flag)[1] for flag in ("--pause", "--resume")],
                         ["paused: workers take no new PR\n", "resumed\n"])

    def test_config_prints_the_config(self):
        self.serve()
        code, out, _ = self.run_cli("config")
        self.assertEqual((code, json.loads(out)), (0, {"review": {"workers": 3}}))

    def test_an_invalid_patch_exits_with_every_problem(self):
        self.serve()
        code = self.run_cli("config", "--patch", '{"review": {"workers": 99}}')[0]
        self.assertTrue(code.startswith("422 invalid_config: "), code)
        self.assertIn("\n  review.workers: ", code)

    def test_config_down_exits_1(self):
        self.assertEqual(self.run_cli("config")[0], cli.DOWN)

    def test_pr_reviews_locally_even_with_the_daemon_up(self):
        self.serve()
        with patch.object(rq, "tick") as tick:
            self.assertEqual(self.run_cli("--pr", "42", env={"PR_LOOP_REPO": GITOPS})[0], 0)
        tick.assert_called_once_with((GITOPS, 42), False)
        self.assertEqual(self.rt.asked, [])

    def test_a_bad_pr_is_a_usage_error(self):
        for text in ("x", "nobody/else#3"):
            self.assertEqual(self.run_cli("--pr", text)[0], 2)


if __name__ == "__main__":
    unittest.main()

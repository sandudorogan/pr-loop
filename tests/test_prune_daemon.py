import io
import contextlib
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import MagicMock, call, patch

from pr_wizard import cli, queue as rq


class Stop(Exception):
    pass


class PruneInDaemon(unittest.TestCase):
    def logged(self, repos, prune):
        out = io.StringIO()
        with patch.object(rq, "prune", prune), contextlib.redirect_stdout(out):
            failed = rq.prune_all(repos, False)
        return failed, out.getvalue()

    def test_pruner_is_a_daemon_thread_on_the_loop(self):
        with patch.object(rq.threading, "Thread") as thread:
            rq.start_pruner(list)
        thread.assert_called_once_with(target=rq.prune_forever, args=(list,), daemon=True)
        thread.return_value.start.assert_called_once_with()

    def test_the_daemon_starts_the_pruner(self):
        self.assertIn("start_pruner(lambda: active(rt.prs))", Path(rq.__file__).read_text().split("def daemon()")[1])

    def test_loop_prunes_every_repo_at_start_then_every_interval(self):
        sleep, prune = MagicMock(side_effect=[None, Stop]), MagicMock()
        with patch.object(rq, "prune", prune), contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(Stop):
                rq.prune_forever(lambda: list(rq.REPOS), sleep)
        self.assertEqual(rq.PRUNE_EVERY, 1800)
        self.assertEqual(sleep.call_args_list, [call(1800), call(1800)])
        self.assertEqual(prune.call_args_list, [call(r, False) for r in rq.REPOS] * 2)

    def test_every_repo_is_covered(self):
        prune = MagicMock()
        self.assertFalse(self.logged(rq.REPOS, prune)[0])
        self.assertEqual([c.args[0] for c in prune.call_args_list], list(rq.REPOS))
        self.assertEqual(list(rq.REPOS), ["iprally/iprally", "iprally/gitops"])

    def test_a_raising_prune_is_logged_and_the_next_repo_still_runs(self):
        def prune(repo, dry_run):
            if repo == rq.MONOREPO:
                raise subprocess.CalledProcessError(1, "git", stderr="boom\n")
        failed, out = self.logged(rq.REPOS, MagicMock(side_effect=prune))
        self.assertTrue(failed)
        self.assertIn("prune failed: boom", out)

    def test_an_exit_inside_prune_does_not_leave_the_loop(self):
        failed, _ = self.logged(rq.REPOS, MagicMock(side_effect=[SystemExit(1), None]))
        self.assertTrue(failed)

    def test_loop_survives_a_raising_prune(self):
        sleep = MagicMock(side_effect=[None, Stop])
        with patch.object(rq, "prune", MagicMock(side_effect=RuntimeError("x"))), \
                contextlib.redirect_stdout(io.StringIO()) as out:
            with self.assertRaises(Stop):
                rq.prune_forever(lambda: list(rq.REPOS), sleep)
        self.assertEqual(out.getvalue().count("prune failed: x"), 2 * len(rq.REPOS))

    def test_cli_prune_without_repo_loops_every_repo_and_with_repo_one(self):
        for argv, repos in ((["--prune"], list(rq.REPOS)), (["--prune", "--repo", "iprally/gitops"], ["iprally/gitops"])):
            with patch.object(rq, "prune_all", return_value=False) as prune_all, patch.object(rq, "queue", return_value=[]), \
                    patch.object(cli.sys, "argv", ["review-queue", *argv]), self.assertRaises(SystemExit) as exit:
                cli.main()
            self.assertEqual([list(prune_all.call_args.args[0]), prune_all.call_args.args[1]], [repos, False])
            prune_all.assert_called_once()
            self.assertFalse(exit.exception.code)

    def test_a_worktree_dir_deleted_by_hand_does_not_block_the_prune(self):
        with tempfile.TemporaryDirectory() as tmp:
            gone = f"{tmp}/wt"
            self.assertIsNone(rq.blocker(rq.MONOREPO, gone, "a" * 40, [], []))


if __name__ == "__main__":
    unittest.main()

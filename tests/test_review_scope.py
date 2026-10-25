import io
import contextlib
import unittest
from unittest.mock import patch

from prs import finding, pr_review as prr

A, B, C = "a" * 40, "b" * 40, "c" * 40


def review(reviewer, rnd, sha, at="2026-10-25T10:00:00Z", body=None):
    return {"body": body or prr.marker(reviewer, rnd, sha), "submitted_at": at}


class Marker(unittest.TestCase):
    def test_round_trip(self):
        text = f"## Code review\n\n{prr.marker('opus', 3, A)}\n\nbody"
        self.assertEqual(prr.marker("opus", 3, A), f"<!-- agent-review: reviewer=opus round=3 sha={A} -->")
        self.assertTrue(prr.marker("opus", 3, A).startswith(prr.MARKER_PREFIX))
        self.assertEqual(prr.MARKER_RE.search(text).groups(), ("opus", "3", A))

    def test_whitespace_is_tolerated(self):
        m = prr.MARKER_RE.search(f"<!--agent-review:   reviewer=codex   round=12  sha={B}-->")
        self.assertEqual(m.groups(), ("codex", "12", B))

    def test_the_posted_body_and_every_inline_comment_carry_it(self):
        sc = {"base_sha": None, "head": A, "base_branch": "main", "round": 2}
        mk = prr.marker("quality", 2, A)
        body = prr.build_body(sc, "quality", "Label", {"summary": "s", "findings": []}, [], [], mk, False)
        inline = prr.inline_body(finding(), "Label", mk)
        for text in (body, inline):
            self.assertEqual(prr.MARKER_RE.search(text).groups(), ("quality", "2", A))

    def test_a_notes_only_review_adds_the_fyi_marker(self):
        sc = {"base_sha": None, "head": A, "base_branch": "main", "round": 1, "pr": 5}
        table = {"a.py": {2}}
        with patch.object(prr, "commentable_lines", return_value=table):
            notes = prr.post(5, "opus", {"findings": [finding("low")], "summary": "s"}, sc, dry_run=True)
            fix = prr.post(5, "opus", {"findings": [finding("medium")], "summary": "s"}, sc, dry_run=True)
        self.assertTrue(notes["stop"])
        self.assertIn(f"{prr.marker('opus', 1, A)}\n{prr.FYI_MARKER}", notes["payload"]["body"])
        self.assertFalse(fix["stop"])
        self.assertNotIn(prr.FYI_MARKER, fix["payload"]["body"])
        self.assertEqual(len(fix["payload"]["comments"]), 1)
        self.assertIn(prr.marker("opus", 1, A), fix["payload"]["comments"][0]["body"])

    def test_no_findings_posts_nothing_and_stops(self):
        sc = {"base_sha": None, "head": A, "base_branch": "main", "round": 1}
        with patch.object(prr, "commentable_lines", return_value={}):
            out = prr.post(5, "opus", {"findings": [], "summary": " all fine "}, sc, dry_run=True)
        self.assertEqual((out["posted"], out["stop"], out["reason"], out["summary"]),
                         (False, True, "no-findings", "all fine"))


class Scope(unittest.TestCase):
    def scope(self, reviews, head=C, linear=True, clean=None):
        meta = {"number": 5, "state": "OPEN", "headRefName": "feat/x", "headRefOid": head, "baseRefName": "main",
                "title": "T", "isDraft": False}
        with patch.object(prr, "pr_meta", return_value=meta), patch.object(prr, "gh_json", return_value=reviews), \
                patch.object(prr, "linear_since", return_value=linear) as since, \
                patch.object(prr, "clean_cache", return_value=clean or {}):
            sc = prr.scope(5)
        self.since = since
        return sc

    def test_first_round_reviews_the_whole_change(self):
        sc = self.scope([{"body": "a human review", "submitted_at": ""}, {"body": None}])
        self.assertEqual((sc["round"], sc["base_sha"], sc["base_ref"], sc["diff_range"]),
                         (1, None, "origin/main", f"origin/main...{C}"))
        self.assertIn("the first review of this PR", sc["round_note"])
        self.assertEqual(sc["history"], [])
        self.since.assert_not_called()

    def test_next_round_diffs_since_the_last_reviewed_head_when_the_range_is_linear(self):
        sc = self.scope([review("opus", 1, A), review("codex", 1, A)], linear=True)
        self.assertEqual((sc["round"], sc["base_sha"], sc["base_ref"], sc["diff_range"]),
                         (2, A, A, f"{A}..{C}"))
        self.assertIn("Review ONLY the commits added since then", sc["round_note"])
        self.since.assert_called_once_with(A, C)

    def test_a_rebase_or_merge_falls_back_to_the_base_branch(self):
        sc = self.scope([review("opus", 1, A)], linear=False)
        self.assertEqual((sc["round"], sc["base_sha"], sc["diff_range"]), (2, None, f"origin/main...{C}"))
        self.assertIn("rebased or merged main", sc["round_note"])

    def test_the_last_round_before_the_head_is_the_diff_base(self):
        sc = self.scope([review("opus", 2, B), review("opus", 1, A)])
        self.assertEqual((sc["round"], sc["base_sha"]), (3, B))
        self.assertEqual([m["round"] for m in sc["history"]], [1, 2])

    def test_reviews_at_the_head_keep_the_round_and_the_earlier_base(self):
        sc = self.scope([review("opus", 1, A), review("opus", 2, C), review("codex", 2, C)])
        self.assertEqual((sc["round"], sc["base_sha"], sc["posted_at_head"]), (2, A, ["codex", "opus"]))

    def test_done_and_settled_merge_posted_reviews_with_the_clean_cache(self):
        reviews = [review("opus", 1, C)]
        sc = self.scope(reviews, clean={f"5/{C}": ["codex"], f"5/{A}": ["quality"]})
        self.assertEqual((sc["done_at_head"], sc["clean_at_head"], sc["settled"]),
                         (["codex", "opus"], ["codex"], False))
        sc = self.scope(reviews, clean={f"5/{C}": ["opus", "codex", "quality"]})
        self.assertTrue(sc["settled"])

    def test_fields_of_the_pr(self):
        sc = self.scope([])
        self.assertEqual((sc["pr"], sc["state"], sc["draft"], sc["title"], sc["branch"], sc["head"], sc["base_branch"]),
                         (5, "OPEN", False, "T", "feat/x", C, "main"))

    def test_markers_sort_by_round_then_time_and_skip_other_reviews(self):
        reviews = [review("codex", 2, B, "2026-10-25T12:00:00Z"), review("opus", 2, B, "2026-10-25T11:00:00Z"),
                   review("opus", 1, A), {"body": "<!-- agent-review-fyi -->"}]
        with patch.object(prr, "gh_json", return_value=reviews):
            self.assertEqual([(m["reviewer"], m["round"], m["sha"]) for m in prr.markers(5)],
                             [("opus", 1, A), ("opus", 2, B), ("codex", 2, B)])

    def test_linear_since(self):
        def sh(args, **kw):
            return type("R", (), {"returncode": sh.ancestor, "stdout": sh.merges})()
        with patch.object(prr, "sh", sh):
            sh.ancestor, sh.merges = 0, "\n"
            self.assertTrue(prr.linear_since(A, C))
            sh.ancestor = 1
            self.assertFalse(prr.linear_since(A, C))
            sh.ancestor, sh.merges = 0, f"{B}\n"
            self.assertFalse(prr.linear_since(A, C))


class ToFix(unittest.TestCase):
    def kept(self, findings, rnd):
        return [f["title"] for f in prr.to_fix(findings, rnd)]

    def test_fix_floor_is_medium_at_confidence_point_six(self):
        findings = [finding("critical", title="c"), finding("high", title="h"), finding("medium", title="m"),
                    finding("low", title="l"), finding("medium", 0.59, title="m-weak"),
                    finding("high", 0.6, title="h-edge"), {"severity": "high", "title": "no-conf"},
                    finding("high", "0.7", title="str-conf")]
        self.assertEqual(self.kept(findings, 1), ["c", "h", "m", "h-edge", "str-conf"])
        self.assertEqual(self.kept(findings, 3), ["c", "h", "m", "h-edge", "str-conf"])

    def test_from_round_four_only_high_and_critical(self):
        findings = [finding("critical", title="c"), finding("high", title="h"), finding("medium", title="m"),
                    finding("high", 0.3, title="h-weak")]
        for rnd in (4, 5, 9):
            self.assertEqual(self.kept(findings, rnd), ["c", "h"])
        self.assertEqual((prr.LATE_ROUND, prr.MIN_CONFIDENCE), (4, 0.6))

    def test_nothing_to_fix(self):
        self.assertEqual(prr.to_fix([], 1), [])
        self.assertEqual(prr.to_fix([finding("low")], 1), [])


class SplitFindings(unittest.TestCase):
    table = {"a.py": {1, 2, 3}}

    def split(self, *findings):
        inline, carried = prr.split_findings(list(findings), self.table)
        return [f["title"] for f in inline], [f["title"] for f in carried]

    def test_inline_needs_a_strong_finding_on_a_commentable_line(self):
        self.assertEqual(self.split(finding(title="ok"), finding(line_start=9, title="off-diff"),
                                    finding(file="b.py", title="no-file"), finding("low", title="low"),
                                    finding(confidence=0.5, title="weak")),
                         (["ok"], ["off-diff", "no-file", "low", "weak"]))

    def test_the_end_line_decides_and_falls_back_to_the_start_line(self):
        self.assertEqual(self.split(finding(line_start=1, line_end=3, title="a"),
                                    finding(line_start=1, line_end=9, title="b"),
                                    finding(line_start=9, line_end=2, title="c")), (["a", "c"], ["b"]))

    def test_late_rounds_do_not_change_the_inline_floor(self):
        self.assertEqual(self.split(finding("medium", title="m")), (["m"], []))

    def test_a_file_without_a_patch_has_no_commentable_lines(self):
        self.assertEqual(prr.split_findings([finding()], {"a.py": set()}), ([], [finding()]))


class CommentableLines(unittest.TestCase):
    def lines(self, files):
        with patch.object(prr, "gh_json", return_value=files) as gh:
            table = prr.commentable_lines(7)
        self.assertEqual((gh.call_args.args, gh.call_args.kwargs), ((f"repos/{prr.REPO}/pulls/7/files",), {"paginate": True}))
        return table

    def test_right_hand_lines_of_context_and_added_rows(self):
        patch_ = "@@ -1,3 +1,4 @@\n ctx\n-old\n+new\n+added\n ctx2\n\\ No newline at end of file"
        self.assertEqual(self.lines([{"filename": "a.py", "patch": patch_}]), {"a.py": {1, 2, 3, 4}})

    def test_several_hunks(self):
        patch_ = "@@ -1,2 +1,2 @@\n a\n+b\n@@ -10 +20,2 @@\n-x\n+y\n+z"
        self.assertEqual(self.lines([{"filename": "a.py", "patch": patch_}]), {"a.py": {1, 2, 20, 21}})

    def test_new_file_with_a_single_line_hunk(self):
        self.assertEqual(self.lines([{"filename": "n.py", "patch": "@@ -0,0 +1 @@\n+only"}]), {"n.py": {1}})

    def test_removed_lines_only_and_patchless_files(self):
        table = self.lines([{"filename": "d.py", "patch": "@@ -1,2 +0,0 @@\n-a\n-b"}, {"filename": "bin.png"},
                            {"filename": "big.json", "patch": ""}])
        self.assertEqual(table, {"d.py": set(), "bin.png": set(), "big.json": set()})


class ExtractJson(unittest.TestCase):
    def test_plain_object(self):
        self.assertEqual(prr.extract_json('{"a": 1}'), {"a": 1})
        self.assertEqual(prr.extract_json('Here it is:\n{"a": {"b": [1, 2]}}'), {"a": {"b": [1, 2]}})

    def test_fenced_block_with_or_without_a_language(self):
        self.assertEqual(prr.extract_json('text\n```json\n{"a": 1}\n```\nbye'), {"a": 1})
        self.assertEqual(prr.extract_json('```\n{"a": 2}\n```'), {"a": 2})

    def test_the_last_parsable_fence_wins(self):
        text = '```json\n{"a": 1}\n```\nthen\n```json\n{"a": 2}\n```\n```\nnot json\n```'
        self.assertEqual(prr.extract_json(text), {"a": 2})

    def test_a_stray_brace_before_the_object_is_skipped(self):
        self.assertEqual(prr.extract_json('see {this} first {"a": 1}'), {"a": 1})

    def test_trailing_prose_after_an_unfenced_object_is_ignored(self):
        self.assertEqual(prr.extract_json('text {"a":1} trailing'), {"a": 1})
        self.assertEqual(prr.extract_json('{"a": {"b": 1}}\n\nHope that helps {really}'), {"a": {"b": 1}})

    def test_no_json_exits_with_an_error(self):
        with contextlib.redirect_stderr(io.StringIO()) as err, self.assertRaises(SystemExit) as ctx:
            prr.extract_json("nothing here")
        self.assertEqual(ctx.exception.code, 1)
        self.assertIn("no parsable JSON object", err.getvalue())


if __name__ == "__main__":
    unittest.main()

"""Tests of scripts/new_code_coverage.py: the new lines, the reports, and the gate."""

import contextlib
import io
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import new_code_coverage as ncc

import tests

DIFF = """\
diff --git a/scripts/a.py b/scripts/a.py
--- a/scripts/a.py
+++ b/scripts/a.py
@@ -3,0 +4,2 @@ def f():
+    x = 1
+    y = 2
@@ -10 +12 @@ def g():
-    old
+    new
diff --git a/gone.py b/gone.py
--- a/gone.py
+++ /dev/null
@@ -1,2 +0,0 @@
-a
-b
"""


class DiffTest(unittest.TestCase):
    def test_added_lines_by_file(self):
        self.assertEqual(ncc.diff_lines(DIFF), {"scripts/a.py": {4, 5, 12}})

    def test_nothing(self):
        self.assertEqual(ncc.diff_lines(""), {})


class LcovTest(unittest.TestCase):
    def test_relative_and_absolute_paths(self):
        root = Path("/repo")
        text = "SF:scripts/a.py\nDA:1,1\nDA:2,0\nend_of_record\nSF:/repo/plugins/x/src/lib.rs\nDA:5,3\nDA:5,0\n"
        self.assertEqual(
            ncc.read_lcov(text, root),
            {"scripts/a.py": {1: 1, 2: 0}, "plugins/x/src/lib.rs": {5: 3}},
        )

    def test_a_path_outside_the_repository_stays_as_it_is(self):
        self.assertEqual(ncc.read_lcov("SF:/elsewhere/b.rs\nDA:1,1\n", Path("/repo")), {"/elsewhere/b.rs": {1: 1}})


class ExclusionsTest(unittest.TestCase):
    def test_sonar_globs(self):
        excluded = ncc.sonar_exclusions(
            "sonar.sources=.\nsonar.exclusions=tests/**,plugins/**/test_*.py\nsonar.coverage.exclusions=x?.rs\n"
        )
        matches = lambda p: any(r.match(p) for r in excluded)  # noqa: E731
        self.assertTrue(matches("tests/test_x.py"))
        self.assertTrue(matches("plugins/film-grain/test_film_grain.py"))
        self.assertTrue(matches("xa.rs"))
        self.assertFalse(matches("plugins/film-grain/film_grain.py"))
        self.assertFalse(matches("scripts/tests.py"))
        self.assertFalse(matches("xab.rs"))


class MeasureTest(unittest.TestCase):
    def test_only_new_lines_with_code_count(self):
        new = {"a.py": {1, 2, 3, 9}, "tests/t.py": {1}, "b.rs": {4}}
        covered = {"a.py": {1: 1, 2: 0, 3: 2}, "tests/t.py": {1: 0}, "b.rs": {4: 0}}
        total, hit, missed = ncc.measure(new, covered, ncc.sonar_exclusions("sonar.exclusions=tests/**"))
        self.assertEqual((total, hit, missed), (4, 2, {"a.py": 1, "b.rs": 1}))


class GitEnvironmentTest(unittest.TestCase):
    def test_variables_naming_a_repository_are_removed(self):
        # Every one the installed git lists is in tests/__init__.py's list (which may name more:
        # the list differs between git versions, and removing a variable git doesn't set is
        # harmless), and none is left.
        listed = subprocess.run(
            ["git", "rev-parse", "--local-env-vars"], capture_output=True, text=True, check=True
        ).stdout.split()
        self.assertEqual(sorted(set(listed) - set(tests.GIT_LOCAL_ENV_VARS)), [])
        self.assertEqual([v for v in tests.GIT_LOCAL_ENV_VARS if v in os.environ], [])


class MainTest(unittest.TestCase):
    """main on a repository of its own: a commit on main, then a branch with new code."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        patcher = mock.patch.object(ncc, "ROOT", self.root)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.git("init", "-q", "-b", "main")
        self.write("a.py", "one\n")
        self.write("sonar-project.properties", "sonar.exclusions=tests/**\n")
        self.git("add", ".")
        self.git("commit", "-q", "-m", "start")
        self.git("switch", "-q", "-c", "feature")

    def git(self, *a):
        subprocess.run(
            ["git", "-c", "user.name=Test", "-c", "user.email=test@example.com", *a],
            cwd=self.root,
            check=True,
            capture_output=True,
        )

    def write(self, path, text):
        p = self.root / path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")

    def run_main(self, lcov, *argv, rust=""):
        self.write("coverage/python.lcov", lcov)
        self.write("coverage/rust.lcov", rust)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = ncc.main(list(argv))
        return code, out.getvalue()

    def test_committed_staged_and_rust_changes_count(self):
        self.write("a.py", "one\ntwo\nthree\n")
        self.git("commit", "-qam", "more")
        self.write("b.py", "new\nfile\n")
        self.write("src/lib.rs", "fn f() {}\n")
        self.write("tests/t.py", "left out\n")
        self.git("add", "b.py", "src/lib.rs", "tests/t.py")
        lcov = "SF:a.py\nDA:1,1\nDA:2,1\nDA:3,0\nSF:b.py\nDA:1,1\nDA:2,1\nSF:tests/t.py\nDA:1,0\n"
        rust = f"SF:{self.root}/src/lib.rs\nDA:1,1\n"
        code, out = self.run_main(lcov, "--min", "70", rust=rust)
        self.assertEqual(code, 0, out)
        self.assertIn("80.0% of new code covered (4 of 5 lines since", out)

    def test_a_file_git_does_not_know_is_not_read(self):
        self.write("c.py", "untracked\n")
        code, out = self.run_main("SF:c.py\nDA:1,0\n")
        self.assertEqual((code, out), (0, "coverage: no new lines to cover\n"))

    def test_below_the_gate_names_the_files(self):
        self.write("a.py", "one\ntwo\nthree\n")
        code, out = self.run_main("SF:a.py\nDA:2,0\nDA:3,1\n", "--min", "80")
        self.assertEqual(code, 1)
        self.assertIn("50.0% of new code covered", out)
        self.assertIn("   1 uncovered  a.py", out)
        self.assertIn("below 80%", out)

    def test_no_new_code(self):
        code, out = self.run_main("SF:a.py\nDA:1,1\n")
        self.assertEqual((code, out), (0, "coverage: no new lines to cover\n"))

    def test_base_is_main_without_origin(self):
        main = subprocess.run(["git", "rev-parse", "main"], cwd=self.root, capture_output=True, text=True, check=True)
        self.assertEqual(ncc.base(), main.stdout.strip())

    def test_only_a_commit_hash_reaches_git_diff(self):
        for since in ("--output=x", "main", "HEAD~1", ""):
            with self.assertRaisesRegex(ncc.Error, "not a commit hash"):
                ncc.new_lines(since)
        with mock.patch.object(ncc, "git", return_value="-x\n"), self.assertRaisesRegex(ncc.Error, "gave '-x'"):
            ncc.base()

    def test_no_option_names_a_branch(self):
        with self.assertRaises(SystemExit), mock.patch("sys.stderr", io.StringIO()):
            ncc.main(["--base", "--output=x"])

    def test_a_missing_report(self):
        self.write("coverage/python.lcov", "")
        with self.assertRaisesRegex(ncc.Error, "coverage/rust.lcov is missing"):
            ncc.main([])


if __name__ == "__main__":
    unittest.main()

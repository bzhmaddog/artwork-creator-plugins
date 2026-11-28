"""Tests of scripts/app_versions.py: the app versions of the plugin page, from the app's tags."""

import contextlib
import io
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

import app_versions

import tests.repo  # noqa: F401  (puts scripts/ on the path)


def git(repo, *args):
    subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *args],
        check=True,
        capture_output=True,
    )


class AppVersionsTest(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.repo = Path(folder.name)
        git(self.repo, "init", "-q")
        (self.repo / "plugin-sdk" / "src").mkdir(parents=True)

    def release(self, tag, sdk, abi):
        (self.repo / "plugin-sdk" / "Cargo.toml").write_text(f'[package]\nname = "s"\nversion = "{sdk}"\n')
        (self.repo / "plugin-sdk" / "src" / "abi.rs").write_text(
            f"pub const ABI_VERSION: u32 = {abi};\npub const OLDEST_ABI_VERSION: u32 = 1;\n"
        )
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "--allow-empty", "-m", tag)
        git(self.repo, "tag", tag)

    def test_releases_from_the_first_app_newest_first(self):
        self.release("v0.15.0", "0.2.0", 2)
        self.release("v0.16.0", "0.3.0", 2)
        self.release("v0.9.1", "0.3.0", 2)
        self.release("v0.21.0", "0.6.0", 3)
        self.release("v0.21.1-rc1", "0.6.0", 3)
        self.release("other", "0.6.0", 3)
        self.assertEqual(
            app_versions.app_versions(self.repo),
            [
                {"version": "0.21.0", "sdk": "0.6.0", "abi": [1, 3]},
                {"version": "0.16.0", "sdk": "0.3.0", "abi": [1, 2]},
            ],
        )

    def test_development_is_the_checkout_as_it_is(self):
        self.release("v0.16.0", "0.3.0", 2)
        (self.repo / "Cargo.toml").write_text('[package]\nname = "app"\nversion = "0.17.0"\n')
        (self.repo / "plugin-sdk" / "Cargo.toml").write_text('[package]\nname = "s"\nversion = "0.4.0"\n')
        self.assertEqual(
            app_versions.development(self.repo),
            {"label": "Current", "version": "0.17.0", "sdk": "0.4.0", "abi": [1, 2]},
        )

    def test_missing_constant(self):
        self.release("v0.16.0", "0.3.0", 2)
        (self.repo / "plugin-sdk" / "src" / "abi.rs").write_text("nothing\n")
        git(self.repo, "commit", "-q", "-am", "broken")
        git(self.repo, "tag", "v0.17.0")
        with self.assertRaisesRegex(ValueError, "OLDEST_ABI_VERSION not found"):
            app_versions.app_versions(self.repo)

    def test_main(self):
        self.release("v0.16.0", "0.3.0", 2)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(app_versions.main([str(self.repo)]), 0)
        self.assertEqual(json.loads(out.getvalue())["apps"][0]["version"], "0.16.0")
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(app_versions.main([]), 2)

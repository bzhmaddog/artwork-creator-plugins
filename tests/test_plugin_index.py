"""Tests of scripts/plugin_index.py: manifests, tags, index entries, merge and validate."""

import argparse
import contextlib
import hashlib
import io
import json
import subprocess
import sys
import unittest
from typing import Any, ClassVar
from unittest import mock

from tests.repo import ROOT, RS_SOURCE, RepoTestCase, release_version
from tests.repo import plugin_index as pi

INDEX_SCRIPT = ROOT / "scripts" / "plugin_index.py"


def args(**kw):
    return argparse.Namespace(**kw)


def quiet(fn, *a):
    """fn(*a) with its stdout, returned."""
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        fn(*a)
    return out.getvalue()


class SemverTest(unittest.TestCase):
    def test_orders_numerically(self):
        self.assertLess(pi.semver("1.2.9"), pi.semver("1.10.0"))
        self.assertEqual(pi.semver("0.16.0"), (0, 16, 0))

    def test_tag_pattern(self):
        match = pi.TAG_RE.match("swap-channels-1.0.0")
        assert match
        self.assertEqual(match["version"], "1.0.0")
        for bad in ("halftone", "halftone-1.0", "halftone-v1.0.0", "Halftone-1.0.0", "-1.0.0"):
            self.assertIsNone(pi.TAG_RE.match(bad), bad)


class CompatibleFromTest(unittest.TestCase):
    def test_absent_is_fine(self):
        self.assertEqual(pi.compatible_from_errors({"version": "1.0.0"}), [])

    def test_must_be_a_version(self):
        for bad in ("1.0", 1, "v1.0.0"):
            self.assertEqual(len(pi.compatible_from_errors({"compatible_from": bad})), 1, bad)

    def test_not_after_the_version(self):
        self.assertEqual(pi.compatible_from_errors({"version": "1.0.0", "compatible_from": "1.0.0"}), [])
        self.assertIn("later than", pi.compatible_from_errors({"version": "1.0.0", "compatible_from": "1.0.1"})[0])

    def index(self, *versions):
        return {"plugins": [{"id": "p", "versions": list(versions)}]}

    def test_first_release_gets_its_own_version(self):
        self.assertEqual(pi.inherited_compatible_from(self.index(), "p", "1.0.0"), "1.0.0")

    def test_inherits_from_the_latest_earlier_version(self):
        index = self.index(
            {"version": "0.1.0", "compatible_from": "0.1.0"},
            {"version": "0.3.0", "compatible_from": "0.2.0"},
            {"version": "2.0.0", "compatible_from": "2.0.0"},
        )
        self.assertEqual(pi.inherited_compatible_from(index, "p", "1.0.0"), "0.2.0")
        # Another plugin's versions don't count.
        self.assertEqual(pi.inherited_compatible_from(index, "q", "1.0.0"), "1.0.0")

    def test_filled_in_after_min_app(self):
        v = pi.with_compatible_from({"version": "1.0.0", "min_app": "0.16.0", "files": {}}, self.index(), "p")
        self.assertEqual(list(v), ["version", "min_app", "compatible_from", "files"])
        self.assertEqual(v["compatible_from"], "1.0.0")

    def test_filled_in_at_the_end_without_min_app(self):
        v = pi.with_compatible_from({"version": "1.0.0"}, self.index(), "p")
        self.assertEqual(v, {"version": "1.0.0", "compatible_from": "1.0.0"})

    def test_given_one_is_kept(self):
        v = {"version": "1.0.0", "compatible_from": "0.5.0"}
        self.assertIs(pi.with_compatible_from(v, self.index(), "p"), v)


class ProvidesTest(unittest.TestCase):
    def test_good(self):
        self.assertEqual(pi.provides_errors({"effects": ["A", "B"]}), [])
        self.assertEqual(pi.provides_errors({"generators": ["G"]}), [])

    def test_needs_one(self):
        self.assertEqual(len(pi.provides_errors({})), 1)

    def test_bad_lists(self):
        for bad in ([], "A", ["A", ""], ["A", " "], [1]):
            self.assertIn("non-empty list", pi.provides_errors({"effects": bad, "generators": ["G"]})[0], bad)

    def test_duplicate(self):
        self.assertIn("twice", pi.provides_errors({"effects": ["A", "A"]})[0])


class LoadPluginTest(RepoTestCase):
    def test_python(self):
        m = pi.load_plugin(self.add_python())
        self.assertEqual(m["version"], "1.0.0")
        self.assertEqual(m["files"], {"any": "demo.py"})

    def test_rust_version_and_files_come_from_cargo(self):
        m = pi.load_plugin(self.add_rust(package="my-fx"))
        self.assertEqual((m["version"], m["package"], m["lib"]), ("0.2.0", "my-fx", "my_fx"))
        self.assertEqual(m["files"], {"linux-x86_64": "libmy_fx.so", "windows-x86_64": "my_fx.dll"})

    def test_rust_lib_name(self):
        m = pi.load_plugin(self.add_rust(lib="fx-core"))
        self.assertEqual(m["files"]["windows-x86_64"], "fx_core.dll")

    def assert_error(self, folder, text):
        with self.assertRaises(pi.Error) as e:
            pi.load_plugin(folder)
        self.assertIn(text, str(e.exception))

    def test_no_manifest(self):
        (self.root / "plugins" / "empty").mkdir()
        self.assert_error(self.root / "plugins" / "empty", "no plugin.json")

    def test_missing_fields(self):
        self.assert_error(self.add_python(author=None, license=None), "missing author, license")

    def test_id_is_the_folder(self):
        folder = self.add_python()
        m = json.loads((folder / "plugin.json").read_text())
        m["id"] = "other"
        (folder / "plugin.json").write_text(json.dumps(m))
        self.assert_error(folder, "is not the folder name")

    def test_compat_from_spelling(self):
        self.assert_error(self.add_python(compat_from="1.0.0"), "spelled compatible_from")

    def test_kind(self):
        self.assert_error(self.add_python(kind="wasm"), "kind must be one of")

    def test_script_must_exist(self):
        self.assert_error(self.add_python(script=None), "script 'demo.py' not found")

    def test_provides(self):
        self.assert_error(self.add_python(effects=None, generators=None), "effects or generators")

    def test_version_format(self):
        self.assert_error(self.add_python(version="1.0"), "is not X.Y.Z")
        self.assert_error(self.add_rust(version="1.0.0-beta.1"), "is not X.Y.Z")

    def test_compatible_from(self):
        self.assert_error(self.add_python(compatible_from="2.0.0"), "later than the version")


class CodeProvidesTest(RepoTestCase):
    def test_python(self):
        folder = self.add_python()
        self.assertEqual(
            pi.code_provides(folder, pi.load_plugin(folder)), {"effects": ["Invert"], "generators": ["Noise"]}
        )

    def test_python_class_without_name(self):
        folder = self.add_python(script="from artwork_plugin_sdk import Effect\n\nclass X(Effect):\n    id = 'x'\n")
        with self.assertRaisesRegex(pi.Error, "has no name"):
            pi.code_provides(folder, pi.load_plugin(folder))

    def test_python_ignores_other_classes(self):
        script = "class Helper:\n    name = 'Nope'\n\nclass Invert(Effect):\n    name = 'Invert'\n"
        folder = self.add_python(script=script, generators=None)
        self.assertEqual(pi.code_provides(folder, pi.load_plugin(folder)), {"effects": ["Invert"], "generators": []})

    def test_rust(self):
        folder = self.add_rust()
        self.assertEqual(
            pi.code_provides(folder, pi.load_plugin(folder)), {"effects": ["Blur"], "generators": ["Grid"]}
        )

    def test_rust_without_export(self):
        folder = self.add_rust(source="struct A;\n")
        with self.assertRaisesRegex(pi.Error, "no export_plugin"):
            pi.code_provides(folder, pi.load_plugin(folder))

    def test_rust_name_not_a_literal(self):
        folder = self.add_rust(source=RS_SOURCE.replace('"Blur"', "NAME"))
        with self.assertRaisesRegex(pi.Error, "no literal fn name in impl Effect for Blur"):
            pi.code_provides(folder, pi.load_plugin(folder))

    def test_rust_trailing_comma_and_unreadable_type(self):
        folder = self.add_rust(source=RS_SOURCE.replace("effects: [Blur]", "effects: [Blur,]"))
        self.assertEqual(pi.code_provides(folder, pi.load_plugin(folder))["effects"], ["Blur"])
        folder = self.add_rust(source=RS_SOURCE.replace("effects: [Blur]", "effects: [fx::Blur]"))
        with self.assertRaisesRegex(pi.Error, "can't read 'fx::Blur'"):
            pi.code_provides(folder, pi.load_plugin(folder))

    def test_real_plugins_match_their_manifests(self):
        with mock.patch.object(pi, "PLUGINS", ROOT / "plugins"):
            for folder in pi.plugin_dirs():
                m = pi.load_plugin(folder)
                code = pi.code_provides(folder, m)
                for k in pi.PROVIDES:
                    self.assertEqual(sorted(m.get(k, [])), sorted(code[k]), f"{folder.name} {k}")


class ParseTagTest(RepoTestCase):
    def test_finds_the_plugin(self):
        self.add_python()
        folder, m = pi.parse_tag("demo-1.0.0")
        self.assertEqual((folder.name, m["version"]), ("demo", "1.0.0"))

    def test_folder_ending_in_digits(self):
        self.add_python("fx")
        self.add_python("fx-2", version="3.0.0")
        self.assertEqual(pi.parse_tag("fx-2-3.0.0")[0].name, "fx-2")
        self.assertEqual(pi.parse_tag("fx-1.0.0")[0].name, "fx")

    def test_version_mismatch_names_the_file(self):
        self.add_python()
        self.add_rust()
        with self.assertRaisesRegex(pi.Error, "demo/plugin.json says version 1.0.0"):
            pi.parse_tag("demo-1.0.1")
        with self.assertRaisesRegex(pi.Error, "rusty/Cargo.toml says version 0.2.0"):
            pi.parse_tag("rusty-0.3.0")

    def test_bad_tags(self):
        self.add_python()
        with self.assertRaisesRegex(pi.Error, "is not <plugin>-<X.Y.Z>"):
            pi.parse_tag("demo-v1")
        with self.assertRaisesRegex(pi.Error, "no plugin folder 'other'"):
            pi.parse_tag("other-1.0.0")


class ResolveTest(RepoTestCase):
    def test_python(self):
        self.add_python()
        out = quiet(pi.cmd_resolve, args(tag="demo-1.0.0"))
        self.assertEqual(out.splitlines(), ["dir=demo", "kind=python", "version=1.0.0", "name=Demo", "script=demo.py"])

    def test_rust(self):
        self.add_rust(package="rusty-fx")
        out = dict(line.split("=", 1) for line in quiet(pi.cmd_resolve, args(tag="rusty-0.2.0")).splitlines())
        self.assertEqual((out["package"], out["lib"], out["kind"]), ("rusty-fx", "rusty_fx", "library"))

    def test_already_released(self):
        self.add_python()
        self.write_index([{"id": "demo", "versions": [release_version("demo", "1.0.0")]}])
        with self.assertRaisesRegex(pi.Error, "already in plugins.json"):
            pi.cmd_resolve(args(tag="demo-1.0.0"))


class Pep723Test(RepoTestCase):
    def test_dependencies(self):
        script = self.write(
            "s.py",
            '# /// script\n# requires-python = ">=3.11"\n'
            '# dependencies = [\n#   "numpy>=2",\n#   "pillow",\n# ]\n'
            "# ///\nimport numpy\n",
        )
        self.assertEqual(pi.pep723_dependencies(script), ["numpy>=2", "pillow"])

    def test_none(self):
        self.assertEqual(pi.pep723_dependencies(self.write("s.py", "import math\n")), [])
        self.assertEqual(
            pi.pep723_dependencies(self.write("s.py", "# /// script\n# requires-python = '>=3.11'\n# ///\n")), []
        )


class SdkAbiTest(RepoTestCase):
    def metadata(self, abi_source):
        sdk = self.root / "sdk"
        self.write("sdk/src/abi.rs", abi_source)
        meta = {
            "packages": [
                {"name": "serde", "manifest_path": "/x/Cargo.toml"},
                {"name": "artwork-plugin-sdk", "manifest_path": str(sdk / "Cargo.toml")},
            ]
        }
        return mock.patch.object(
            pi.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, json.dumps(meta), "")
        )

    def test_reads_abi_version(self):
        with self.metadata("/// The ABI.\npub const ABI_VERSION: u32 = 4;\n") as run:
            self.assertEqual(pi.sdk_abi(), 4)
        self.assertIn("--locked", run.call_args.args[0])
        with self.metadata("pub const ABI_VERSION: u32 = 4;\n") as run:
            pi.sdk_abi(locked=False)
        self.assertNotIn("--locked", run.call_args.args[0])

    def test_not_found(self):
        with self.metadata("pub const OTHER: u32 = 4;\n"), self.assertRaisesRegex(pi.Error, "ABI_VERSION"):
            pi.sdk_abi()


class TagMessageTest(RepoTestCase):
    def git(self, *a):
        subprocess.run(
            ["git", "-c", "user.name=Test", "-c", "user.email=test@example.com", *a],
            cwd=self.root,
            check=True,
            capture_output=True,
        )

    def test_annotated_lightweight_and_missing(self):
        self.git("init", "-q")
        self.git("commit", "-q", "--allow-empty", "-m", "start")
        self.git("tag", "-a", "demo-1.0.0", "-m", "Faster noise\n\nAnd a fix.")
        self.git("tag", "demo-1.0.1")
        self.assertEqual(pi.tag_message("demo-1.0.0"), "Faster noise\n\nAnd a fix.")
        self.assertIsNone(pi.tag_message("demo-1.0.1"))
        self.assertIsNone(pi.tag_message("demo-9.9.9"))


class PluginEntryTest(RepoTestCase):
    files: ClassVar = {"any": {"url": "u", "sha256": "0" * 64, "size": 1}}

    def test_python(self):
        folder = self.add_python(compatible_from="0.9.0")
        self.write(
            "plugins/demo/demo.py",
            '# /// script\n# dependencies = ["numpy"]\n# ///\n' + (folder / "demo.py").read_text(),
        )
        entry = pi.plugin_entry(folder, pi.load_plugin(folder), self.files, "Changes")
        self.assertEqual(entry["latest"], "1.0.0")
        self.assertEqual([k for k in entry if k not in ("latest", "versions")], list(pi.PLUGIN_FIELDS))
        [v] = entry["versions"]
        self.assertEqual(v["compatible_from"], "0.9.0")
        self.assertEqual(v["dependencies"], ["numpy"])
        self.assertEqual(v["changes"], "Changes")
        self.assertEqual(v["sdk"], "0.3.0")
        self.assertNotIn("abi", v)
        self.assertEqual(list(v)[-1], "files")

    def test_library_gets_the_abi(self):
        folder = self.add_rust()
        v = pi.plugin_entry(folder, pi.load_plugin(folder), self.files, abi=7)["versions"][0]
        self.assertEqual(v["abi"], 7)
        self.assertNotIn("changes", v)
        self.assertNotIn("compatible_from", v)

    def test_compatible_from_from_the_index(self):
        folder = self.add_python()
        index = {"plugins": [{"id": "demo", "versions": [{"version": "0.5.0", "compatible_from": "0.4.0"}]}]}
        v = pi.plugin_entry(folder, pi.load_plugin(folder), self.files, index=index)["versions"][0]
        self.assertEqual(v["compatible_from"], "0.4.0")


class PrepareTest(RepoTestCase):
    def test_hashes_the_files_and_writes_notes(self):
        folder = self.add_python()
        assets = self.root / "dist"
        assets.mkdir()
        data = (folder / "demo.py").read_bytes()
        (assets / "demo.py").write_bytes(data)
        out, notes = self.root / "entry.json", self.root / "notes.md"
        with mock.patch.object(pi, "tag_message", return_value="Better noise"):
            pi.cmd_prepare(
                args(tag="demo-1.0.0", assets=str(assets), base_url="https://x/dl/", out=str(out), notes=str(notes))
            )
        f = json.loads(out.read_text())["versions"][0]["files"]["any"]
        self.assertEqual(
            f, {"url": "https://x/dl/demo.py", "sha256": hashlib.sha256(data).hexdigest(), "size": len(data)}
        )
        self.assertTrue(notes.read_text().startswith("Better noise\n"))
        self.assertIn(f["sha256"], notes.read_text())

    def test_missing_file(self):
        self.add_python()
        (self.root / "dist").mkdir()
        with self.assertRaisesRegex(pi.Error, "demo.py missing"):
            pi.cmd_prepare(args(tag="demo-1.0.0", assets=str(self.root / "dist"), base_url="u", out="o", notes=None))


class VerifyTest(RepoTestCase):
    def entry(self, data, sha=None, size=None):
        path = self.write(
            "entry.json",
            json.dumps(
                {
                    "versions": [
                        {
                            "files": {
                                "any": {
                                    "url": "https://example.com/f",
                                    "sha256": sha or hashlib.sha256(data).hexdigest(),
                                    "size": len(data) if size is None else size,
                                }
                            }
                        }
                    ]
                }
            ),
        )
        return args(entry=str(path))

    def urlopen(self, data):
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = data
        return mock.patch.object(pi.urllib.request, "urlopen", return_value=response)

    def test_ok(self):
        with self.urlopen(b"abc"):
            self.assertIn("ok any", quiet(pi.cmd_verify, self.entry(b"abc")))

    def test_mismatch(self):
        for entry in (self.entry(b"abc", sha="0" * 64), self.entry(b"abc", size=4)):
            with self.urlopen(b"abc"), self.assertRaisesRegex(pi.Error, "does not match"):
                pi.cmd_verify(entry)

    def test_retries_then_fails(self):
        with (
            mock.patch.object(pi.urllib.request, "urlopen", side_effect=OSError("down")) as urlopen,
            mock.patch.object(pi.time, "sleep") as sleep,
            self.assertRaisesRegex(pi.Error, "down"),
        ):
            pi.cmd_verify(self.entry(b"abc"))
        self.assertEqual(urlopen.call_count, 6)
        self.assertEqual(sleep.call_count, 5)


class MergeTest(RepoTestCase):
    def entry(self, id, version, **extra):
        e = {
            "id": id,
            "name": id.title(),
            "kind": "python",
            "latest": version,
            "versions": [release_version(id, version, compatible_from=None, **extra)],
        }
        return args(entry=str(self.write(f"{id}-{version}.json", json.dumps(e))))

    def test_new_plugin(self):
        self.write_index([{"id": "zeta", "versions": [release_version("zeta", "1.0.0")], "latest": "1.0.0"}])
        quiet(pi.cmd_merge, self.entry("alpha", "0.1.0"))
        plugins = self.read_index()["plugins"]
        self.assertEqual([p["id"] for p in plugins], ["alpha", "zeta"])
        self.assertEqual(plugins[0]["latest"], "0.1.0")
        self.assertEqual(plugins[0]["versions"][0]["compatible_from"], "0.1.0")

    def test_versions_newest_first_and_latest(self):
        self.write_index(
            [
                {
                    "id": "demo",
                    "name": "Old name",
                    "latest": "1.0.0",
                    "versions": [release_version("demo", "1.0.0", compatible_from="0.5.0")],
                }
            ]
        )
        quiet(pi.cmd_merge, self.entry("demo", "1.1.0"))
        quiet(pi.cmd_merge, self.entry("demo", "0.9.0"))
        [p] = self.read_index()["plugins"]
        self.assertEqual([v["version"] for v in p["versions"]], ["1.1.0", "1.0.0", "0.9.0"])
        self.assertEqual(p["latest"], "1.1.0")
        # The details follow the entry merged last.
        self.assertEqual(p["name"], "Demo")
        # compatible_from carried over from the version before.
        self.assertEqual(p["versions"][0]["compatible_from"], "0.5.0")
        self.assertEqual(p["versions"][2]["compatible_from"], "0.9.0")
        self.assertEqual(list(p)[-2:], ["latest", "versions"])

    def test_merged_index_validates(self):
        self.add_python()
        quiet(pi.cmd_merge, self.entry("demo", "1.0.0"))
        quiet(pi.cmd_validate, args())

    def test_twice(self):
        quiet(pi.cmd_merge, self.entry("demo", "1.0.0"))
        before = self.read_index()
        with self.assertRaisesRegex(pi.Error, "already in plugins.json"):
            pi.cmd_merge(self.entry("demo", "1.0.0"))
        self.assertEqual(self.read_index(), before)


class ValidateTest(RepoTestCase):
    def setUp(self):
        super().setUp()
        self.add_python()
        self.add_rust()
        self.index: list[dict[str, Any]] = [
            {"id": "demo", "latest": "1.0.0", "versions": [release_version("demo", "1.0.0")]}
        ]

    def problems(self):
        self.write_index(self.index)
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.suppress(pi.Error):
            pi.cmd_validate(args())
        return [line.removeprefix("::error::") for line in out.getvalue().splitlines() if line.startswith("::error::")]

    def assert_problem(self, text):
        problems = self.problems()
        self.assertTrue(any(text in p for p in problems), problems)

    def test_ok(self):
        self.assertEqual(self.problems(), [])
        self.write_index(self.index)
        self.assertIn("ok: 2 plugins, 1 in the index", quiet(pi.cmd_validate, args()))

    def test_manifest_and_code_disagree(self):
        self.add_python(effects=["Invert", "Sharpen"])
        self.assert_problem("plugin.json effects ['Invert', 'Sharpen'] don't match the code's ['Invert']")

    def test_folder_without_manifest(self):
        (self.root / "plugins" / "stray").mkdir()
        (self.root / "plugins" / ".hidden").mkdir()
        self.assertEqual(self.problems(), ["plugins/stray has no plugin.json"])

    def test_workspace_member_missing(self):
        self.add_rust("other", member=False)
        self.assert_problem("plugins/other is not in the workspace members")

    def test_format(self):
        self.write("plugins.json", json.dumps({"format": 2, "plugins": []}))
        out = io.StringIO()
        with contextlib.redirect_stdout(out), self.assertRaises(pi.Error):
            pi.cmd_validate(args())
        self.assertIn("needs format 1", out.getvalue())

    def test_duplicates(self):
        self.index[0]["versions"].append(release_version("demo", "1.0.0"))
        self.index.append(dict(self.index[0]))
        self.assert_problem("plugins.json: demo listed twice")
        self.assert_problem("plugins.json: demo 1.0.0 listed twice")

    def test_version_fields(self):
        v = self.index[0]["versions"][0]
        v.pop("compatible_from")
        v["effects"] = []
        self.assert_problem("has no compatible_from")
        self.assert_problem("effects must be a non-empty list")

    def test_abi_1_has_no_generators(self):
        self.index[0]["versions"][0].update(abi=1, generators=["G"])
        self.assert_problem("ABI 1 has no generators")

    def test_files(self):
        v = self.index[0]["versions"][0]
        v["files"]["any"].update(
            url="https://github.com/o/r/releases/download/demo-0.9.0/demo.py", sha256="xyz", size=0
        )
        self.assert_problem("url is not a release asset of demo-1.0.0")
        self.assert_problem("bad sha256")
        self.assert_problem("bad size")
        v["files"] = {}
        self.assert_problem("demo 1.0.0 has no files")

    def test_latest(self):
        self.index[0]["versions"].insert(0, release_version("demo", "1.10.0"))
        self.assert_problem("latest is '1.0.0', but its latest version is 1.10.0")

    def test_a_break_stays_a_break(self):
        self.index[0]["latest"] = "1.2.0"
        self.index[0]["versions"] += [
            release_version("demo", "1.1.0", compatible_from="1.1.0"),
            release_version("demo", "1.2.0", compatible_from="1.0.0"),
        ]
        self.assert_problem("demo 1.2.0: compatible_from 1.0.0 is older than 1.1.0")


class CommandLineTest(unittest.TestCase):
    """The script as the Makefile and the workflows run it, on this repository."""

    def run_script(self, *a):
        return subprocess.run(
            [sys.executable, str(INDEX_SCRIPT), *a], cwd=ROOT, capture_output=True, text=True, check=False
        )

    def test_validate_this_repository(self):
        r = self.run_script("validate")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_version(self):
        for plugin in ("halftone", "posterize", "swap-channels"):
            r = self.run_script("version", plugin)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertRegex(r.stdout.strip(), pi.VERSION_RE)

    def test_error_exit(self):
        r = self.run_script("resolve", "nope-1.0.0")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("no plugin folder 'nope'", r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main()

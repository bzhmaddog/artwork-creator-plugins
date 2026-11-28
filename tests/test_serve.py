"""Tests of scripts/serve.py: the list made from the working tree, and the HTTP server."""

import hashlib
import io
import json
import subprocess
import threading
import urllib.error
import urllib.request
from unittest import mock

import serve

from tests.repo import RepoTestCase


class ServeTestCase(RepoTestCase):
    def setUp(self):
        super().setUp()
        # The server's request log and build messages go to stderr.
        for patcher in (mock.patch.object(serve, "ROOT", self.root), mock.patch("sys.stderr", io.StringIO())):
            patcher.start()
            self.addCleanup(patcher.stop)


class LocalRepositoryTest(ServeTestCase):
    def test_python_plugins_listed_with_their_hash(self):
        folder = self.add_python()
        repo = serve.LocalRepository("http://h:1", [])
        index = repo.index()
        [p] = index["plugins"]
        [v] = p["versions"]
        data = (folder / "demo.py").read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        self.assertEqual(
            v["files"]["any"], {"url": f"http://h:1/files/{digest}/demo.py", "sha256": digest, "size": len(data)}
        )
        self.assertIn("working tree", v["changes"])
        self.assertEqual(repo.files[digest], ("demo.py", data))

    def test_released_versions_follow_the_working_tree_s(self):
        self.add_python()
        old = {"version": "0.9.0", "files": {"any": {"url": "https://github.com/x/demo.py"}}}
        replaced = {"version": "1.0.0", "files": {}}
        index = {"format": 1, "plugins": [{"id": "demo", "versions": [replaced, old]}]}
        (self.root / "plugins.json").write_text(json.dumps(index))
        [p] = serve.LocalRepository("u", []).index()["plugins"]
        self.assertEqual([v["version"] for v in p["versions"]], [p["latest"], "0.9.0"])
        self.assertIn("working tree", p["versions"][0]["changes"])
        self.assertEqual(p["versions"][1], old)
        # No plugins.json: the working tree's alone.
        (self.root / "plugins.json").write_text("not json")
        [p] = serve.LocalRepository("u", []).index()["plugins"]
        self.assertEqual(len(p["versions"]), 1)

    def test_an_old_file_stays_downloadable_after_an_edit(self):
        folder = self.add_python()
        repo = serve.LocalRepository("u", [])
        first = repo.index()["plugins"][0]["versions"][0]["files"]["any"]["sha256"]
        (folder / "demo.py").write_text((folder / "demo.py").read_text() + "\n# edited\n")
        second = repo.index()["plugins"][0]["versions"][0]["files"]["any"]["sha256"]
        self.assertNotEqual(first, second)
        self.assertIn(first, repo.files)

    def test_unbuilt_library_left_out(self):
        self.add_python()
        self.add_rust()
        with mock.patch.object(serve, "sdk_abi") as sdk_abi:
            index = serve.LocalRepository("u", []).index()
        self.assertEqual([p["id"] for p in index["plugins"]], ["demo"])
        sdk_abi.assert_not_called()

    def test_built_library_listed_with_the_abi(self):
        self.add_rust()
        out = self.root / "target" / "x86_64-unknown-linux-gnu" / "release"
        out.mkdir(parents=True)
        (out / "librusty.so").write_bytes(b"\x7fELF")
        with mock.patch.object(serve, "sdk_abi", return_value=3) as sdk_abi:
            [p] = serve.LocalRepository("u", []).index()["plugins"]
        sdk_abi.assert_called_once_with("rusty", locked=False)
        v = p["versions"][0]
        self.assertEqual(v["abi"], 3)
        self.assertEqual(list(v["files"]), ["linux-x86_64"])

    def test_builds_every_target(self):
        ok = subprocess.CompletedProcess([], 0, "", "")
        with mock.patch.object(serve.subprocess, "run", return_value=ok) as run:
            serve.LocalRepository("u", ["t1", "t2"]).index()
        self.assertEqual([c.args[0][-1] for c in run.call_args_list], ["t1", "t2"])
        self.assertNotIn("--locked", run.call_args_list[0].args[0])

    def test_build_failure(self):
        failed = subprocess.CompletedProcess([], 101, "", "error[E0425]: oops")
        with (
            mock.patch.object(serve.subprocess, "run", return_value=failed),
            self.assertRaisesRegex(serve.Error, "E0425"),
        ):
            serve.LocalRepository("u", ["t1"]).index()


class ServerTest(ServeTestCase):
    def setUp(self):
        super().setUp()
        self.server, self.repo = serve.make_server("127.0.0.1", 0, [])
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.url = self.repo.base_url

    def get(self, path, method="GET"):
        try:
            with urllib.request.urlopen(urllib.request.Request(self.url + path, method=method), timeout=10) as r:
                return r.status, r.headers, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.headers, e.read()

    def test_base_url_has_the_real_port(self):
        self.assertEqual(self.url, f"http://127.0.0.1:{self.server.server_address[1]}")

    def test_list_and_download(self):
        folder = self.add_python()
        status, headers, body = self.get("/plugins.json?x=1")
        self.assertEqual(
            (status, headers["Content-Type"], headers["Cache-Control"]), (200, "application/json", "no-store")
        )
        f = json.loads(body)["plugins"][0]["versions"][0]["files"]["any"]
        self.assertTrue(f["url"].startswith(self.url + "/files/"))
        status, _, data = self.get(f["url"][len(self.url) :])
        self.assertEqual((status, data), (200, (folder / "demo.py").read_bytes()))

    def test_head(self):
        self.add_python()
        status, headers, body = self.get("/plugins.json", "HEAD")
        self.assertEqual(status, 200)
        self.assertEqual(body, b"")
        self.assertGreater(int(headers["Content-Length"]), 0)

    def test_not_found(self):
        self.add_python()
        _, _, body = self.get("/plugins.json")
        digest = json.loads(body)["plugins"][0]["versions"][0]["files"]["any"]["sha256"]
        for path in (
            "/",
            "/index.js",
            "/files/" + "0" * 64 + "/demo.py",
            f"/files/{digest}/other.py",
            "/../plugins.json",
        ):
            self.assertEqual(self.get(path)[0], 404, path)

    def test_site(self):
        site = self.root / "site"
        site.mkdir()
        (site / "index.html").write_text("<p>page</p>")
        (site / "index.js").write_text("main();")
        (self.root / "secret.txt").write_text("no")
        status, headers, body = self.get("/")
        self.assertEqual((status, headers["Content-Type"], body), (200, "text/html; charset=utf-8", b"<p>page</p>"))
        (site / "index.html").write_text("<head><title>t</title></head><body></body>")
        _, _, body = self.get("/index.html")
        self.assertEqual(body, b"<head><title>t</title>" + serve.INDEX_SOURCES_META + b"</head><body></body>")
        status, headers, body = self.get("/index.js?v=2")
        self.assertEqual(status, 200)
        self.assertIn("javascript", headers["Content-Type"])
        self.assertEqual(body, b"main();")
        for path in ("/site/index.js", "/../secret.txt", "/%2e%2e/secret.txt", "/missing.js"):
            self.assertEqual(self.get(path)[0], 404, path)

    def test_index_sources(self):
        status, headers, body = self.get("/sources.json")
        self.assertEqual((status, headers["Content-Type"]), (200, "application/json"))
        sources = json.loads(body)["sources"]
        self.assertEqual([s["id"] for s in sources], ["local", "file", "published"])
        self.assertEqual(sources[2]["url"], serve.PUBLISHED_INDEX)

    def test_app_versions(self):
        dev = {"label": "Current", "version": "0.22.0", "sdk": "0.7.0", "abi": [1, 3]}
        apps = [{"version": "0.21.0", "sdk": "0.6.0", "abi": [1, 3]}]
        with mock.patch.object(serve, "APP_CHECKOUT", self.root / "app"):
            self.assertEqual(self.get("/apps.json")[0], 404)
            (self.root / "app" / ".git").mkdir(parents=True)
            with (
                mock.patch.object(serve, "app_versions", return_value=apps),
                mock.patch.object(serve, "development", return_value=dev),
            ):
                status, headers, body = self.get("/apps.json")
            self.assertEqual(
                (status, headers["Content-Type"], json.loads(body)), (200, "application/json", {"apps": [dev, *apps]})
            )
            with mock.patch.object(serve, "development", side_effect=ValueError("ABI_VERSION not found")):
                status, _, body = self.get("/apps.json")
            self.assertEqual((status, body), (500, b"ABI_VERSION not found\n"))

    def test_malformed_index_is_unreadable(self):
        for index in (
            "[1]",
            '{"plugins": [{"name": "no id"}]}',
            '{"plugins": 3}',
            '{"plugins": [{"id": "x", "versions": 3}]}',
        ):
            (self.root / "plugins.json").write_text(index)
            self.assertEqual(serve.LocalRepository.released(), {}, index)

    def test_repository_index(self):
        (self.root / "plugins.json").unlink(missing_ok=True)
        self.assertEqual(self.get("/repository/plugins.json")[0], 404)
        (self.root / "plugins.json").write_text('{"format": 1, "plugins": []}')
        status, headers, body = self.get("/repository/plugins.json")
        self.assertEqual((status, headers["Content-Type"]), (200, "application/json"))
        self.assertEqual(json.loads(body), {"format": 1, "plugins": []})

    def test_error_in_the_list(self):
        self.add_python(version="bad")
        status, _, body = self.get("/plugins.json")
        self.assertEqual(status, 500)
        self.assertIn(b"is not X.Y.Z", body)

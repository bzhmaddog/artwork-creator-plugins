#!/usr/bin/env python3
"""Serve the working tree's plugins as a plugin repository on this machine, to try them in
the app before a release (make serve). The list is the one the Release workflow would
write (plugin_index.plugin_entry), made from the manifests and builds, with every file
served from here instead of a GitHub Release, followed by the versions already released
(those of the repository's plugins.json, downloaded from their GitHub Release as from the
published list), so an app the working tree's version doesn't work with is offered the
latest released one that does, as it would be. It's made again on every fetch: the Rust
plugins are rebuilt and every file is hashed again. The page of site/ is served at /, to
preview it with that list, and the repository's plugins.json file, as it is on disk, at
/repository/plugins.json.

Standard library only (Python 3.11+).
"""

import argparse
import contextlib
import hashlib
import http.server
import json
import mimetypes
import subprocess
import sys
import threading

from app_versions import app_versions, development
from plugin_index import ROOT, Error, load_plugin, plugin_dirs, plugin_entry, sdk_abi

# The page that lists the plugins (site/, published with plugins.json on GitHub Pages).
SITE = "site"

# The app checkout whose tags give the page's app versions (/apps.json), as the Pages
# workflow publishes them from the app's repository, after its own files as they are, the
# select's "Current" item.
APP_CHECKOUT = ROOT.parent / "artwork-creator-app"

# The official index, as the app reads it (OFFICIAL in the app).
PUBLISHED_INDEX = "https://bzhmaddog.github.io/artwork-creator-plugins/plugins.json"

# The indexes the page offers in its select when served from here (/sources.json): this
# server's list, the repository's plugins.json file as it is on disk, uncommitted edits
# included (/repository/plugins.json, the file the Release workflow updates) and the
# published one. The page reads this list only when
# it names it, which it does only when served from here (INDEX_SOURCES_META).
INDEX_SOURCES = {
    "sources": [
        {"id": "local", "label": "Working tree (make serve)", "url": "plugins.json"},
        {"id": "file", "label": "plugins.json of this clone", "url": "repository/plugins.json"},
        {"id": "published", "label": "Published (GitHub Pages)", "url": PUBLISHED_INDEX},
    ]
}
INDEX_SOURCES_META = b'<meta name="index-sources" content="sources.json">\n'

# Platform key in the index -> Rust target whose target/ folder has its file.
PLATFORM_TARGETS = {"linux-x86_64": "x86_64-unknown-linux-gnu", "windows-x86_64": "x86_64-pc-windows-gnu"}


class LocalRepository:
    """A repository list made from the working tree. Files are kept by their SHA-256, so a
    download always matches the list it came from, even after a rebuild."""

    def __init__(self, base_url, build):
        self.base_url = base_url
        self.build = build
        self.files = {}  # sha256 -> (name, bytes)
        self.lock = threading.Lock()

    # No --locked here, unlike the release: a version bumped in a Cargo.toml goes into
    # Cargo.lock on the next fetch of the list, instead of failing it.
    def cargo_build(self):
        for target in self.build:
            print(f"building for {target}", file=sys.stderr)
            r = subprocess.run(
                ["cargo", "build", "--release", "--workspace", "--target", target],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            if r.returncode:
                raise Error(f"cargo build --target {target} failed:\n{r.stderr[-4000:]}")

    def file_path(self, folder, m, platform, name):
        if m["kind"] == "python":
            return folder / name
        target = PLATFORM_TARGETS.get(platform)
        return ROOT / "target" / target / "release" / name if target else None

    @staticmethod
    def released():
        """The versions of each plugin in the repository's plugins.json, by id; none if it
        can't be read."""
        try:
            index = json.loads((ROOT / "plugins.json").read_text(encoding="utf-8"))
            plugins = index["plugins"]
            return {p["id"]: list(p.get("versions", [])) for p in plugins}
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            return {}

    def index(self):
        with self.lock:
            self.cargo_build()
            plugins = []
            released = self.released()
            for folder in plugin_dirs():
                m = load_plugin(folder)
                files = {}
                for platform, name in m["files"].items():
                    path = self.file_path(folder, m, platform, name)
                    if path is None or not path.is_file():
                        continue
                    data = path.read_bytes()
                    digest = hashlib.sha256(data).hexdigest()
                    self.files[digest] = (name, data)
                    files[platform] = {
                        "url": f"{self.base_url}/files/{digest}/{name}",
                        "sha256": digest,
                        "size": len(data),
                    }
                if not files:
                    print(f"{m['id']}: no file built, left out (make linux / make windows)", file=sys.stderr)
                    continue
                # Each library's own SDK: two may differ.
                abi = sdk_abi(m["package"], locked=False) if m["kind"] == "library" else None
                changes = f"Local build of {m['id']} {m['version']} (working tree)"
                # Made from the working tree alone, not from the committed plugins.json: a
                # version has a compatible_from only when its manifest gives one.
                entry = plugin_entry(folder, m, files, changes, abi)
                # Then the released versions, but the one the working tree replaces.
                entry["versions"] += [v for v in released.get(m["id"], []) if v["version"] != m["version"]]
                plugins.append(entry)
            return {"format": 1, "name": "Local plugins (working tree)", "plugins": plugins}


def site_file(path):
    """The file of site/ a request path names ("/" is index.html), or None. Only the names
    of the files directly in site/ match, so no path can reach outside it."""
    name = "index.html" if path == "/" else path[1:]
    folder = ROOT / SITE
    if not folder.is_dir():
        return None
    files = {p.name: p for p in folder.iterdir() if p.is_file()}
    return files.get(name)


def make_server(host, port, build):
    """The HTTP server of a LocalRepository, bound but not serving yet. With port 0 the
    system picks a free port, which the list's URLs then use."""
    repo = LocalRepository(None, build)

    class Handler(http.server.BaseHTTPRequestHandler):
        def send(self, status, body, content_type):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def do_GET(self):
            path = self.path.split("?", 1)[0]
            if path == "/plugins.json":
                try:
                    index = repo.index()
                except (Error, OSError, ValueError, KeyError, subprocess.CalledProcessError) as e:
                    print(f"error: {e}", file=sys.stderr)
                    return self.send(500, f"{e}\n".encode(), "text/plain; charset=utf-8")
                body = json.dumps(index, indent=2, ensure_ascii=False) + "\n"
                return self.send(200, body.encode(), "application/json")
            if path == "/sources.json":
                body = json.dumps(INDEX_SOURCES, indent=2) + "\n"
                return self.send(200, body.encode(), "application/json")
            if path == "/apps.json" and (APP_CHECKOUT / ".git").exists():
                try:
                    apps = [development(APP_CHECKOUT), *app_versions(APP_CHECKOUT)]
                    body = json.dumps({"apps": apps}, indent=2) + "\n"
                except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as e:
                    print(f"error: {e}", file=sys.stderr)
                    return self.send(500, f"{e}\n".encode(), "text/plain; charset=utf-8")
                return self.send(200, body.encode(), "application/json")
            if path == "/repository/plugins.json":
                on_disk = ROOT / "plugins.json"
                if on_disk.is_file():
                    return self.send(200, on_disk.read_bytes(), "application/json")
            page = site_file(path)
            if page is not None:
                content_type = mimetypes.guess_type(page.name)[0] or "application/octet-stream"
                if content_type.startswith("text/") or content_type.endswith("javascript"):
                    content_type += "; charset=utf-8"
                data = page.read_bytes()
                # The page's select of indexes (see INDEX_SOURCES), before the page's script runs.
                if page.name == "index.html":
                    data = data.replace(b"</head>", INDEX_SOURCES_META + b"</head>", 1)
                return self.send(200, data, content_type)
            parts = path.strip("/").split("/")
            if len(parts) == 3 and parts[0] == "files" and parts[1] in repo.files:
                name, data = repo.files[parts[1]]
                if parts[2] == name:
                    return self.send(200, data, "application/octet-stream")
            self.send(404, b"not found; the list is at /plugins.json\n", "text/plain")

        do_HEAD = do_GET

    server = http.server.ThreadingHTTPServer((host, port), Handler)
    url_host = "127.0.0.1" if host in ("", "0.0.0.0", "::") else host
    repo.base_url = f"http://{url_host}:{server.server_address[1]}"
    return server, repo


def serve(host, port, build):
    server, repo = make_server(host, port, build)
    print(f"Local plugin repository: {repo.base_url}/plugins.json (Ctrl+C to stop)", file=sys.stderr)
    with contextlib.suppress(KeyboardInterrupt):
        server.serve_forever()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", default="127.0.0.1", help="address to listen on (default 127.0.0.1)")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument(
        "--build",
        action="append",
        default=[],
        metavar="TARGET",
        help="Rust target to rebuild on every fetch of the list (repeatable)",
    )
    args = ap.parse_args()
    try:
        serve(args.host, args.port, args.build)
    except (Error, OSError) as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

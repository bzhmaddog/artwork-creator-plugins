#!/usr/bin/env python3
"""Serve the working tree's plugins as a plugin repository on this machine, to try them in
the app before a release (make serve). The list is the one the Release workflow would
write (plugin_index.plugin_entry), made from the manifests and builds only (the committed
plugins.json isn't read), with every file served from here instead of a GitHub Release,
and it's made again on every fetch: the Rust plugins are rebuilt and every file is
hashed again.

Standard library only (Python 3.11+).
"""

import argparse
import hashlib
import http.server
import json
import subprocess
import sys
import threading

from plugin_index import ROOT, Error, load_plugin, plugin_dirs, plugin_entry, sdk_abi

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
            r = subprocess.run(["cargo", "build", "--release", "--workspace", "--target", target],
                               cwd=ROOT, capture_output=True, text=True)
            if r.returncode:
                raise Error(f"cargo build --target {target} failed:\n{r.stderr[-4000:]}")

    def file_path(self, folder, m, platform, name):
        if m["kind"] == "python":
            return folder / name
        target = PLATFORM_TARGETS.get(platform)
        return ROOT / "target" / target / "release" / name if target else None

    def index(self):
        with self.lock:
            self.cargo_build()
            abi = None
            plugins = []
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
                    files[platform] = {"url": f"{self.base_url}/files/{digest}/{name}",
                                       "sha256": digest, "size": len(data)}
                if not files:
                    print(f"{m['id']}: no file built, left out (make linux / make windows)", file=sys.stderr)
                    continue
                if m["kind"] == "library" and abi is None:
                    abi = sdk_abi(locked=False)
                changes = f"Local build of {m['id']} {m['version']} (working tree)"
                # Made from the working tree alone, not from the committed plugins.json: a
                # version has a compatible_from only when its manifest gives one.
                plugins.append(plugin_entry(folder, m, files, changes, abi))
            return {"format": 1, "name": "Local plugins (working tree)", "plugins": plugins}


def serve(host, port, build):
    url_host = "127.0.0.1" if host in ("", "0.0.0.0", "::") else host
    repo = LocalRepository(f"http://{url_host}:{port}", build)

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
            parts = path.strip("/").split("/")
            if len(parts) == 3 and parts[0] == "files" and parts[1] in repo.files:
                name, data = repo.files[parts[1]]
                if parts[2] == name:
                    return self.send(200, data, "application/octet-stream")
            self.send(404, b"not found; the list is at /plugins.json\n", "text/plain")

        do_HEAD = do_GET

    server = http.server.ThreadingHTTPServer((host, port), Handler)
    print(f"Local plugin repository: {repo.base_url}/plugins.json (Ctrl+C to stop)", file=sys.stderr)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", default="127.0.0.1", help="address to listen on (default 127.0.0.1)")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--build", action="append", default=[], metavar="TARGET",
                    help="Rust target to rebuild on every fetch of the list (repeatable)")
    args = ap.parse_args()
    try:
        serve(args.host, args.port, args.build)
    except (Error, OSError) as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

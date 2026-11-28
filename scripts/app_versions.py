#!/usr/bin/env python3
"""The app versions the plugin page offers in its select (site/index.js), as the apps.json
the Pages workflow publishes next to it: for each release tag of the app (vX.Y.Z) from
the first app that reads plugins.json on, the version of the plugin SDK it ships and the
library ABI versions it loads, read from the tag in a clone of the app's repository.

    python3 scripts/app_versions.py <app clone>       the JSON on stdout

Standard library only (Python 3.11+).
"""

import json
import re
import subprocess
import sys
import tomllib
from pathlib import Path

# The first app that reads a plugin repository's list.
FIRST_APP = (0, 16, 0)

TAG = re.compile(r"v(\d+)\.(\d+)\.(\d+)")


def show(repo, tag, path):
    """The text of path at tag in the git repository repo."""
    return subprocess.run(
        ["git", "-C", str(repo), "show", f"{tag}:{path}"], check=True, capture_output=True, text=True
    ).stdout


def abi_constant(text, name):
    found = re.search(rf"pub const {name}: u32 = (\d+);", text)
    if not found:
        raise ValueError(f"{name} not found")
    return int(found[1])


def app_entry(version, read):
    """The entry of the app version whose files read(path) gives (the text of a path in the
    app's repository): {version, sdk, abi: [oldest, newest]}."""
    sdk = tomllib.loads(read("plugin-sdk/Cargo.toml"))["package"]["version"]
    abi = read("plugin-sdk/src/abi.rs")
    return {
        "version": version,
        "sdk": sdk,
        "abi": [abi_constant(abi, "OLDEST_ABI_VERSION"), abi_constant(abi, "ABI_VERSION")],
    }


def app_versions(repo):
    """The app releases in the clone repo, newest first."""
    tags = subprocess.run(
        ["git", "-C", str(repo), "tag", "--list", "v*"], check=True, capture_output=True, text=True
    ).stdout.split()
    releases = sorted((tuple(map(int, m.groups())), tag) for tag in tags if (m := TAG.fullmatch(tag)))
    return [
        app_entry(tag[1:], lambda path, tag=tag: show(repo, tag, path))
        for version, tag in reversed(releases)
        if version >= FIRST_APP
    ]


def development(repo):
    """The app of the checkout repo as its files are (make serve), labelled "Current"."""
    read = lambda path: (Path(repo) / path).read_text(encoding="utf-8")  # noqa: E731
    version = tomllib.loads(read("Cargo.toml"))["package"]["version"]
    return {"label": "Current", **app_entry(version, read)}


def main(argv):
    if len(argv) != 1:
        print("usage: app_versions.py <clone of the app's repository>", file=sys.stderr)
        return 2
    print(json.dumps({"apps": app_versions(Path(argv[0]))}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

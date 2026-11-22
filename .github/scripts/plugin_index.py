#!/usr/bin/env python3
"""The plugin index (plugins.json) and the releases it points to.

Each plugin is a folder of plugins/ with a plugin.json manifest (id, name, description, author,
homepage, license, kind, min_app; for a Python plugin also version, script and sdk). A
release is a tag <folder>-<version>; the Release workflow uses these commands:

  resolve TAG          check the tag against the plugin and print what to build, as
                       key=value lines for $GITHUB_OUTPUT
  prepare TAG ...      hash the built files and write the plugin's index entry
  verify ENTRY         download every file of an entry and check its size and SHA-256
  merge ENTRY          add an entry's version to plugins.json
  validate             check plugins.json and every manifest (CI)
  version PLUGIN       print a plugin's version (make tag)

Standard library only (Python 3.11+).
"""

import argparse
import datetime
import hashlib
import json
import re
import subprocess
import sys
import time
import tomllib
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INDEX = ROOT / "plugins.json"
PLUGINS = ROOT / "plugins"
TAG_RE = re.compile(r"^(?P<dir>[a-z0-9][a-z0-9-]*?)-(?P<version>\d+\.\d+\.\d+)$")
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")
KINDS = ("library", "python")
REQUIRED = ("id", "name", "description", "author", "license", "kind", "min_app")
# Fields of a manifest copied to the plugin's entry in the index, and to each version.
PLUGIN_FIELDS = ("id", "name", "description", "author", "homepage", "license", "kind")
VERSION_FIELDS = ("min_app", "sdk")
PEP723_RE = re.compile(r"(?m)^# /// script\s*$\s(?P<content>(^#(| .*)$\s)+)^# ///$")


class Error(Exception):
    pass


def semver(v):
    return tuple(int(x) for x in v.split("."))


def plugin_dirs():
    return sorted(p.parent for p in PLUGINS.glob("*/plugin.json"))


def load_plugin(folder):
    """The manifest of a plugin folder, checked, with version and files filled in."""
    folder = Path(folder)
    path = folder / "plugin.json"
    if not path.is_file():
        raise Error(f"{folder.name}: no plugin.json")
    m = json.loads(path.read_text(encoding="utf-8"))
    missing = [k for k in REQUIRED if not m.get(k)]
    if missing:
        raise Error(f"{path.name} of {folder.name}: missing {', '.join(missing)}")
    if m["id"] != folder.name:
        raise Error(f"{folder.name}: id {m['id']!r} is not the folder name")
    if m["kind"] not in KINDS:
        raise Error(f"{folder.name}: kind must be one of {', '.join(KINDS)}")
    if m["kind"] == "library":
        cargo = tomllib.loads((folder / "Cargo.toml").read_text(encoding="utf-8"))
        package = cargo["package"]["name"]
        lib = cargo.get("lib", {}).get("name", package).replace("-", "_")
        m["version"] = cargo["package"]["version"]
        m["package"] = package
        m["lib"] = lib
        # Platform key in the index -> file name the build makes.
        m["files"] = {"linux-x86_64": f"lib{lib}.so", "windows-x86_64": f"{lib}.dll"}
    else:
        script = m.get("script")
        if not script or not (folder / script).is_file():
            raise Error(f"{folder.name}: script {script!r} not found")
        m["files"] = {"any": script}
    if not VERSION_RE.match(m.get("version", "")):
        raise Error(f"{folder.name}: version {m.get('version')!r} is not X.Y.Z")
    return m


def parse_tag(tag):
    t = TAG_RE.match(tag)
    if not t:
        raise Error(f"tag {tag!r} is not <plugin>-<X.Y.Z>")
    # The folder name may itself end in -<digits>; take the longest folder that exists.
    for folder in sorted(plugin_dirs(), key=lambda p: -len(p.name)):
        if tag.startswith(folder.name + "-") and VERSION_RE.match(tag[len(folder.name) + 1:]):
            m = load_plugin(folder)
            version = tag[len(folder.name) + 1:]
            if m["version"] != version:
                where = "Cargo.toml" if m["kind"] == "library" else "plugin.json"
                raise Error(f"tag {tag} but {folder.name}/{where} says version {m['version']}")
            return folder, m
    raise Error(f"tag {tag!r}: no plugin folder {t['dir']!r} with a plugin.json")


def released_versions(plugin_id):
    index = json.loads(INDEX.read_text(encoding="utf-8"))
    for p in index["plugins"]:
        if p["id"] == plugin_id:
            return {v["version"] for v in p["versions"]}
    return set()


def cmd_resolve(args):
    folder, m = parse_tag(args.tag)
    if m["version"] in released_versions(m["id"]):
        raise Error(f"{m['id']} {m['version']} is already in plugins.json")
    out = {"dir": folder.name, "kind": m["kind"], "version": m["version"], "name": m["name"]}
    if m["kind"] == "library":
        out.update(package=m["package"], lib=m["lib"])
    else:
        out["script"] = m["script"]
    for k, v in out.items():
        print(f"{k}={v}")


def sdk_abi():
    """ABI_VERSION of the plugin SDK the workspace builds against."""
    meta = json.loads(subprocess.run(
        ["cargo", "metadata", "--format-version", "1", "--locked"],
        cwd=ROOT, check=True, capture_output=True, text=True).stdout)
    for p in meta["packages"]:
        if p["name"] == "artwork-plugin-sdk":
            abi = Path(p["manifest_path"]).parent / "src" / "abi.rs"
            found = re.search(r"pub const ABI_VERSION: u32 = (\d+);", abi.read_text(encoding="utf-8"))
            if found:
                return int(found[1])
    raise Error("ABI_VERSION of artwork-plugin-sdk not found")


def tag_message(tag):
    """The message of an annotated tag (the version's changes), or None."""
    def git(*a):
        return subprocess.run(["git", *a], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    if git("cat-file", "-t", f"refs/tags/{tag}") != "tag":
        return None
    text = git("tag", "-l", "--format=%(contents:subject)%0a%0a%(contents:body)", tag).strip()
    return text or None


def pep723_dependencies(script):
    """Dependencies from the PEP 723 block of a Python plugin, if it has one."""
    found = PEP723_RE.search(script.read_text(encoding="utf-8"))
    if not found:
        return []
    toml = "".join(line[2:] if line.startswith("# ") else line[1:]
                   for line in found["content"].splitlines(keepends=True))
    return tomllib.loads(toml).get("dependencies", [])


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def cmd_prepare(args):
    folder, m = parse_tag(args.tag)
    assets = Path(args.assets)
    version = {"version": m["version"], "released": datetime.date.today().isoformat()}
    if m["kind"] == "library":
        version["abi"] = sdk_abi()
    for k in VERSION_FIELDS:
        if m.get(k):
            version[k] = m[k]
    changes = tag_message(args.tag)
    if changes:
        version["changes"] = changes
    if m["kind"] == "python":
        deps = pep723_dependencies(folder / m["script"])
        if deps:
            version["dependencies"] = deps
    files = {}
    for platform, name in m["files"].items():
        path = assets / name
        if not path.is_file():
            raise Error(f"{name} missing from {assets}")
        files[platform] = {
            "url": f"{args.base_url.rstrip('/')}/{name}",
            "sha256": sha256(path),
            "size": path.stat().st_size,
        }
    version["files"] = files
    entry = {k: m[k] for k in PLUGIN_FIELDS if m.get(k)}
    entry["versions"] = [version]
    Path(args.out).write_text(json.dumps(entry, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if args.notes:
        lines = [changes or f"{m['name']} {m['version']}", "", "| Platform | File | SHA-256 |", "|---|---|---|"]
        lines += [f"| {p} | {m['files'][p]} | `{f['sha256']}` |" for p, f in files.items()]
        Path(args.notes).write_text("\n".join(lines) + "\n", encoding="utf-8")


def cmd_verify(args):
    entry = json.loads(Path(args.entry).read_text(encoding="utf-8"))
    for platform, f in entry["versions"][0]["files"].items():
        for attempt in range(6):
            try:
                with urllib.request.urlopen(f["url"], timeout=60) as r:
                    data = r.read()
                break
            except OSError as e:
                if attempt == 5:
                    raise Error(f"{f['url']}: {e}")
                time.sleep(5 * (attempt + 1))
        if len(data) != f["size"] or hashlib.sha256(data).hexdigest() != f["sha256"]:
            raise Error(f"{f['url']} does not match its size and SHA-256")
        print(f"ok {platform} {f['url']}")


def cmd_merge(args):
    entry = json.loads(Path(args.entry).read_text(encoding="utf-8"))
    index = json.loads(INDEX.read_text(encoding="utf-8"))
    new = entry["versions"][0]
    plugin = next((p for p in index["plugins"] if p["id"] == entry["id"]), None)
    if plugin is None:
        plugin = {"versions": []}
        index["plugins"].append(plugin)
    if any(v["version"] == new["version"] for v in plugin["versions"]):
        raise Error(f"{entry['id']} {new['version']} is already in plugins.json")
    versions = sorted(plugin["versions"] + [new], key=lambda v: semver(v["version"]), reverse=True)
    # The plugin's details follow its latest release; versions keep their own.
    plugin.clear()
    plugin.update({k: v for k, v in entry.items() if k != "versions"})
    plugin["versions"] = versions
    index["plugins"].sort(key=lambda p: p["id"])
    INDEX.write_text(json.dumps(index, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"added {entry['id']} {new['version']} to plugins.json")


def cmd_version(args):
    print(load_plugin(PLUGINS / args.plugin)["version"])


def cmd_validate(args):
    errors = []
    for folder in plugin_dirs():
        try:
            load_plugin(folder)
        except (Error, OSError, ValueError, KeyError) as e:
            errors.append(str(e))
    for folder in PLUGINS.iterdir():
        if folder.is_dir() and not (folder / "plugin.json").is_file():
            errors.append(f"plugins/{folder.name} has no plugin.json")
    workspace = tomllib.loads((ROOT / "Cargo.toml").read_text(encoding="utf-8"))["workspace"]["members"]
    for cargo in PLUGINS.glob("*/Cargo.toml"):
        if f"plugins/{cargo.parent.name}" not in workspace:
            errors.append(f"plugins/{cargo.parent.name} is not in the workspace members of Cargo.toml")
    index = json.loads(INDEX.read_text(encoding="utf-8"))
    if index.get("format") != 1 or not isinstance(index.get("plugins"), list):
        errors.append("plugins.json: needs format 1 and a plugins list")
    ids = set()
    for p in index.get("plugins", []):
        pid = p.get("id")
        if pid in ids:
            errors.append(f"plugins.json: {pid} listed twice")
        ids.add(pid)
        seen = set()
        for v in p.get("versions", []):
            where = f"plugins.json: {pid} {v.get('version')}"
            if v.get("version") in seen:
                errors.append(f"{where} listed twice")
            seen.add(v.get("version"))
            if not v.get("files"):
                errors.append(f"{where} has no files")
            for platform, f in v.get("files", {}).items():
                tag = f"{pid}-{v.get('version')}"
                if not re.fullmatch(r"https://github\.com/[^/]+/[^/]+/releases/download/" + re.escape(tag) + r"/[^/]+", f.get("url", "")):
                    errors.append(f"{where} {platform}: url is not a release asset of {tag}")
                if not re.fullmatch(r"[0-9a-f]{64}", f.get("sha256", "")):
                    errors.append(f"{where} {platform}: bad sha256")
                if not isinstance(f.get("size"), int) or f["size"] <= 0:
                    errors.append(f"{where} {platform}: bad size")
    for e in errors:
        print(f"::error::{e}")
    if errors:
        raise Error(f"{len(errors)} problem(s)")
    print(f"ok: {len(plugin_dirs())} plugins, {len(ids)} in the index")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("resolve")
    s.add_argument("tag")
    s.set_defaults(fn=cmd_resolve)
    s = sub.add_parser("prepare")
    s.add_argument("tag")
    s.add_argument("--assets", required=True, help="folder with the built files")
    s.add_argument("--base-url", required=True, help="URL the files are published under")
    s.add_argument("--out", required=True, help="index entry to write")
    s.add_argument("--notes", help="release notes to write")
    s.set_defaults(fn=cmd_prepare)
    s = sub.add_parser("verify")
    s.add_argument("entry")
    s.set_defaults(fn=cmd_verify)
    s = sub.add_parser("merge")
    s.add_argument("entry")
    s.set_defaults(fn=cmd_merge)
    s = sub.add_parser("version")
    s.add_argument("plugin")
    s.set_defaults(fn=cmd_version)
    s = sub.add_parser("validate")
    s.set_defaults(fn=cmd_validate)
    args = ap.parse_args()
    try:
        args.fn(args)
    except Error as e:
        print(f"::error::{e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

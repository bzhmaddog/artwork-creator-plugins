#!/usr/bin/env python3
"""The plugin index (plugins.json) and the releases it points to.

Each plugin is a folder of plugins/ with a plugin.json manifest (id, name, description, author,
homepage, license, kind, min_app, optionally compatible_from, and effects and/or generators: the display names of what it
provides; for a Python plugin also version, script and sdk). A release is a tag <folder>-<version>; the Release workflow uses these commands:

  resolve TAG          check the tag against the plugin and print what to build, as
                       key=value lines for $GITHUB_OUTPUT
  prepare TAG ...      hash the built files and write the plugin's index entry
  verify ENTRY         download every file of an entry and check its size and SHA-256
  merge ENTRY          add an entry's version to plugins.json
  validate             check plugins.json and every manifest (CI)
  version PLUGIN       print a plugin's version (make tag)

serve.py, next to this file, uses this module for make serve.

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

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "plugins.json"
PLUGINS = ROOT / "plugins"
TAG_RE = re.compile(r"^(?P<dir>[a-z0-9][a-z0-9-]*?)-(?P<version>\d+\.\d+\.\d+)$")
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")
KINDS = ("library", "python")
REQUIRED = ("id", "name", "description", "author", "license", "kind", "min_app")
# Fields of a manifest copied to the plugin's entry in the index, and to each version.
PLUGIN_FIELDS = ("id", "name", "description", "author", "homepage", "license", "kind")
VERSION_FIELDS = ("min_app", "compatible_from", "sdk", "effects", "generators")
# What a plugin provides, as lists of display names (the names the code returns).
PROVIDES = ("effects", "generators")
PEP723_RE = re.compile(r"(?m)^# /// script\s*$\s(?P<content>(^#(| .*)$\s)+)^# ///$")


class Error(Exception):
    pass


def semver(v):
    return tuple(int(x) for x in v.split("."))


def compatible_from_errors(d):
    """Problems with the compatible_from of a manifest or an index version: the oldest version
    of the plugin whose saved settings and documents this version still reads (absent: every
    earlier version). Raised to the version itself by a release that breaks with the past."""
    c = d.get("compatible_from")
    if c is None:
        return []
    if not isinstance(c, str) or not VERSION_RE.match(c):
        return [f"compatible_from {c!r} is not X.Y.Z"]
    if VERSION_RE.match(d.get("version") or "") and semver(c) > semver(d["version"]):
        return [f"compatible_from {c} is later than the version itself"]
    return []


def inherited_compatible_from(index, plugin_id, version):
    """The compatible_from a version gets in the index when its manifest has none: the one of
    the latest released version before it, or the version itself for a first release."""
    earlier = [v for p in index["plugins"] if p["id"] == plugin_id for v in p["versions"]
               if semver(v["version"]) < semver(version)]
    if not earlier:
        return version
    return max(earlier, key=lambda v: semver(v["version"])).get("compatible_from", version)


def with_compatible_from(version, index, plugin_id):
    """version (a dict) with compatible_from filled in, in its place after min_app."""
    if "compatible_from" in version:
        return version
    out = {}
    for k, v in version.items():
        out[k] = v
        if k == "min_app":
            out["compatible_from"] = inherited_compatible_from(index, plugin_id, version["version"])
    out.setdefault("compatible_from", inherited_compatible_from(index, plugin_id, version["version"]))
    return out


def provides_errors(d):
    """Problems with the effects and generators lists of a manifest or an index version."""
    errors = []
    for k in PROVIDES:
        if k not in d:
            continue
        v = d[k]
        if not isinstance(v, list) or not v or not all(isinstance(s, str) and s.strip() for s in v):
            errors.append(f"{k} must be a non-empty list of non-empty strings")
        elif len(set(v)) != len(v):
            errors.append(f"{k} has a name twice")
    if not any(d.get(k) for k in PROVIDES):
        errors.append("needs at least one name in effects or generators")
    return errors


PY_CLASS_RE = re.compile(r"(?m)^class\s+\w+\s*\(\s*(Effect|Generator)\s*\)\s*:(?P<body>(?:\n(?:[ \t].*|[ \t]*))*)")
PY_NAME_RE = re.compile(r"(?m)^[ \t]+name\s*=\s*(\"[^\"\n]*\"|'[^'\n]*')")
RS_EXPORT_RE = re.compile(r"export_plugin!\s*\((?P<body>.*?)\)\s*;", re.S)
RS_NAME_RE = re.compile(r"fn\s+name\s*\(\s*&\s*self\s*\)\s*->\s*&\s*(?:'static\s+)?str\s*\{\s*\"([^\"\\]*)\"\s*\}")


def code_provides(folder, m):
    """The effect and generator names a plugin's source declares, read with regexes (no build):
    for Python the name of each Effect and Generator subclass, for Rust the fn name of each
    type in export_plugin!'s effects and generators."""
    found = {k: [] for k in PROVIDES}
    if m["kind"] == "python":
        src = (folder / m["script"]).read_text(encoding="utf-8")
        for c in PY_CLASS_RE.finditer(src):
            name = PY_NAME_RE.search(c["body"])
            if not name:
                raise Error(f"{folder.name}: a {c[1]} subclass in {m['script']} has no name = \"...\"")
            found["effects" if c[1] == "Effect" else "generators"].append(name[1][1:-1])
        return found
    src = "\n".join(p.read_text(encoding="utf-8") for p in sorted((folder / "src").rglob("*.rs")))
    export = RS_EXPORT_RE.search(src)
    if not export:
        raise Error(f"{folder.name}: no export_plugin!(...) found in src/")
    for k, trait in (("effects", "Effect"), ("generators", "Generator")):
        listed = re.search(rf"\b{k}\s*:\s*\[(?P<types>[^\]]*)\]", export["body"])
        for t in (listed["types"].split(",") if listed else []):
            t = t.strip()
            if not t:
                continue
            if not re.fullmatch(r"\w+", t):
                raise Error(f"{folder.name}: can't read {t!r} in export_plugin!'s {k}")
            impl = re.search(rf"(?m)^impl\s+{trait}\s+for\s+{t}\s*\{{(?P<rest>.*?)(?=^impl\b|\Z)", src, re.S)
            name = impl and RS_NAME_RE.search(impl["rest"])
            if not name:
                raise Error(f"{folder.name}: no literal fn name in impl {trait} for {t}")
            found[k].append(name[1])
    return found


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
    problems = provides_errors(m)
    if problems:
        raise Error(f"{folder.name}: {'; '.join(problems)}")
    if not VERSION_RE.match(m.get("version", "")):
        raise Error(f"{folder.name}: version {m.get('version')!r} is not X.Y.Z")
    problems = compatible_from_errors(m)
    if problems:
        raise Error(f"{folder.name}: {'; '.join(problems)}")
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


def sdk_abi(locked=True):
    """ABI_VERSION of the plugin SDK the workspace builds against."""
    meta = json.loads(subprocess.run(
        ["cargo", "metadata", "--format-version", "1"] + (["--locked"] if locked else []),
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


def plugin_entry(folder, m, files, changes=None, abi=None, index=None):
    """A plugin's entry in the index, with one version: the manifest's, released today, with
    the given files ({platform: {url, sha256, size}}). abi is the SDK's ABI version for a
    library, read from the SDK when not given. With an index, a compatible_from the manifest
    doesn't give is taken from it (merge does that for a release, against main's index)."""
    version = {"version": m["version"], "released": datetime.date.today().isoformat()}
    if m["kind"] == "library":
        version["abi"] = abi if abi is not None else sdk_abi()
    for k in VERSION_FIELDS:
        if m.get(k):
            version[k] = m[k]
    if changes:
        version["changes"] = changes
    if m["kind"] == "python":
        deps = pep723_dependencies(folder / m["script"])
        if deps:
            version["dependencies"] = deps
    version["files"] = files
    entry = {k: m[k] for k in PLUGIN_FIELDS if m.get(k)}
    entry["latest"] = m["version"]
    entry["versions"] = [with_compatible_from(version, index, m["id"]) if index else version]
    return entry


def cmd_prepare(args):
    folder, m = parse_tag(args.tag)
    assets = Path(args.assets)
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
    changes = tag_message(args.tag)
    entry = plugin_entry(folder, m, files, changes)
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
    new = with_compatible_from(entry["versions"][0], index, entry["id"])
    plugin = next((p for p in index["plugins"] if p["id"] == entry["id"]), None)
    if plugin is None:
        plugin = {"versions": []}
        index["plugins"].append(plugin)
    if any(v["version"] == new["version"] for v in plugin["versions"]):
        raise Error(f"{entry['id']} {new['version']} is already in plugins.json")
    versions = sorted(plugin["versions"] + [new], key=lambda v: semver(v["version"]), reverse=True)
    # The plugin's details follow its latest release; versions keep their own.
    plugin.clear()
    plugin.update({k: v for k, v in entry.items() if k not in ("latest", "versions")})
    plugin["latest"] = versions[0]["version"]
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
            m = load_plugin(folder)
            code = code_provides(folder, m)
            for k in PROVIDES:
                declared, actual = set(m.get(k, [])), set(code[k])
                if declared != actual:
                    errors.append(f"{folder.name}: plugin.json {k} {sorted(declared)} don't match the code's {sorted(actual)}")
        except (Error, OSError, ValueError, KeyError) as e:
            errors.append(str(e))
    for folder in PLUGINS.iterdir():
        if folder.is_dir() and not folder.name.startswith(".") and not (folder / "plugin.json").is_file():
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
            if not v.get("compatible_from"):
                errors.append(f"{where} has no compatible_from")
            errors += [f"{where}: {e}" for e in provides_errors(v) + compatible_from_errors(v)]
            if v.get("abi") == 1 and "generators" in v:
                errors.append(f"{where}: ABI 1 has no generators")
            for platform, f in v.get("files", {}).items():
                tag = f"{pid}-{v.get('version')}"
                if not re.fullmatch(r"https://github\.com/[^/]+/[^/]+/releases/download/" + re.escape(tag) + r"/[^/]+", f.get("url", "")):
                    errors.append(f"{where} {platform}: url is not a release asset of {tag}")
                if not re.fullmatch(r"[0-9a-f]{64}", f.get("sha256", "")):
                    errors.append(f"{where} {platform}: bad sha256")
                if not isinstance(f.get("size"), int) or f["size"] <= 0:
                    errors.append(f"{where} {platform}: bad size")
        try:
            newest = max((v["version"] for v in p.get("versions", [])), key=semver, default=None)
        except (KeyError, ValueError, AttributeError, TypeError):
            newest = None
        if newest and p.get("latest") != newest:
            errors.append(f"plugins.json: {pid}: latest is {p.get('latest')!r}, but its latest version is {newest}")
        # A break stays a break: a later version can't claim to read what an earlier one couldn't.
        try:
            ordered = sorted(p.get("versions", []), key=lambda v: semver(v["version"]))
        except (KeyError, ValueError, AttributeError):
            ordered = []
        floor = None
        for v in ordered:
            c = v.get("compatible_from")
            if c is None or not VERSION_RE.match(str(c)):
                c = floor
            elif floor and semver(c) < semver(floor):
                errors.append(f"plugins.json: {pid} {v['version']}: compatible_from {c} is older than {floor}, set by an earlier version")
                c = floor
            floor = c
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

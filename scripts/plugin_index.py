#!/usr/bin/env python3
"""The plugin index (plugins.json) and the releases it points to.

Each plugin is a folder of plugins/ with a plugin.json manifest (id, name, description, author,
homepage, license, kind, optionally engines and compatible_from, and effects and/or generators:
the display names of what it provides; for a Python plugin also version and script).
engines says what the plugin needs of the app, as version requirements: {"app": ">=0.17.0",
"sdk": ">=0.4.0"}; a Python plugin gives "sdk", a library none (its ABI version says it).
A release is a tag <folder>-<version>; the Release workflow uses these commands:

  resolve TAG          check the tag against the plugin and print what to build, as
                       key=value lines for $GITHUB_OUTPUT
  prepare TAG ...      hash the built files and write the plugin's index entry
  verify ENTRY         download every file of an entry and check its size and SHA-256
  unpublished TAG      fail if the tag's GitHub Release is already published
  publish TAG ... FILE...  put the built files on the tag's GitHub Release (gh), then publish it
  merge ENTRY          add an entry's version to plugins.json
  pull-request TAG ENTRY ...  merge, validate and commit the entry on its own branch, push
                       it and open a pull request for it (git, gh)
  validate             check plugins.json and every manifest (CI)
  version PLUGIN       print a plugin's version (make tag)
  dependencies         print the Python plugins' dependencies, one per line (pip install)

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
REQUIRED = ("id", "name", "description", "author", "license", "kind")
# The newest SDK of the apps that don't read engines (0.16.x, which only read min_app,
# written from engines.app): a Python plugin needing a later one needs an engines.app, or
# they would offer it.
UNCHECKED_SDK = "0.3.0"
# What engines may name: the app and its plugin SDK.
ENGINES = ("app", "sdk")
# A clause of a version requirement: the subset of Cargo's syntax the app and this script
# read the same way.
REQ_CLAUSE_RE = re.compile(r"^(>=|<=|>|<|=)\s*(\d+\.\d+\.\d+)$")
# Fields of a manifest copied to the plugin's entry in the index, and to each version.
PLUGIN_FIELDS = ("id", "name", "description", "author", "homepage", "license", "kind")
VERSION_FIELDS = ("engines", "compatible_from", "effects", "generators")
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
    earlier = [
        v
        for p in index["plugins"]
        if p["id"] == plugin_id
        for v in p["versions"]
        if semver(v["version"]) < semver(version)
    ]
    if not earlier:
        return version
    return max(earlier, key=lambda v: semver(v["version"])).get("compatible_from", version)


def with_compatible_from(version, index, plugin_id):
    """version (a dict) with compatible_from filled in, in its place after min_app and engines."""
    if "compatible_from" in version:
        return version
    after = [k for k in version if k in ("min_app", "engines")]
    out = {}
    for k, v in version.items():
        out[k] = v
        if after and k == after[-1]:
            out["compatible_from"] = inherited_compatible_from(index, plugin_id, version["version"])
    out.setdefault("compatible_from", inherited_compatible_from(index, plugin_id, version["version"]))
    return out


def requirement(text):
    """The clauses (operator, version) of a version requirement in Cargo's syntax, as the app
    reads it, limited to >=, >, <=, < and = before X.Y.Z, joined by commas: ">=0.4.0, <2.0.0"."""
    if not isinstance(text, str) or not text.strip():
        raise Error(f"{text!r} is not a version requirement")
    clauses = []
    for part in text.split(","):
        c = REQ_CLAUSE_RE.match(part.strip())
        if not c:
            raise Error(f"{text!r} is not a version requirement: >=, >, <=, < or = before X.Y.Z, joined by commas")
        clauses.append((c[1], c[2]))
    return clauses


def lower_bound(text):
    """The version a requirement starts at (its >= or =), or None."""
    return max((v for op, v in requirement(text) if op in (">=", "=")), key=semver, default=None)


def engines_errors(engines, kind):
    """Problems with the engines of a manifest or an index version."""
    if not isinstance(engines, dict) or not engines:
        return ["engines must be an object naming app and/or sdk"]
    errors = [f"engines.{k}: unknown, use {' or '.join(ENGINES)}" for k in engines if k not in ENGINES]
    for k, req in engines.items():
        try:
            requirement(req)
        except Error as e:
            errors.append(f"engines.{k}: {e}")
    if kind == "library" and "sdk" in engines:
        errors.append("engines.sdk: a library's SDK is checked through its ABI version")
    return errors


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
PY_PLUGIN_RE = re.compile(r"\bPlugin\(\s*(\"[^\"\n]*\"|'[^'\n]*')\s*,\s*(\"[^\"\n]*\"|'[^'\n]*')")
RS_EXPORT_RE = re.compile(r"export_plugin!\s*\((?P<body>.*?)\)\s*;", re.S)
RS_NAME_RE = re.compile(r"fn\s+name\s*\(\s*&\s*self\s*\)\s*->\s*&\s*(?:'static\s+)?str\s*\{\s*\"([^\"\\]*)\"\s*\}")


def code_provides(folder, m):
    """The effect and generator names a plugin's source declares, read with regexes (no build):
    for Python the name of each Effect and Generator subclass, for Rust the fn name of each
    type in export_plugin!'s effects and generators."""
    found: dict[str, list[str]] = {k: [] for k in PROVIDES}
    if m["kind"] == "python":
        src = script_path(folder, m).read_text(encoding="utf-8")
        for c in PY_CLASS_RE.finditer(src):
            name = PY_NAME_RE.search(c["body"])
            if not name:
                raise Error(f'{folder.name}: a {c[1]} subclass in {m["script"]} has no name = "..."')
            found["effects" if c[1] == "Effect" else "generators"].append(name[1][1:-1])
        return found
    src = "\n".join(p.read_text(encoding="utf-8") for p in sorted((folder / "src").rglob("*.rs")))
    export = RS_EXPORT_RE.search(src)
    if not export:
        raise Error(f"{folder.name}: no export_plugin!(...) found in src/")
    for k, trait in (("effects", "Effect"), ("generators", "Generator")):
        listed = re.search(rf"\b{k}\s*:\s*\[(?P<types>[^\]]*)\]", export["body"])
        for listed_type in listed["types"].split(",") if listed else []:
            t = listed_type.strip()
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


def code_identity(folder, m):
    """The name and version a plugin's code gives itself, which the app shows once it is
    loaded, read with regexes: for Python the literal strings passed to Plugin(name, version,
    ...), for Rust those of export_plugin!'s name and version (None for the version when it is
    env!("CARGO_PKG_VERSION"), the Cargo.toml version, which is the manifest's)."""
    if m["kind"] == "python":
        found = PY_PLUGIN_RE.search(script_path(folder, m).read_text(encoding="utf-8"))
        if not found:
            raise Error(f'{folder.name}: no Plugin("name", "version", ...) with literal strings in {m["script"]}')
        return {"name": found[1][1:-1], "version": found[2][1:-1]}
    src = "\n".join(p.read_text(encoding="utf-8") for p in sorted((folder / "src").rglob("*.rs")))
    export = RS_EXPORT_RE.search(src)
    if not export:
        raise Error(f"{folder.name}: no export_plugin!(...) found in src/")
    name = re.search(r'\bname\s*:\s*"([^"\\]*)"', export["body"])
    version = re.search(r'\bversion\s*:\s*(?:"([^"\\]*)"|(env!\s*\(\s*"CARGO_PKG_VERSION"\s*\)))', export["body"])
    if not name or not version:
        raise Error(f'{folder.name}: export_plugin! needs name: "..." and version: env!("CARGO_PKG_VERSION") or "..."')
    return {"name": name[1], "version": version[1]}


def identity_errors(folder, m, code):
    """Where the name and version the code gives itself differ from the manifest's."""
    where = m["script"] if m["kind"] == "python" else "export_plugin!"
    errors = []
    for k in ("name", "version"):
        if code[k] is not None and code[k] != m[k]:
            errors.append(f"{folder.name}: {where} has {k} {code[k]!r}, plugin.json has {m[k]!r}")
    return errors


def index_errors(m, p):
    """Where a manifest disagrees with its plugin's entry in the index, p. Its details are
    copied there by each release: a manifest at the latest released version must have the
    same, and none can be older."""
    try:
        if semver(m["version"]) < semver(p["latest"]):
            return [f"{m['id']}: plugin.json has version {m['version']}, older than the latest release {p['latest']}"]
    except (KeyError, ValueError, AttributeError, TypeError):
        return []
    if m["version"] != p["latest"]:
        return []
    return [
        f"{m['id']}: plugin.json {k} {m.get(k)!r} differs from plugins.json's {p.get(k)!r}: "
        "release a new version to change it"
        for k in PLUGIN_FIELDS
        if m.get(k) != p.get(k)
    ]


def script_path(folder, m):
    """A Python plugin's script: only the file name of the manifest's script, in `folder`
    (load_plugin also refuses any other)."""
    return folder / Path(m["script"]).name


def plugin_dirs():
    return sorted(p.parent for p in PLUGINS.glob("*/plugin.json"))


def load_plugin(folder):
    """The manifest of a plugin folder, checked, with version and files filled in."""
    folder = Path(folder)
    path = folder / "plugin.json"
    if not path.is_file():
        raise Error(f"{folder.name}: no plugin.json")
    m = json.loads(path.read_text(encoding="utf-8"))
    if "compat_from" in m:
        raise Error(f"{path.name} of {folder.name}: compat_from is spelled compatible_from")
    for old in ("min_app", "min_sdk", "sdk"):
        if old in m:
            raise Error(f'{path.name} of {folder.name}: {old} is now in engines, e.g. "engines": {{"app": ">=0.17.0"}}')
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
        # A file name in the plugin's folder: never a path elsewhere.
        if not isinstance(script, str) or script != Path(script).name or not script.endswith(".py"):
            raise Error(f"{folder.name}: script {script!r} must be the name of a .py file in its folder")
        if not script_path(folder, m).is_file():
            raise Error(f"{folder.name}: script {script!r} not found")
        m["files"] = {"any": script}
        try:
            deps = pep723_dependencies(script_path(folder, m))
        except tomllib.TOMLDecodeError as e:
            raise Error(f"{folder.name}: the PEP 723 block of {script} isn't TOML: {e}") from e
        if not isinstance(deps, list) or not all(isinstance(d, str) and d.strip() for d in deps):
            raise Error(f"{folder.name}: dependencies in {script} must be a list of requirement strings")
    problems = provides_errors(m)
    if problems:
        raise Error(f"{folder.name}: {'; '.join(problems)}")
    if not VERSION_RE.match(m.get("version", "")):
        raise Error(f"{folder.name}: version {m.get('version')!r} is not X.Y.Z")
    problems = compatible_from_errors(m)
    if problems:
        raise Error(f"{folder.name}: {'; '.join(problems)}")
    engines = m.get("engines")
    if engines is not None:
        problems = engines_errors(engines, m["kind"])
        if problems:
            raise Error(f"{folder.name}: {'; '.join(problems)}")
    if m["kind"] == "python":
        sdk = (engines or {}).get("sdk")
        if sdk is None:
            raise Error(f'{folder.name}: a Python plugin needs engines.sdk, e.g. "engines": {{"sdk": ">=0.3.0"}}')
        start = lower_bound(sdk)
        if start is None:
            raise Error(f"{folder.name}: engines.sdk {sdk!r} needs a >= bound")
        app = engines.get("app")
        if semver(start) > semver(UNCHECKED_SDK) and not (app and lower_bound(app)):
            raise Error(
                f"{folder.name}: engines.sdk {sdk!r} needs an engines.app >= the app release that ships it: "
                f"apps for SDK {UNCHECKED_SDK} and before read only the min_app written from it"
            )
    return m


def parse_tag(tag):
    t = TAG_RE.match(tag)
    if not t:
        raise Error(f"tag {tag!r} is not <plugin>-<X.Y.Z>")
    # The folder name may itself end in -<digits>; take the longest folder that exists.
    for folder in sorted(plugin_dirs(), key=lambda p: -len(p.name)):
        if tag.startswith(folder.name + "-") and VERSION_RE.match(tag[len(folder.name) + 1 :]):
            m = load_plugin(folder)
            version = tag[len(folder.name) + 1 :]
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


def sdk_abi(package, locked=True):
    """ABI_VERSION of the plugin SDK the Rust plugin `package` builds against: each plugin
    takes its own, so two in the workspace may differ."""
    meta = json.loads(
        subprocess.run(
            ["cargo", "metadata", "--format-version", "1"] + (["--locked"] if locked else []),
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    )
    packages = {p["id"]: p for p in meta["packages"]}
    name = lambda pkg: packages.get(pkg, {}).get("name")  # noqa: E731
    nodes = (meta.get("resolve") or {}).get("nodes", [])
    node = next((n for n in nodes if name(n["id"]) == package), None)
    sdk = next((d["pkg"] for d in (node or {}).get("deps", []) if name(d["pkg"]) == "artwork-plugin-sdk"), None)
    if sdk is None:
        raise Error(f"{package} doesn't depend on artwork-plugin-sdk")
    abi = Path(packages[sdk]["manifest_path"]).parent / "src" / "abi.rs"
    found = re.search(r"pub const ABI_VERSION: u32 = (\d+);", abi.read_text(encoding="utf-8"))
    if not found:
        raise Error(f"ABI_VERSION of artwork-plugin-sdk not found in {abi}")
    return int(found[1])


def tag_message(tag):
    """The message of an annotated tag (the version's changes), or None."""

    def git(*a):
        return subprocess.run(["git", *a], cwd=ROOT, capture_output=True, text=True, check=False).stdout.strip()

    if git("cat-file", "-t", f"refs/tags/{tag}") != "tag":
        return None
    text = git("tag", "-l", "--format=%(contents:subject)%0a%0a%(contents:body)", tag).strip()
    return text or None


def pep723_dependencies(script):
    """Dependencies from the PEP 723 block of a Python plugin, if it has one."""
    found = PEP723_RE.search(script.read_text(encoding="utf-8"))
    if not found:
        return []
    toml = "".join(
        line[2:] if line.startswith("# ") else line[1:] for line in found["content"].splitlines(keepends=True)
    )
    return tomllib.loads(toml).get("dependencies", [])


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
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
        version["abi"] = abi if abi is not None else sdk_abi(m["package"])
    app = (m.get("engines") or {}).get("app")
    if app and lower_bound(app):
        # For the apps before engines (0.16), which read only this.
        version["min_app"] = lower_bound(app)
    for k in VERSION_FIELDS:
        if m.get(k):
            version[k] = m[k]
    if changes:
        version["changes"] = changes
    if m["kind"] == "python":
        deps = pep723_dependencies(script_path(folder, m))
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
                    raise Error(f"{f['url']}: {e}") from e
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
    INDEX.write_text(json.dumps(index, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")  # NOSONAR
    print(f"added {entry['id']} {new['version']} to plugins.json")
    return entry


def run(*cmd, capture=False, check=True):
    """Runs a command (git, gh) in the repository; its output, stripped, when `capture`."""
    try:
        r = subprocess.run(list(cmd), cwd=ROOT, check=check, text=True, capture_output=capture)
    except subprocess.CalledProcessError as e:
        raise Error(f"{' '.join(cmd[:3])} failed (exit {e.returncode}): {(e.stderr or '').strip()}") from e
    return (r.stdout or "").strip() if capture else ""


def release_draft(tag):
    """Whether the GitHub Release of `tag` is a draft: True, False when published, None
    when there is none."""
    answer = run("gh", "release", "view", tag, "--json", "isDraft", "--jq", ".isDraft", capture=True, check=False)
    return {"true": True, "false": False}.get(answer)


def cmd_unpublished(args):
    if release_draft(args.tag) is False:
        raise Error(f"Release {args.tag} is already published; release a new version instead.")


def cmd_publish(args):
    """Files go on a draft, published once they are all there: with release immutability on,
    a published release takes no more files. The files and the notes are only handed to gh,
    never opened here."""
    if release_draft(args.tag):
        run("gh", "release", "delete", args.tag, "--yes")  # a draft left by a failed run; the tag stays
    run("gh", "release", "create", args.tag, "--draft", "--verify-tag", "--latest=false",
        "--title", args.title, "--notes-file", args.notes)  # fmt: skip
    run("gh", "release", "upload", args.tag, *args.files)
    run("gh", "release", "edit", args.tag, "--draft=false", "--latest=false")
    print(f"published {args.tag} with {len(args.files)} file(s)")


def pr_body(tag, repo, entry):
    """The description of a release's index pull request: a link to it and its entry."""
    url = f"https://github.com/{repo}/releases/tag/{tag}"
    text = json.dumps(entry, indent=2, ensure_ascii=False)
    return f"Adds release [{tag}]({url}) to plugins.json.\n\n```json\n{text}\n```\n"


def cmd_pull_request(args):
    """The entry merged into plugins.json and validated on the branch args.branch, made from the
    checked-out default branch, force-pushed (a re-run replaces the branch an earlier one left),
    and a pull request to args.base, unless one is open for that branch already."""
    run("git", "config", "user.name", "github-actions[bot]")
    run("git", "config", "user.email", "41898282+github-actions[bot]@users.noreply.github.com")
    run("git", "switch", "-c", args.branch)
    entry = cmd_merge(argparse.Namespace(entry=args.entry))
    cmd_validate(argparse.Namespace())
    run("git", "commit", "-am", f"Index {args.tag}")
    run("git", "push", "--force", "origin", f"HEAD:refs/heads/{args.branch}")
    opened = run("gh", "pr", "list", "--head", args.branch, "--state", "open",
                 "--json", "number", "--jq", ".[].number", capture=True)  # fmt: skip
    if opened:
        print(f"A pull request for {args.branch} is already open (#{opened}); its branch was updated.")
        return
    # The body as an argument: no file is written for it.
    run("gh", "pr", "create", "--base", args.base, "--head", args.branch,
        "--title", f"Index {args.tag}", "--body", pr_body(args.tag, args.repo, entry))  # fmt: skip


def cmd_dependencies(args):
    """Every dependency of the Python plugins, once, as pip install takes them."""
    seen = []
    for folder in plugin_dirs():
        m = load_plugin(folder)
        if m["kind"] == "python":
            seen += [d for d in pep723_dependencies(script_path(folder, m)) if d not in seen]
    for d in seen:
        print(d)


def cmd_version(args):
    print(load_plugin(PLUGINS / args.plugin)["version"])


def cmd_validate(args):
    errors = []
    manifests = {}
    for folder in plugin_dirs():
        try:
            m = load_plugin(folder)
            manifests[m["id"]] = m
            code = code_provides(folder, m)
            for k in PROVIDES:
                declared, actual = set(m.get(k, [])), set(code[k])
                if declared != actual:
                    errors.append(
                        f"{folder.name}: plugin.json {k} {sorted(declared)} don't match the code's {sorted(actual)}"
                    )
            errors += identity_errors(folder, m, code_identity(folder, m))
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
        if pid in manifests:
            errors += index_errors(manifests[pid], p)
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
            if "engines" in v:
                errors += [f"{where}: {e}" for e in engines_errors(v["engines"], p.get("kind"))]
            deps = v.get("dependencies", [])
            if not isinstance(deps, list) or not all(isinstance(d, str) and d.strip() for d in deps):
                errors.append(f"{where}: dependencies must be a list of requirement strings")
            if v.get("abi") == 1 and "generators" in v:
                errors.append(f"{where}: ABI 1 has no generators")
            for platform, f in v.get("files", {}).items():
                tag = f"{pid}-{v.get('version')}"
                if not re.fullmatch(
                    r"https://github\.com/[^/]+/[^/]+/releases/download/" + re.escape(tag) + r"/[^/]+", f.get("url", "")
                ):
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
                errors.append(
                    f"plugins.json: {pid} {v['version']}: compatible_from {c} is older than {floor}, "
                    "set by an earlier version"
                )
                c = floor
            floor = c
    for problem in errors:
        print(f"::error::{problem}")
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
    s = sub.add_parser("unpublished")
    s.add_argument("tag")
    s.set_defaults(fn=cmd_unpublished)
    s = sub.add_parser("publish")
    s.add_argument("tag")
    s.add_argument("--notes", required=True, help="release notes (from prepare)")
    s.add_argument("--title", required=True, help="the release's title")
    s.add_argument("files", nargs="+", help="the files to publish")
    s.set_defaults(fn=cmd_publish)
    s = sub.add_parser("merge")
    s.add_argument("entry")
    s.set_defaults(fn=cmd_merge)
    s = sub.add_parser("pull-request")
    s.add_argument("tag")
    s.add_argument("entry")
    s.add_argument("--base", required=True, help="the branch to merge into (the default branch)")
    s.add_argument("--branch", required=True, help="the branch to commit on, made from the checked-out one")
    s.add_argument("--repo", required=True, help="OWNER/REPO, for the release's link")
    s.set_defaults(fn=cmd_pull_request)
    s = sub.add_parser("version")
    s.add_argument("plugin")
    s.set_defaults(fn=cmd_version)
    s = sub.add_parser("validate")
    s.set_defaults(fn=cmd_validate)
    s = sub.add_parser("dependencies")
    s.set_defaults(fn=cmd_dependencies)
    args = ap.parse_args()
    try:
        args.fn(args)
    except Error as e:
        print(f"::error::{e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

"""A throwaway plugin repository for the tests: plugin folders, a Cargo.toml workspace and
a plugins.json in a temporary folder, with plugin_index pointed at it."""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import plugin_index  # noqa: E402

PY_SCRIPT = """\
from artwork_plugin_sdk import Effect, Generator, Plugin

class Invert(Effect):
    id = "demo.invert"
    name = "Invert"

class Noise(Generator):
    id = "demo.noise"
    name = "Noise"

plugin = Plugin("Demo", "1.0", effects=[Invert()], generators=[Noise()])
"""

RS_SOURCE = """\
use artwork_plugin_sdk::{Effect, Generator, export_plugin};

struct Blur;
impl Effect for Blur {
    fn name(&self) -> &str {
        "Blur"
    }
}

struct Grid;
impl Generator for Grid {
    fn name(&self) -> &'static str { "Grid" }
}

export_plugin!(
    name: "Rusty",
    version: env!("CARGO_PKG_VERSION"),
    effects: [Blur],
    generators: [Grid],
);
"""


def manifest(id, kind="python", **extra):
    m = {
        "id": id,
        "name": id.title(),
        "description": f"The {id} plugin",
        "author": "tester",
        "homepage": f"https://example.com/{id}",
        "license": "MIT",
        "kind": kind,
    }
    if kind == "python":
        m.update(
            version="1.0.0",
            script=f"{id.replace('-', '_')}.py",
            engines={"sdk": ">=0.3.0"},
            effects=["Invert"],
            generators=["Noise"],
        )
    else:
        m.update(effects=["Blur"], generators=["Grid"])
    m.update(extra)
    return {k: v for k, v in m.items() if v is not None}


def release_version(id, version, **extra):
    """A version as the index has it, with files on the GitHub Release of its tag."""
    tag = f"{id}-{version}"
    v = {
        "version": version,
        "released": "2026-01-01",
        "min_app": "0.16.0",
        "compatible_from": version,
        "effects": ["Invert"],
        "files": {
            "any": {"url": f"https://github.com/o/r/releases/download/{tag}/{id}.py", "sha256": "0" * 64, "size": 10}
        },
    }
    v.update(extra)
    return {k: x for k, x in v.items() if x is not None}


class RepoTestCase(unittest.TestCase):
    """Each test gets an empty repository at self.root, which plugin_index works on."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        (self.root / "plugins").mkdir()
        self.write("Cargo.toml", '[workspace]\nresolver = "3"\nmembers = []\n')
        self.write_index([])
        for name, value in (
            ("ROOT", self.root),
            ("PLUGINS", self.root / "plugins"),
            ("INDEX", self.root / "plugins.json"),
        ):
            patcher = mock.patch.object(plugin_index, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def write(self, path, text):
        p = self.root / path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        return p

    def write_index(self, plugins):
        self.write("plugins.json", json.dumps({"format": 1, "name": "Test", "plugins": plugins}, indent=2))

    def read_index(self):
        return json.loads((self.root / "plugins.json").read_text(encoding="utf-8"))

    def add_python(self, id="demo", script=PY_SCRIPT, **extra):
        m = manifest(id, **extra)
        folder = self.root / "plugins" / id
        self.write(f"plugins/{id}/plugin.json", json.dumps(m))
        if script is not None and m.get("script"):
            self.write(f"plugins/{id}/{m['script']}", script)
        return folder

    def add_rust(self, id="rusty", version="0.2.0", package=None, lib=None, source=RS_SOURCE, member=True, **extra):
        folder = self.root / "plugins" / id
        self.write(f"plugins/{id}/plugin.json", json.dumps(manifest(id, kind="library", **extra)))
        cargo = f'[package]\nname = "{package or id}"\nversion = "{version}"\nedition = "2024"\n'
        if lib:
            cargo += f'\n[lib]\nname = "{lib}"\ncrate-type = ["cdylib"]\n'
        self.write(f"plugins/{id}/Cargo.toml", cargo)
        self.write(f"plugins/{id}/src/lib.rs", source)
        if member:
            members = [f"plugins/{p.parent.name}" for p in sorted((self.root / "plugins").glob("*/Cargo.toml"))]
            self.write("Cargo.toml", f'[workspace]\nresolver = "3"\nmembers = {json.dumps(members)}\n')
        return folder

"""Collects the Python plugins' own tests (plugins/<plugin>/test_*.py, next to each plugin's
script) into this test run, so make test-python runs them with the scripts' tests: the
plugin folders aren't packages (swap-channels can't be a module name), so unittest's
discovery can't reach them. Also checks what holds across the plugins."""

import importlib.util
import json
import unittest

from tests.plugin_testing import load_plugin
from tests.repo import ROOT

PLUGINS = ROOT / "plugins"


def plugin_test_files():
    return sorted(PLUGINS.glob("*/test_*.py"))


def load_tests(loader, tests, pattern):
    for path in plugin_test_files():
        name = f"plugin_tests.{path.parent.name.replace('-', '_')}.{path.stem}"
        spec = importlib.util.spec_from_file_location(name, path)
        assert spec and spec.loader, path
        module = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(module)
        except unittest.SkipTest as e:
            # A plugin whose dependency isn't installed (tests/plugin_testing.py).
            tests.addTest(skipped(name, str(e)))
            continue
        tests.addTests(loader.loadTestsFromModule(module))
    return tests


def skipped(name, reason):
    def test():
        raise unittest.SkipTest(reason)

    return unittest.FunctionTestCase(test, description=name)


def python_plugins():
    """(folder, manifest) of every Python plugin."""
    for manifest in sorted(PLUGINS.glob("*/plugin.json")):
        m = json.loads(manifest.read_text(encoding="utf-8"))
        if m.get("kind") == "python":
            yield manifest.parent, m


class PluginsTest(unittest.TestCase):
    def test_every_python_plugin_has_tests(self):
        for folder, _ in python_plugins():
            self.assertTrue(list(folder.glob("test_*.py")), f"plugins/{folder.name} has no test_*.py")

    def test_ids_are_unique(self):
        ids = []
        for folder, m in python_plugins():
            try:
                plugin = load_plugin(folder / m["script"]).plugin
            except unittest.SkipTest:
                continue
            ids += [x.id for x in plugin.effects + plugin.generators]
        self.assertEqual(len(ids), len(set(ids)), ids)

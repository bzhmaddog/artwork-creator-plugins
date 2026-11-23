"""What the Python plugins' tests (plugins/*/test_*.py) share: loading a plugin's script,
and images to run it on. The plugins run against artwork_plugin_sdk when it can be
imported (the app's Python SDK), and otherwise against a small stand-in with the same
names, enough for the plugins' code: an image is RGBA bytes, premultiplied, in
image.pixels, and values are the parameters' values by key."""

import importlib.util
import sys
import types
from pathlib import Path


def stand_in_sdk():
    sdk = types.ModuleType("artwork_plugin_sdk")

    class Effect:
        pass

    class Generator:
        pass

    class Plugin:
        def __init__(self, name, version, effects=(), generators=()):
            self.name, self.version = name, version
            self.effects, self.generators = list(effects), list(generators)

    def param(kind):
        return lambda key, label, *a, **kw: {"kind": kind, "key": key, "label": label, "args": a, **kw}

    def color(value):
        """[r, g, b, a] from "#rrggbbaa"."""
        return list(bytes.fromhex(value.lstrip("#")))

    vars(sdk).update(Effect=Effect, Generator=Generator, Plugin=Plugin, color=color)
    for kind in ("int", "float", "color", "choice", "bool"):
        setattr(sdk, f"{kind}_param", param(kind))
    return sdk


def load_plugin(path):
    """The module of a plugin's script, with the SDK (or its stand-in) importable."""
    if "artwork_plugin_sdk" not in sys.modules and importlib.util.find_spec("artwork_plugin_sdk") is None:
        sys.modules["artwork_plugin_sdk"] = stand_in_sdk()
    path = Path(path)
    spec = importlib.util.spec_from_file_location(f"plugin_{path.stem}", path)
    assert spec and spec.loader, path
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Image:
    def __init__(self, width, height, pixels=None):
        self.width, self.height = width, height
        self.pixels = bytearray(pixels if pixels is not None else bytes(width * height * 4))

    def pixel(self, x, y):
        i = (y * self.width + x) * 4
        return tuple(self.pixels[i : i + 4])


def gradient(width=64, height=4, alpha=255):
    """Every channel value once per row, with a constant alpha."""
    px = bytearray()
    for y in range(height):
        for x in range(width):
            v = (x * 4 + y) % 256
            px += bytes((v, 255 - v, (v * 7) % 256, alpha))
    return Image(width, height, px)

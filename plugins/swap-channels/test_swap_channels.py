"""Tests of the Swap channels effect (swap_channels.py). Run with the other tests: make
test-python, from the repository's root."""

import unittest
from pathlib import Path

from tests.plugin_testing import Image, gradient, load_plugin

swap_channels = load_plugin(Path(__file__).with_name("swap_channels.py"))


class DeclaredTest(unittest.TestCase):
    def test_names(self):
        self.assertEqual([e.name for e in swap_channels.plugin.effects], ["Swap channels"])

    def test_leaves_strokes_out(self):
        self.assertTrue(swap_channels.SwapChannels.fill_only)


class SwapChannelsTest(unittest.TestCase):
    def test_pairs(self):
        expected = {"red-blue": (3, 2, 1, 4), "red-green": (2, 1, 3, 4), "green-blue": (1, 3, 2, 4)}
        for pair, px in expected.items():
            img = Image(2, 1, bytes((1, 2, 3, 4)) * 2)
            swap_channels.SwapChannels().apply(img, {"pair": pair}, 1.0)
            self.assertEqual((img.pixel(0, 0), img.pixel(1, 0)), (px, px), pair)

    def test_twice_is_identity(self):
        img = gradient()
        before = bytes(img.pixels)
        for _ in range(2):
            swap_channels.SwapChannels().apply(img, {"pair": "green-blue"}, 1.0)
        self.assertEqual(bytes(img.pixels), before)


if __name__ == "__main__":
    unittest.main()

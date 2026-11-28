"""Tests of the Posterize effect (posterize.py). Run with the other
tests: make test-python, from the repository's root."""

import unittest
from pathlib import Path

from tests.plugin_testing import Image, gradient, load_plugin

posterize = load_plugin(Path(__file__).with_name("posterize.py"))


class DeclaredTest(unittest.TestCase):
    def test_names(self):
        self.assertEqual([e.name for e in posterize.plugin.effects], ["Posterize"])
        self.assertEqual(posterize.plugin.generators, [])


class PosterizeTest(unittest.TestCase):
    def apply(self, img, levels):
        posterize.Posterize().apply(img, {"levels": levels}, 1.0)
        return img

    def test_levels(self):
        for levels in (2, 3, 4, 5, 32):
            step = 255 / (levels - 1)
            allowed = {round(k * step) for k in range(levels)}
            img = self.apply(gradient(), levels)
            colors = {v for i, v in enumerate(img.pixels) if i % 4 != 3}
            self.assertEqual(colors, allowed, levels)

    def test_two_levels_threshold_at_half(self):
        img = self.apply(Image(4, 1, bytes((0, 127, 128, 255) * 4)), 2)
        self.assertEqual(img.pixel(0, 0), (0, 0, 255, 255))

    def test_alpha_kept(self):
        img = gradient(alpha=77)
        self.apply(img, 3)
        self.assertEqual(set(img.pixels[3::4]), {77})

    def test_nearest_level(self):
        img = self.apply(Image(1, 1, bytes((40, 43, 200, 255))), 4)
        self.assertEqual(img.pixel(0, 0), (0, 85, 170, 255))


if __name__ == "__main__":
    unittest.main()

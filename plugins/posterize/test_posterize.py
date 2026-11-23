"""Tests of the Posterize effect and the Bands generator (posterize.py). Run with the other
tests: make test-python, from the repository's root."""

import math
import unittest
from pathlib import Path

from tests.plugin_testing import Image, gradient, load_plugin

posterize = load_plugin(Path(__file__).with_name("posterize.py"))


class DeclaredTest(unittest.TestCase):
    def test_names(self):
        self.assertEqual([e.name for e in posterize.plugin.effects], ["Posterize"])
        self.assertEqual([g.name for g in posterize.plugin.generators], ["Bands"])


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


class BandsTest(unittest.TestCase):
    FIRST, SECOND = "#1d3557ff", "#f1faeeff"

    def generate(self, width, height, band_mm, angle, px_per_mm=1.0):
        img = Image(width, height)
        values = {"width": band_mm, "angle": angle, "first": self.FIRST, "second": self.SECOND}
        posterize.Bands().generate(img, values, px_per_mm)
        return img

    def expected(self, x, y, band, angle):
        """Band of pixel (x, y), from its center: 0 for the first color."""
        t = math.radians(angle)
        return math.floor(((x + 0.5) * math.sin(t) + (y + 0.5) * math.cos(t)) / band) % 2

    def colors(self):
        return [tuple(bytes.fromhex(c[1:])) for c in (self.FIRST, self.SECOND)]

    def test_fills_the_image(self):
        for w, h in ((1, 1), (7, 3), (40, 25)):
            self.assertEqual(len(self.generate(w, h, 3, 30).pixels), w * h * 4)

    def test_horizontal(self):
        img = self.generate(10, 20, 5, 0)
        first, second = self.colors()
        for y in range(20):
            row = {img.pixel(x, y) for x in range(10)}
            self.assertEqual(row, {first if (y // 5) % 2 == 0 else second}, y)

    def test_vertical(self):
        img = self.generate(20, 5, 2, 90, px_per_mm=2)
        first, second = self.colors()
        for x in range(20):
            self.assertEqual({img.pixel(x, y) for y in range(5)}, {first if (x // 4) % 2 == 0 else second}, x)

    def test_any_angle_matches_the_formula(self):
        colors = self.colors()
        for angle in (-180, -135, -90, -33, -1, 17, 45, 60, 120, 179):
            # A band width no pixel center lands exactly on the edge of, at 0 or 90°.
            img = self.generate(37, 23, 2.5, angle, px_per_mm=1.37)
            band = 2.5 * 1.37
            wrong = [
                (x, y)
                for y in range(23)
                for x in range(37)
                if img.pixel(x, y) != colors[self.expected(x, y, band, angle)]
            ]
            # The runs are cut where the formula changes band, give or take a pixel center
            # exactly on an edge.
            self.assertLessEqual(len(wrong), 2, (angle, wrong[:5]))

    def test_band_at_least_a_pixel(self):
        img = self.generate(6, 6, 0.5, 0, px_per_mm=0.1)
        first, second = self.colors()
        self.assertEqual([img.pixel(0, y) for y in range(4)], [first, second, first, second])


if __name__ == "__main__":
    unittest.main()

"""Tests of the Film grain effect (film_grain.py). Run with the other tests: make
test-python, from the repository's root. Skipped when numpy, its dependency, isn't
installed (see tests/plugin_testing.py)."""

import unittest
from pathlib import Path

from tests.plugin_testing import Image, gradient, load_plugin

film_grain = load_plugin(Path(__file__).with_name("film_grain.py"))

VALUES = {"amount": 50, "size": 1.0, "kind": "mono", "seed": 7}


def grain(img, scale=1.0, **values):
    film_grain.FilmGrain().apply(img, VALUES | values, scale)
    return img


def gray(width=32, height=32, level=128, alpha=255):
    return Image(width, height, bytes((level, level, level, alpha)) * (width * height))


class DeclaredTest(unittest.TestCase):
    def test_names(self):
        self.assertEqual([e.name for e in film_grain.plugin.effects], ["Film grain"])

    def test_roles(self):
        roles = {p["id"]: p.get("role") for p in film_grain.FilmGrain.params}
        self.assertEqual(roles, {"amount": None, "size": "size", "kind": None, "seed": "seed"})


class FilmGrainTest(unittest.TestCase):
    def test_amount_zero_changes_nothing(self):
        img = gradient()
        before = bytes(img.pixels)
        self.assertEqual(bytes(grain(img, amount=0).pixels), before)

    def test_adds_noise_around_the_color(self):
        img = grain(gray())
        reds = img.pixels[0::4]
        self.assertGreater(len(set(reds)), 10)
        self.assertAlmostEqual(sum(reds) / len(reds), 128, delta=4)

    def test_same_seed_same_grain(self):
        self.assertEqual(grain(gray()).pixels, grain(gray()).pixels)
        self.assertNotEqual(grain(gray()).pixels, grain(gray(), seed=8).pixels)

    def test_mono_moves_the_channels_together(self):
        img = grain(gray())
        self.assertEqual(img.pixels[0::4], img.pixels[1::4])
        self.assertEqual(img.pixels[0::4], img.pixels[2::4])

    def test_color_moves_them_apart(self):
        img = grain(gray(), kind="color")
        self.assertNotEqual(img.pixels[0::4], img.pixels[1::4])

    def test_grain_size_scales_with_the_image(self):
        for size, scale in ((4.0, 1.0), (2.0, 2.0)):
            img = grain(gray(10, 10), size=size, scale=scale)
            # Squares of 4x4 pixels, cut at the right and bottom edges.
            for y in range(10):
                for x in range(10):
                    self.assertEqual(img.pixel(x, y), img.pixel(x // 4 * 4, y // 4 * 4), (size, x, y))
            self.assertGreater(len({img.pixel(x, y) for y in range(10) for x in range(10)}), 1)

    def test_premultiplied_alpha_kept(self):
        img = grain(gray(level=40, alpha=60), amount=100)
        self.assertEqual(set(img.pixels[3::4]), {60})
        self.assertLessEqual(max(img.pixels[0::4]), 60)
        transparent = grain(gray(level=0, alpha=0), amount=100)
        self.assertEqual(set(transparent.pixels), {0})

    def test_clipped_at_black_and_white(self):
        for level in (0, 255):
            img = grain(gray(level=level), amount=100)
            self.assertTrue(all(0 <= v <= 255 for v in img.pixels))
            self.assertIn(level, img.pixels[0::4])

    def test_empty_image(self):
        self.assertEqual(grain(Image(0, 0)).pixels, bytearray())


if __name__ == "__main__":
    unittest.main()

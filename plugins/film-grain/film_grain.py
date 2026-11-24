# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "numpy>=1.26",
# ]
# ///
"""Artwork Creator plugin in Python with a dependency: a film grain effect, adding random
noise to an image, made with numpy. The PEP 723 block above declares numpy; the release
copies it into plugins.json as the version's dependencies, for the app to install.
"""

import numpy as np
from artwork_plugin_sdk import Effect, Plugin, choice_param, float_param, int_param

# Standard deviation of the noise at 100 %, in color levels (0-255).
FULL_STRENGTH = 64


class FilmGrain(Effect):
    id = "pygrain.grain"
    name = "Film grain"
    description = "Random noise, like the grain of film (Python plugin using numpy)"
    params = [
        int_param("amount", "Amount", 0, 100, 20, unit=" %"),
        float_param("size", "Grain size", 1, 8, 1, unit=" px", decimals=1),
        choice_param("kind", "Grain", [("mono", "Monochrome"), ("color", "Color")], "mono"),
        int_param("seed", "Seed", 0, 9999, 0),
    ]

    def apply(self, image, values, scale):
        h, w = image.height, image.width
        if not h or not w or not values["amount"]:
            return
        px = np.frombuffer(bytes(image.pixels), dtype=np.uint8).reshape(h, w, 4)
        # The same seed gives the same grain on every render; a grain is a square of cell
        # pixels, scaled with the image.
        rng = np.random.default_rng(values["seed"])
        cell = max(1, round(values["size"] * scale))
        channels = 3 if values["kind"] == "color" else 1
        noise = rng.normal(0.0, 1.0, (-(-h // cell), -(-w // cell), channels))
        noise = noise.repeat(cell, axis=0).repeat(cell, axis=1)[:h, :w]
        # The pixels are premultiplied: the noise is scaled by alpha, and a channel stays
        # between 0 and alpha.
        alpha = px[..., 3:].astype(np.float32)
        strength = values["amount"] / 100 * FULL_STRENGTH
        rgb = px[..., :3] + noise * strength * (alpha / 255)
        out = px.copy()
        out[..., :3] = np.clip(np.rint(rgb), 0, alpha).astype(np.uint8)
        image.pixels[:] = out.tobytes()


plugin = Plugin("Film grain", "1.0", effects=[FilmGrain()])

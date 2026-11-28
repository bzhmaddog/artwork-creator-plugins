"""Example Artwork Creator plugin in Python: a posterize effect, reducing each color
channel to a few levels. Plain Python, no package needed.

`make plugins` copies it into plugins/. See "Plugins" in README.md.
"""

from artwork_plugin_sdk import Effect, Plugin, int_param


class Posterize(Effect):
    id = "pyexample.posterize"
    name = "Posterize"
    description = "Reduce each color channel to a few levels (Python example plugin)"
    # It changes colors, not shapes: a shape's stroke and a text's outline stay out of it.
    fill_only = True
    params = [int_param("levels", "Levels", 2, 32, 4)]

    def apply(self, image, values, scale):
        step = 255 / (values["levels"] - 1)
        table = bytes(round(round(v / step) * step) for v in range(256))
        # Every byte goes through the table; the alpha bytes are put back after.
        alpha = image.pixels[3::4]
        image.pixels[:] = image.pixels.translate(table)
        image.pixels[3::4] = alpha


# The texts of the code in each language of the app.
TRANSLATIONS = {
    "en-US": {
        "Reduce each color channel to a few levels": "Reduce each color channel to a few levels",
        "Posterize": "Posterize",
        "Reduce each color channel to a few levels (Python example plugin)": (
            "Reduce each color channel to a few levels (Python example plugin)"
        ),
        "Levels": "Levels",
    },
    "en-GB": {
        "Reduce each color channel to a few levels": "Reduce each colour channel to a few levels",
        "Posterize": "Posterize",
        "Reduce each color channel to a few levels (Python example plugin)": (
            "Reduce each colour channel to a few levels (Python example plugin)"
        ),
        "Levels": "Levels",
    },
    "fr-FR": {
        "Reduce each color channel to a few levels": "Réduit chaque canal de couleur à quelques niveaux",
        "Posterize": "Postériser",
        "Reduce each color channel to a few levels (Python example plugin)": (
            "Réduit chaque canal de couleur à quelques niveaux (extension d'exemple en Python)"
        ),
        "Levels": "Niveaux",
    },
}

plugin = Plugin("Posterize", "2.1.0", effects=[Posterize()], translations=TRANSLATIONS)

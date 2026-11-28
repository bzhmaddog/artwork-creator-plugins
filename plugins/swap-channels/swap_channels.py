"""Example Artwork Creator plugin in Python: swaps two color channels of an image. Plain
Python, no package needed.

`make plugins` copies it into plugins/. See "Plugins" in README.md.
"""

from artwork_plugin_sdk import Effect, Plugin, choice_param

# Offsets of the channels in a pixel.
CHANNELS = {"red": 0, "green": 1, "blue": 2}


class SwapChannels(Effect):
    id = "pyswap.swap"
    name = "Swap channels"
    description = "Swap two color channels (Python example plugin)"
    # It changes colors, not shapes: a shape's stroke and a text's outline stay out of it.
    fill_only = True
    params = [
        choice_param(
            "pair",
            "Swap",
            [("red-blue", "Red and blue"), ("red-green", "Red and green"), ("green-blue", "Green and blue")],
            "red-blue",
        ),
    ]

    def apply(self, image, values, scale):
        a, b = (CHANNELS[c] for c in values["pair"].split("-"))
        px = image.pixels
        px[a::4], px[b::4] = px[b::4], px[a::4]


# The texts of the code in each language of the app.
TRANSLATIONS = {
    "en-US": {
        "Swap two color channels of an image": "Swap two color channels of an image",
        "Swap channels": "Swap channels",
        "Swap two color channels (Python example plugin)": "Swap two color channels (Python example plugin)",
        "Swap": "Swap",
        "Red and blue": "Red and blue",
        "Red and green": "Red and green",
        "Green and blue": "Green and blue",
    },
    "en-GB": {
        "Swap two color channels of an image": "Swap two colour channels of an image",
        "Swap channels": "Swap channels",
        "Swap two color channels (Python example plugin)": "Swap two colour channels (Python example plugin)",
        "Swap": "Swap",
        "Red and blue": "Red and blue",
        "Red and green": "Red and green",
        "Green and blue": "Green and blue",
    },
    "fr-FR": {
        "Swap two color channels of an image": "Échange deux canaux de couleur d'une image",
        "Swap channels": "Échanger les canaux",
        "Swap two color channels (Python example plugin)": (
            "Échange deux canaux de couleur (extension d'exemple en Python)"
        ),
        "Swap": "Échanger",
        "Red and blue": "Rouge et bleu",
        "Red and green": "Rouge et vert",
        "Green and blue": "Vert et bleu",
    },
}

plugin = Plugin("Swap channels", "1.2.0", effects=[SwapChannels()], translations=TRANSLATIONS)

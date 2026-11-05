import io

from PIL import Image

CHANNEL = 255
COLORS = 8
EDGE = CHANNEL // COLORS


def _plain(red, green, blue):
    return min(red, green, blue) >= CHANNEL - EDGE or max(red, green, blue) <= EDGE


def _counted(data):
    try:
        with Image.open(io.BytesIO(data)) as raw:
            shrunk = raw.convert("RGBA").quantize(colors=COLORS,
                                                  method=Image.Quantize.FASTOCTREE)
            return shrunk.convert("RGBA").getcolors(COLORS)
    except (OSError, ValueError, Image.DecompressionBombError):
        return None


def dominant(data):
    if not data:
        return None
    best, seen = None, 0
    for count, (red, green, blue, alpha) in _counted(data) or ():
        if alpha <= CHANNEL - EDGE or _plain(red, green, blue) or count <= seen:
            continue
        best, seen = (red, green, blue), count
    return "#%02x%02x%02x" % best if best else None

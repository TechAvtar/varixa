"""Regenerates the deterministic image fixtures in this directory.

Run from services/api:  python tests/fixtures/make_fixtures.py
Fixtures are committed; this script exists so they can be reproduced exactly.
"""

from pathlib import Path

from PIL import Image, ImageDraw

HERE = Path(__file__).parent


def gradient(size: tuple[int, int] = (256, 192)) -> Image.Image:
    w, h = size
    img = Image.new("RGB", size)
    px = img.load()
    assert px is not None
    for y in range(h):
        for x in range(w):
            px[x, y] = (x * 255 // (w - 1), y * 255 // (h - 1), 96)
    d = ImageDraw.Draw(img)
    d.ellipse((60, 40, 200, 150), fill=(240, 240, 240))
    d.rectangle((20, 140, 110, 180), fill=(10, 10, 10))
    return img


def main() -> None:
    base = gradient()
    base.save(HERE / "gradient.png", optimize=True)
    base.save(HERE / "gradient_q60.jpg", quality=60)  # recompressed: same content
    base.transpose(Image.Transpose.FLIP_LEFT_RIGHT).save(HERE / "gradient_flipped.png")
    Image.new("RGB", (64, 64), (0, 0, 0)).save(HERE / "black.png")
    half = Image.new("L", (64, 64), 0)
    ImageDraw.Draw(half).rectangle((32, 0, 63, 63), fill=255)
    half.save(HERE / "half_black_white.png")


if __name__ == "__main__":
    main()

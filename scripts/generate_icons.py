"""Render the Karobar mark to every launcher-icon size the platforms need.

The mark is drawn here rather than shipped as a hand-made PNG so it stays identical
to the in-app `KarobarMark` widget and can be regenerated after any design change:

    python scripts/generate_icons.py
"""

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
MOBILE = ROOT / "mobile"

PRIMARY = (249, 115, 22)        # #F97316
PRIMARY_DARK = (194, 65, 12)    # #C2410C
WHITE = (255, 255, 255)

SUPERSAMPLE = 4  # draw large, downscale — gives clean anti-aliased edges

ANDROID_LAUNCHER = {
    "mipmap-mdpi": 48,
    "mipmap-hdpi": 72,
    "mipmap-xhdpi": 96,
    "mipmap-xxhdpi": 144,
    "mipmap-xxxhdpi": 192,
}

# Adaptive icons are 108dp with the outer 18dp reserved for masking/parallax,
# so the artwork has to live inside the middle 72dp.
ANDROID_ADAPTIVE = {
    "mipmap-mdpi": 108,
    "mipmap-hdpi": 162,
    "mipmap-xhdpi": 216,
    "mipmap-xxhdpi": 324,
    "mipmap-xxxhdpi": 432,
}

IOS_ICONS = {
    "Icon-App-20x20@1x.png": 20, "Icon-App-20x20@2x.png": 40, "Icon-App-20x20@3x.png": 60,
    "Icon-App-29x29@1x.png": 29, "Icon-App-29x29@2x.png": 58, "Icon-App-29x29@3x.png": 87,
    "Icon-App-40x40@1x.png": 40, "Icon-App-40x40@2x.png": 80, "Icon-App-40x40@3x.png": 120,
    "Icon-App-60x60@2x.png": 120, "Icon-App-60x60@3x.png": 180,
    "Icon-App-76x76@1x.png": 76, "Icon-App-76x76@2x.png": 152,
    "Icon-App-83.5x83.5@2x.png": 167,
    "Icon-App-1024x1024@1x.png": 1024,
}


def gradient_square(size: int, radius_ratio: float) -> Image.Image:
    """Rounded square with the brand's diagonal orange gradient."""
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))

    gradient = Image.new("RGBA", (size, size))
    pixels = gradient.load()
    for y in range(size):
        for x in range(size):
            # Diagonal ramp from top-left to bottom-right.
            t = (x + y) / (2 * (size - 1)) if size > 1 else 0
            pixels[x, y] = (
                round(PRIMARY[0] + (PRIMARY_DARK[0] - PRIMARY[0]) * t),
                round(PRIMARY[1] + (PRIMARY_DARK[1] - PRIMARY[1]) * t),
                round(PRIMARY[2] + (PRIMARY_DARK[2] - PRIMARY[2]) * t),
                255,
            )

    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        (0, 0, size - 1, size - 1), radius=int(size * radius_ratio), fill=255
    )
    image.paste(gradient, (0, 0), mask)
    return image


# The mark is a bill with a torn bottom edge and three rising bars punched out of
# it. Geometry lives here in a 100×100 space and is mirrored exactly by
# `KarobarMark` in the Flutter app.
BILL_LEFT, BILL_RIGHT = 24.0, 76.0
BILL_TOP, BILL_BOTTOM = 14.0, 72.0
TEETH = 4
TOOTH_DEPTH = 7.0

BARS = ((36.0, 48.0), (50.0, 37.0), (64.0, 26.0))  # (centre x, top y) — rising
BAR_WIDTH = 8.0
BAR_BOTTOM = 62.0


def mark_mask(size: int) -> Image.Image:
    """An 8-bit mask of the mark: 255 where the artwork is, 0 where it isn't.

    Returning a mask rather than pixels lets the same geometry produce a white
    mark on the gradient tile *and* a transparent-punched adaptive foreground.
    """
    unit = size / 100.0
    mask = Image.new("L", (size, size), 0)
    draw = ImageDraw.Draw(mask)

    def point(x: float, y: float) -> tuple[float, float]:
        return (x * unit, y * unit)

    # Bill body: rounded at the top, torn along the bottom.
    radius = 6.0
    body: list[tuple[float, float]] = []
    steps = 8
    for index in range(steps + 1):  # top-left corner arc
        angle = math.pi + index * (math.pi / 2) / steps
        body.append(
            point(
                BILL_LEFT + radius + radius * math.cos(angle),
                BILL_TOP + radius + radius * math.sin(angle),
            )
        )
    for index in range(steps + 1):  # top-right corner arc
        angle = -math.pi / 2 + index * (math.pi / 2) / steps
        body.append(
            point(
                BILL_RIGHT - radius + radius * math.cos(angle),
                BILL_TOP + radius + radius * math.sin(angle),
            )
        )

    # Torn edge: zigzag from right back to left.
    tooth_width = (BILL_RIGHT - BILL_LEFT) / TEETH
    body.append(point(BILL_RIGHT, BILL_BOTTOM - TOOTH_DEPTH))
    for index in range(TEETH):
        x_mid = BILL_RIGHT - (index + 0.5) * tooth_width
        x_end = BILL_RIGHT - (index + 1) * tooth_width
        body.append(point(x_mid, BILL_BOTTOM))
        body.append(point(x_end, BILL_BOTTOM - TOOTH_DEPTH))

    draw.polygon(body, fill=255)

    # Punch the bars back out.
    for centre_x, top_y in BARS:
        x0, y0 = point(centre_x - BAR_WIDTH / 2, top_y)
        x1, y1 = point(centre_x + BAR_WIDTH / 2, BAR_BOTTOM)
        draw.rounded_rectangle(
            (x0, y0, x1, y1), radius=max(1.0, BAR_WIDTH / 2 * unit), fill=0
        )

    return mask


def white_mark(size: int) -> Image.Image:
    """The mark as opaque white on transparency."""
    layer = Image.new("RGBA", (size, size), WHITE + (0,))
    layer.putalpha(mark_mask(size))
    return layer


def render_icon(size: int, *, radius_ratio: float = 0.22, scale: float = 0.78) -> Image.Image:
    """Full launcher icon: gradient tile with the white mark centred on it."""
    big = size * SUPERSAMPLE
    tile = gradient_square(big, radius_ratio)

    inner = int(big * scale)
    mark = white_mark(inner)
    offset = (big - inner) // 2
    tile.alpha_composite(mark, (offset, offset))

    return tile.resize((size, size), Image.LANCZOS)


def render_adaptive_foreground(size: int) -> Image.Image:
    """Transparent foreground layer; the mark stays inside the safe centre 72/108."""
    big = size * SUPERSAMPLE
    layer = Image.new("RGBA", (big, big), (0, 0, 0, 0))

    inner = int(big * (72 / 108) * 0.82)
    offset = (big - inner) // 2
    layer.alpha_composite(white_mark(inner), (offset, offset))

    return layer.resize((size, size), Image.LANCZOS)


def render_adaptive_background(size: int) -> Image.Image:
    big = size * SUPERSAMPLE
    return gradient_square(big, 0.5).resize((size, size), Image.LANCZOS)


def render_splash(size: int) -> Image.Image:
    """Transparent white mark for the native splash, shown on the orange window."""
    big = size * SUPERSAMPLE
    return white_mark(big).resize((size, size), Image.LANCZOS)


def write(image: Image.Image, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, "PNG", optimize=True)
    print(f"  {path.relative_to(ROOT)}")


def main() -> None:
    print("Android launcher icons")
    for folder, size in ANDROID_LAUNCHER.items():
        write(render_icon(size), MOBILE / "android/app/src/main/res" / folder / "ic_launcher.png")

    print("Android adaptive layers")
    for folder, size in ANDROID_ADAPTIVE.items():
        base = MOBILE / "android/app/src/main/res" / folder
        write(render_adaptive_foreground(size), base / "ic_launcher_foreground.png")
        write(render_adaptive_background(size), base / "ic_launcher_background.png")

    print("Android splash mark")
    for folder, size in {
        "drawable-mdpi": 160, "drawable-hdpi": 240, "drawable-xhdpi": 320,
        "drawable-xxhdpi": 480, "drawable-xxxhdpi": 640,
    }.items():
        write(render_splash(size), MOBILE / "android/app/src/main/res" / folder / "splash_mark.png")

    print("iOS app icons")
    ios = MOBILE / "ios/Runner/Assets.xcassets/AppIcon.appiconset"
    if ios.exists():
        for name, size in IOS_ICONS.items():
            # iOS masks the corners itself and forbids transparency.
            icon = render_icon(size, radius_ratio=0.0).convert("RGB")
            write(icon, ios / name)

    print("In-app assets")
    write(render_icon(512), MOBILE / "assets/images/app_icon.png")
    write(render_splash(512), MOBILE / "assets/images/mark.png")

    print("\nDone. Rebuild the app to see the new icon.")


if __name__ == "__main__":
    main()

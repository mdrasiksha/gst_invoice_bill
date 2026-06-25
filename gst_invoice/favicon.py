"""Generate GST Smart favicon assets from a text-based source definition."""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

FAVICON_BLUE = "#0a65c2"
FAVICON_BLUE_RGBA = (10, 101, 194, 255)
WHITE_RGBA = (255, 255, 255, 255)
FOLD_RGBA = (225, 240, 255, 255)

PNG_SIZES = {
    "favicon-16x16.png": 16,
    "favicon-32x32.png": 32,
    "apple-touch-icon.png": 180,
    "android-chrome-192x192.png": 192,
    "android-chrome-512x512.png": 512,
}
ICO_SIZES = [(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]


def draw_favicon(size: int) -> Image.Image:
    """Draw a small-size-friendly blue GST Smart invoice icon."""
    image = Image.new("RGBA", (size, size), FAVICON_BLUE_RGBA)
    draw = ImageDraw.Draw(image)

    padding = size * 0.18
    x0, y0 = padding, size * 0.14
    x1, y1 = size - padding, size * 0.84
    radius = size * 0.055
    fold = size * 0.18
    line_width = max(1, int(size * 0.028))

    draw.rounded_rectangle((x0, y0, x1, y1), radius=radius, fill=WHITE_RGBA)
    draw.polygon([(x1 - fold, y0), (x1, y0 + fold), (x1 - fold, y0 + fold)], fill=FOLD_RGBA)
    draw.line(
        [(x1 - fold, y0), (x1 - fold, y0 + fold), (x1, y0 + fold)],
        fill=FAVICON_BLUE_RGBA,
        width=max(1, int(size * 0.018)),
    )

    draw.rounded_rectangle(
        (size * 0.31, size * 0.26, size * 0.46, size * 0.31),
        radius=max(1, line_width // 2),
        fill=FAVICON_BLUE_RGBA,
    )
    for index, y_ratio in enumerate((0.37, 0.49, 0.61)):
        y = size * y_ratio
        width_ratio = 0.69 if index < 2 else 0.58
        draw.rounded_rectangle(
            (size * 0.31, y, size * width_ratio, y + line_width),
            radius=max(1, line_width // 2),
            fill=FAVICON_BLUE_RGBA,
        )

    return image


def ensure_favicon_assets(static_dir: Path) -> None:
    """Create favicon files in the static directory when binary assets are absent."""
    static_dir.mkdir(parents=True, exist_ok=True)

    for filename, size in PNG_SIZES.items():
        target = static_dir / filename
        if not target.exists():
            draw_favicon(size).save(target)

    ico_target = static_dir / "favicon.ico"
    if not ico_target.exists():
        draw_favicon(256).save(ico_target, sizes=ICO_SIZES)

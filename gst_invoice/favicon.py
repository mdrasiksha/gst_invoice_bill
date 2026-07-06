"""Generate GST Smart favicon assets from a vector source definition."""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

FAVICON_BLUE = "#2563eb"
FAVICON_BLUE_RGBA = (37, 99, 235, 255)
WHITE_RGBA = (255, 255, 255, 255)
FOLD_RGBA = (225, 240, 255, 255)
TRANSPARENT_RGBA = (255, 255, 255, 0)

PNG_SIZES = {
    "favicon-16x16.png": 16,
    "favicon-32x32.png": 32,
    "favicon-48x48.png": 48,
    "favicon-96x96.png": 96,
    "favicon-192x192.png": 192,
    "favicon-512x512.png": 512,
    "apple-touch-icon.png": 180,
}
LEGACY_PNG_SIZES = {
    "android-chrome-192x192.png": 192,
    "android-chrome-512x512.png": 512,
}
ICO_SIZES = [(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]


def _draw_favicon(size: int, scale: int) -> Image.Image:
    canvas_size = size * scale
    image = Image.new("RGBA", (canvas_size, canvas_size), TRANSPARENT_RGBA)
    draw = ImageDraw.Draw(image)

    s = canvas_size
    badge = s * 0.08
    badge_radius = s * 0.18
    draw.rounded_rectangle((badge, badge, s - badge, s - badge), radius=badge_radius, fill=FAVICON_BLUE_RGBA)

    padding = s * 0.23
    x0, y0 = padding, s * 0.18
    x1, y1 = s - padding, s * 0.78
    radius = s * 0.035
    fold = s * 0.16
    line_width = max(scale, int(s * 0.026))

    draw.rounded_rectangle((x0, y0, x1, y1), radius=radius, fill=WHITE_RGBA)
    draw.polygon([(x1 - fold, y0), (x1, y0 + fold), (x1 - fold, y0 + fold)], fill=FOLD_RGBA)
    draw.line(
        [(x1 - fold, y0), (x1 - fold, y0 + fold), (x1, y0 + fold)],
        fill=FAVICON_BLUE_RGBA,
        width=max(scale, int(s * 0.014)),
    )

    draw.rounded_rectangle(
        (s * 0.34, s * 0.31, s * 0.47, s * 0.36),
        radius=max(scale, line_width // 2),
        fill=FAVICON_BLUE_RGBA,
    )
    for index, y_ratio in enumerate((0.44, 0.54, 0.64)):
        y = s * y_ratio
        width_ratio = 0.67 if index < 2 else 0.58
        draw.rounded_rectangle(
            (s * 0.34, y, s * width_ratio, y + line_width),
            radius=max(scale, line_width // 2),
            fill=FAVICON_BLUE_RGBA,
        )

    return image


def draw_favicon(size: int) -> Image.Image:
    """Draw a transparent, small-size-friendly blue GST Smart invoice icon."""
    scale = 4 if size >= 48 else 8
    image = _draw_favicon(size, scale)
    return image.resize((size, size), Image.Resampling.LANCZOS)


def ensure_favicon_assets(static_dir: Path) -> None:
    """Create favicon files in the static directory from the GST Smart source mark."""
    static_dir.mkdir(parents=True, exist_ok=True)

    for filename, size in {**PNG_SIZES, **LEGACY_PNG_SIZES}.items():
        draw_favicon(size).save(static_dir / filename)

    draw_favicon(256).save(static_dir / "favicon.ico", sizes=ICO_SIZES)

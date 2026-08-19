from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

Image.MAX_IMAGE_PIXELS = 50_000_000  # ~50 Megapixel ≈ 200 MB RAM; raises DecompressionBombError above

from .config import StyleConfig
from .metadata import LicenseInfo


def _best_font(size: int, font_path: str = "") -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [font_path] if font_path else []
    candidates += [
        "DejaVuSans.ttf",
        "LiberationSans-Regular.ttf",
        "Arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    ]
    for path in candidates:
        if not path:
            continue
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


# Reference font size that text_stroke_width is expressed in — the browser
# renderer uses the same constant, so both scale the outline identically.
_STROKE_REFERENCE_FONT_SIZE = 32


def _stroke_kwargs(style: StyleConfig, font_size: int) -> dict:
    """Translate the configured stroke width into Pillow's stroke arguments.

    The browser strokes via canvas `lineWidth`, which is centred on the glyph
    outline, so only half of it shows outside the glyph. Pillow's `stroke_width`
    is that outward extent directly — hence the /2. Both renderers scale the
    configured width with the font size so the outline does not collapse to a
    hairline on large images.
    """
    width = style.text_stroke.width
    if width <= 0:
        return {}
    scaled = width * (font_size / _STROKE_REFERENCE_FONT_SIZE) / 2
    # A requested stroke must stay visible even after rounding down.
    return {
        "stroke_width": max(1, round(scaled)),
        "stroke_fill": (*style.text_stroke.color, 255),
    }


def render_overlay(
    image_path: Path,
    info: LicenseInfo,
    output_path: Path,
    style: StyleConfig | None = None,
) -> None:
    text = info.overlay_text()
    if not text:
        raise ValueError("LicenseInfo has no content to render.")

    if style is None:
        style = StyleConfig()

    with Image.open(image_path) as src:
        img = src.convert("RGBA")
    w, h = img.size

    bar_h = max(20, int(h * style.bar_ratio))
    padding = max(4, int(h * style.padding_ratio))
    font_size = style.font_size if style.font_size > 0 else max(10, bar_h - 2 * padding)

    font = _best_font(font_size, style.font_path)

    bar_rgba = (*style.bar_color, style.bar_opacity)
    text_rgba = (*style.text_color, 255)

    bar = Image.new("RGBA", (w, bar_h), bar_rgba)
    draw = ImageDraw.Draw(bar)
    stroke_kwargs = _stroke_kwargs(style, font_size)
    draw.text((padding, padding), text, font=font, fill=text_rgba, **stroke_kwargs)

    composite = img.copy()
    y = h - bar_h if style.position == "bottom" else 0
    composite.paste(bar, (0, y), bar)

    if output_path.suffix.lower() in {".jpg", ".jpeg"}:
        composite.convert("RGB").save(output_path)
    else:
        composite.save(output_path)

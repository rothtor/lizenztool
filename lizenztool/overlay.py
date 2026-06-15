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

    img = Image.open(image_path).convert("RGBA")
    w, h = img.size

    bar_h = max(20, int(h * style.bar_ratio))
    padding = max(4, int(h * style.padding_ratio))
    font_size = style.font_size if style.font_size > 0 else max(10, bar_h - 2 * padding)

    font = _best_font(font_size, style.font_path)

    bar_rgba = (*style.bar_color, style.bar_opacity)
    text_rgba = (*style.text_color, 255)

    bar = Image.new("RGBA", (w, bar_h), bar_rgba)
    draw = ImageDraw.Draw(bar)
    draw.text((padding, padding), text, font=font, fill=text_rgba)

    composite = img.copy()
    y = h - bar_h if style.position == "bottom" else 0
    composite.paste(bar, (0, y), bar)

    if output_path.suffix.lower() in {".jpg", ".jpeg"}:
        composite.convert("RGB").save(output_path)
    else:
        composite.save(output_path)

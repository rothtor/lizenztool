"""Output file integrity: batch runs must never write two images to one file."""
import re
from pathlib import Path

import pytest
from PIL import Image

from lizenztool.config import AppConfig, OutputConfig, StyleConfig, TextStrokeConfig
from lizenztool.main import _output_path, _unique_path
from lizenztool.metadata import LicenseInfo
from lizenztool.overlay import _stroke_kwargs, render_overlay

_STATIC = Path(__file__).parent.parent / "lizenztool" / "static"


def _cfg(pattern: str) -> AppConfig:
    return AppConfig(output=OutputConfig(filename_pattern=pattern))


@pytest.fixture(scope="module")
def html() -> str:
    return (_STATIC / "index.html").read_text()


class TestDefaultPattern:
    def test_default_pattern_contains_counter(self):
        """The default name must not collapse for two images in the same minute."""
        assert "{n}" in OutputConfig().filename_pattern
        assert OutputConfig().filename_pattern == "img_{date}-{time}-{n}"


class TestUniquePath:
    def test_free_path_is_returned_unchanged(self, tmp_path):
        target = tmp_path / "fixed.jpg"
        assert _unique_path(target, set()) == target

    def test_existing_file_is_not_overwritten(self, tmp_path):
        target = tmp_path / "fixed.jpg"
        target.write_bytes(b"original")
        assert _unique_path(target, set()) == tmp_path / "fixed-2.jpg"
        # The original is untouched.
        assert target.read_bytes() == b"original"

    def test_suffix_increments_past_existing_variants(self, tmp_path):
        (tmp_path / "fixed.jpg").write_bytes(b"a")
        (tmp_path / "fixed-2.jpg").write_bytes(b"b")
        assert _unique_path(tmp_path / "fixed.jpg", set()) == tmp_path / "fixed-3.jpg"

    def test_reserved_paths_collide_even_before_they_exist(self, tmp_path):
        """Within one run, a path handed out earlier counts as taken."""
        target = tmp_path / "fixed.jpg"
        assert _unique_path(target, {target}) == tmp_path / "fixed-2.jpg"

    def test_suffix_keeps_the_extension(self, tmp_path):
        (tmp_path / "photo.png").write_bytes(b"a")
        assert _unique_path(tmp_path / "photo.png", set()).suffix == ".png"


class TestOutputPath:
    def test_constant_pattern_still_yields_distinct_paths(self, tmp_path):
        """filename_pattern = "fixed" must not route a batch onto one file."""
        cfg = _cfg("fixed")
        sources = [tmp_path / f"in{i}.jpg" for i in range(3)]
        for s in sources:
            s.write_bytes(b"x")

        reserved: set[Path] = set()
        out = []
        for idx, src in enumerate(sources, start=1):
            p = _output_path(src, tmp_path / "out", idx, len(sources), cfg, reserved)
            reserved.add(p)
            out.append(p)

        assert len(set(out)) == 3, f"paths collided: {out}"
        assert [p.name for p in out] == ["fixed.jpg", "fixed-2.jpg", "fixed-3.jpg"]

    def test_two_images_same_pattern_differ(self, tmp_path):
        """Two images with the same expanded name get different targets."""
        cfg = _cfg("same")
        a, b = tmp_path / "a.jpg", tmp_path / "b.jpg"
        a.write_bytes(b"x")
        b.write_bytes(b"x")

        reserved: set[Path] = set()
        pa = _output_path(a, None, 1, 2, cfg, reserved)
        reserved.add(pa)
        pb = _output_path(b, None, 2, 2, cfg, reserved)
        assert pa != pb

    def test_existing_output_file_is_not_overwritten(self, tmp_path):
        cfg = _cfg("fixed")
        src = tmp_path / "in.jpg"
        src.write_bytes(b"x")
        existing = tmp_path / "fixed.jpg"
        existing.write_bytes(b"do not touch")

        out = _output_path(src, tmp_path, 1, 1, cfg)
        assert out != existing
        assert existing.read_bytes() == b"do not touch"

    def test_counter_is_zero_padded_to_batch_width(self, tmp_path):
        cfg = _cfg("img_{n}")
        src = tmp_path / "in.jpg"
        src.write_bytes(b"x")
        assert _output_path(src, tmp_path, 7, 100, cfg).name == "img_007.jpg"


class TestRenderedOutputIsNotOverwritten:
    """End-to-end: rendering a batch with a constant pattern keeps every file."""

    def test_batch_render_produces_distinct_files(self, tmp_path):
        cfg = _cfg("fixed")
        info = LicenseInfo(copyright_holder="Jane Doe", year="2024", license_type="CC BY 2.0")

        sources = []
        for i, color in enumerate(("red", "green", "blue")):
            p = tmp_path / f"src{i}.jpg"
            Image.new("RGB", (200, 120), color).save(p)
            sources.append(p)

        reserved: set[Path] = set()
        outputs = []
        for idx, src in enumerate(sources, start=1):
            out = _output_path(src, tmp_path / "out", idx, len(sources), cfg, reserved)
            reserved.add(out)
            out.parent.mkdir(parents=True, exist_ok=True)
            render_overlay(src, info, out, style=cfg.style)
            outputs.append(out)

        assert len(set(outputs)) == 3
        assert all(p.exists() for p in outputs)
        # Each output still carries its own source image.
        colors = [Image.open(p).convert("RGB").getpixel((5, 5)) for p in outputs]
        assert len(set(colors)) == 3


class TestPillowTextStroke:
    """The CLI renderer must stroke text the way the browser canvas does."""

    def test_no_stroke_when_width_is_zero(self):
        style = StyleConfig(text_stroke=TextStrokeConfig(width=0))
        assert _stroke_kwargs(style, 32) == {}

    def test_stroke_kwargs_are_pillow_arguments(self):
        style = StyleConfig(text_stroke=TextStrokeConfig(width=2, color=(10, 20, 30)))
        kw = _stroke_kwargs(style, 64)
        assert set(kw) == {"stroke_width", "stroke_fill"}
        assert kw["stroke_fill"] == (10, 20, 30, 255)

    def test_stroke_scales_with_font_size(self):
        style = StyleConfig(text_stroke=TextStrokeConfig(width=2))
        small = _stroke_kwargs(style, 32)["stroke_width"]
        large = _stroke_kwargs(style, 320)["stroke_width"]
        assert large > small

    def test_requested_stroke_stays_visible_after_rounding(self):
        style = StyleConfig(text_stroke=TextStrokeConfig(width=0.5))
        assert _stroke_kwargs(style, 16)["stroke_width"] >= 1

    def test_stroke_changes_the_rendered_pixels(self, tmp_path):
        src = tmp_path / "src.png"
        Image.new("RGB", (400, 200), "white").save(src)
        info = LicenseInfo(copyright_holder="Jane Doe", year="2024", license_type="CC BY 2.0")

        plain = tmp_path / "plain.png"
        stroked = tmp_path / "stroked.png"
        render_overlay(src, info, plain,
                       style=StyleConfig(bar_opacity=0, text_stroke=TextStrokeConfig(width=0)))
        render_overlay(src, info, stroked,
                       style=StyleConfig(bar_opacity=0,
                                         text_stroke=TextStrokeConfig(width=6, color=(255, 0, 0))))

        assert plain.read_bytes() != stroked.read_bytes()
        # The stroke color actually reaches the canvas.
        colors = Image.open(stroked).convert("RGB").getcolors(maxcolors=1 << 20)
        assert (255, 0, 0) in {color for _count, color in colors}


class TestBrowserTiffRejection:
    """Static checks over the browser code, which has no JS test runner here."""

    def test_file_picker_no_longer_offers_tiff(self, html):
        accept = re.search(r'id="file-input"[^>]*accept="([^"]*)"', html).group(1)
        assert "tiff" not in accept
        assert "image/jpeg" in accept and "image/png" in accept

    def test_tiff_is_detected_and_refused(self, html):
        assert "async function isTiff(" in html
        assert 't("ui.tiff_unsupported")' in html

    def test_tiff_detection_covers_name_mime_and_magic_bytes(self, html):
        block = re.search(r'async function isTiff\((.*?)\n\}', html, re.S).group(1)
        assert r"/\.tiff?$/" in block          # extension (drag & drop, picker)
        assert "_TIFF_MIME" in block            # MIME type (fetched blobs)
        assert "0x2a" in block                  # magic bytes (unnamed blobs)

    def test_drag_and_drop_goes_through_the_same_guard(self, html):
        drop = re.search(r'dropzone\.addEventListener\("drop".*', html).group(0)
        assert "setFile(f)" in drop

    def test_tiff_message_names_the_cli(self):
        import json
        for lang in ("en", "de"):
            msg = json.loads((_STATIC / "locales" / f"{lang}.json").read_text())["ui"]["tiff_unsupported"]
            assert "CLI" in msg
            assert "TIFF" in msg


class TestMetadataWording:
    """The UI must not promise metadata preservation it cannot guarantee."""

    def test_keep_exif_label_is_qualified(self):
        import json
        for lang in ("en", "de"):
            ui = json.loads((_STATIC / "locales" / f"{lang}.json").read_text())["ui"]
            label = ui["keep_exif"]
            assert "EXIF" in label and "XMP" in label
            assert label not in ("Keep original metadata", "Original-Metadaten behalten")
            # The hint explains the JPEG/PNG-only limitation.
            assert "JPEG" in ui["exif_kept_hint"] and "PNG" in ui["exif_kept_hint"]

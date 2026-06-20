"""Test configuration parsing."""
import pytest
from pathlib import Path
import tempfile
import tomllib
from lizenztool.config import (
    load_config,
    _parse,
    _parse_style,
    _parse_color,
    expand_filename,
    StyleConfig,
    OutputConfig,
    IntegrationsConfig,
    AppConfig,
)


class TestParseColor:
    """Test _parse_color for RGB parsing."""

    def test_parse_color_from_list(self):
        """Parse color from [R, G, B] list."""
        assert _parse_color([255, 128, 0]) == (255, 128, 0)

    def test_parse_color_from_string(self):
        """Parse color from 'R,G,B' string."""
        assert _parse_color("255, 128, 0") == (255, 128, 0)

    def test_parse_color_clamps_high_values(self):
        """Clamp values > 255 to 255."""
        assert _parse_color([300, 400, 500]) == (255, 255, 255)

    def test_parse_color_clamps_negative_values(self):
        """Clamp negative values to 0."""
        assert _parse_color([-10, -20, -30]) == (0, 0, 0)

    def test_parse_color_invalid_list_length(self):
        """Raise error for list with != 3 elements."""
        with pytest.raises(ValueError, match="exactly 3 components"):
            _parse_color([255, 128])

    def test_parse_color_invalid_string_format(self):
        """Raise error for malformed string."""
        with pytest.raises(Exception):
            _parse_color("not,a,color")


class TestParseStyle:
    """Test _parse_style for StyleConfig parsing."""

    def test_parse_style_minimal_dict(self):
        """Parse minimal style dict with defaults."""
        style = _parse_style({})
        assert style.position == "bottom"
        assert style.bar_opacity == 200
        assert style.bar_ratio == 0.06

    def test_parse_style_custom_values(self):
        """Parse custom style values."""
        style = _parse_style({
            "position": "top",
            "bar_opacity": 100,
            "bar_ratio": 0.1,
            "font_size": 24,
        })
        assert style.position == "top"
        assert style.bar_opacity == 100
        assert style.bar_ratio == 0.1
        assert style.font_size == 24

    def test_parse_style_custom_colors(self):
        """Parse custom bar_color and text_color."""
        style = _parse_style({
            "bar_color": [0, 0, 0],
            "text_color": [255, 255, 255],
        })
        assert style.bar_color == (0, 0, 0)
        assert style.text_color == (255, 255, 255)

    def test_parse_style_defaults_colors(self):
        """Use default colors when not specified."""
        style = _parse_style({})
        assert style.bar_color == (0, 0, 0)
        assert style.text_color == (255, 255, 255)


class TestParse:
    """Test _parse for full AppConfig parsing."""

    def test_parse_empty_config(self):
        """Parse empty config dict with all defaults."""
        config = _parse({})
        assert config.style.position == "bottom"
        assert config.output.strip_exif is True
        assert config.integrations.flickr_api_key == ""
        assert len(config.presets) == 3  # standard, minimal, bold

    def test_parse_with_style(self):
        """Parse config with custom style."""
        raw = {
            "style": {
                "bar_ratio": 0.1,
                "bar_opacity": 150,
            }
        }
        config = _parse(raw)
        assert config.style.bar_ratio == 0.1
        assert config.style.bar_opacity == 150

    def test_parse_with_output(self):
        """Parse config with custom output settings."""
        raw = {
            "output": {
                "filename_pattern": "photo_{n}",
                "strip_exif": False,
                "write_license_meta": True,
            }
        }
        config = _parse(raw)
        assert config.output.filename_pattern == "photo_{n}"
        assert config.output.strip_exif is False
        assert config.output.write_license_meta is True

    def test_parse_with_integrations(self):
        """Parse config with API keys."""
        raw = {
            "integrations": {
                "flickr_api_key": "key123",
                "dvids_api_key": "key456",
            }
        }
        config = _parse(raw)
        assert config.integrations.flickr_api_key == "key123"
        assert config.integrations.dvids_api_key == "key456"

    def test_parse_with_presets(self):
        """Parse config with custom presets."""
        raw = {
            "presets": {
                "custom": {
                    "bar_ratio": 0.15,
                    "bar_opacity": 50,
                }
            }
        }
        config = _parse(raw)
        assert "custom" in config.presets
        assert config.presets["custom"].bar_ratio == 0.15
        # Built-in presets still present
        assert "standard" in config.presets
        assert "minimal" in config.presets


class TestExpandFilename:
    """Test expand_filename for placeholder substitution."""

    def test_expand_filename_with_date(self):
        """Replace {date} with YYYYMMDD."""
        result = expand_filename("img_{date}.jpg", "0")
        # Just check format: should be img_YYYYMMDD.jpg
        assert result.startswith("img_")
        assert result.endswith(".jpg")
        assert len(result) == len("img_20260620.jpg")

    def test_expand_filename_with_time(self):
        """Replace {time} with HHMM."""
        result = expand_filename("img_{time}.jpg", "0")
        # Should be img_HHMM.jpg
        assert result.startswith("img_")
        assert result.endswith(".jpg")

    def test_expand_filename_with_counter(self):
        """Replace {n} with counter."""
        result = expand_filename("img_{n}.jpg", "abc123")
        assert result == "img_abc123.jpg"

    def test_expand_filename_all_placeholders(self):
        """Replace all placeholders in one pattern."""
        result = expand_filename("photo_{date}-{time}_{n}.jpg", "xyz")
        assert "{date}" not in result
        assert "{time}" not in result
        assert "{n}" not in result
        assert "xyz" in result
        assert result.endswith(".jpg")

    def test_expand_filename_no_placeholders(self):
        """Handle patterns with no placeholders."""
        result = expand_filename("static_name.jpg", "0")
        assert result == "static_name.jpg"


class TestLoadConfig:
    """Test load_config with file loading."""

    def test_load_config_returns_app_config(self):
        """Return AppConfig instance."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".toml", delete=False) as f:
            f.write("[style]\nbar_ratio = 0.08\n")
            f.flush()
            path = Path(f.name)

        try:
            config = load_config(path)
            assert isinstance(config, AppConfig)
            assert config.style.bar_ratio == 0.08
        finally:
            path.unlink()

    def test_load_config_missing_file_uses_defaults(self):
        """Return defaults when file doesn't exist."""
        nonexistent = Path("/tmp/nonexistent_lizenztool_config_12345.toml")
        config = load_config(nonexistent)
        assert isinstance(config, AppConfig)
        assert config.style.bar_ratio == 0.06

    def test_load_config_invalid_toml_raises_error(self):
        """Raise error on invalid TOML syntax."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".toml", delete=False) as f:
            f.write("[style\ninvalid toml")
            f.flush()
            path = Path(f.name)

        try:
            with pytest.raises(Exception):
                load_config(path)
        finally:
            path.unlink()

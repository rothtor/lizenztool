import tomllib
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path


@dataclass
class StyleConfig:
    position: str = "bottom"        # "top" or "bottom"
    bar_opacity: int = 200           # 0–255
    bar_color: tuple[int, int, int] = (0, 0, 0)
    text_color: tuple[int, int, int] = (255, 255, 255)
    font_path: str = ""              # empty = auto-detect system font
    font_size: int = 0               # 0 = proportional to image height
    bar_ratio: float = 0.06          # bar height as fraction of image height
    padding_ratio: float = 0.015     # padding as fraction of image height


@dataclass
class OutputConfig:
    filename_pattern: str = "licensed_{n}"  # {n} = zero-padded counter
    strip_exif: bool = True                  # remove all metadata from output file
    write_license_meta: bool = False         # write confirmed license back as XMP/IPTC


@dataclass
class IntegrationsConfig:
    flickr_api_key: str = ""
    dvids_api_key:  str = ""


_DEFAULT_PRESETS: dict[str, "StyleConfig"] = {}  # filled after StyleConfig is defined


def _default_presets() -> dict[str, "StyleConfig"]:
    return {
        "standard": StyleConfig(),
        "minimal":  StyleConfig(bar_ratio=0.04, bar_opacity=150),
        "bold":     StyleConfig(bar_ratio=0.09, bar_opacity=245),
    }


@dataclass
class AppConfig:
    style: StyleConfig = field(default_factory=StyleConfig)
    output: OutputConfig = field(default_factory=OutputConfig)
    integrations: IntegrationsConfig = field(default_factory=IntegrationsConfig)
    presets: dict[str, StyleConfig] = field(default_factory=_default_presets)


def expand_filename(pattern: str, counter: str) -> str:
    """Replace {n} and {date} placeholders in a filename pattern."""
    return (
        pattern
        .replace("{n}", counter)
        .replace("{date}", date.today().strftime("%Y%m%d"))
    )


_SEARCH_PATHS = [
    Path("lizenztool.toml"),
    Path.home() / ".config" / "lizenztool" / "config.toml",
]


def load_config(config_path: Path | None = None) -> AppConfig:
    if config_path is not None:
        paths = [config_path]
    else:
        paths = _SEARCH_PATHS

    raw: dict = {}
    for p in paths:
        if p.exists():
            with open(p, "rb") as f:
                raw = tomllib.load(f)
            break

    return _parse(raw)


def _parse_color(value: str | list) -> tuple[int, int, int]:
    def clamp(v: int) -> int:
        return max(0, min(255, v))

    if isinstance(value, list):
        r, g, b = value
    else:
        parts = [int(v.strip()) for v in str(value).split(",")]
        r, g, b = parts[0], parts[1], parts[2]
    return (clamp(int(r)), clamp(int(g)), clamp(int(b)))


def _parse_style(s: dict) -> StyleConfig:
    return StyleConfig(
        position=s.get("position", "bottom"),
        bar_opacity=int(s.get("bar_opacity", 200)),
        bar_color=_parse_color(s["bar_color"]) if "bar_color" in s else (0, 0, 0),
        text_color=_parse_color(s["text_color"]) if "text_color" in s else (255, 255, 255),
        font_path=s.get("font_path", ""),
        font_size=int(s.get("font_size", 0)),
        bar_ratio=float(s.get("bar_ratio", 0.06)),
        padding_ratio=float(s.get("padding_ratio", 0.015)),
    )


def _parse(raw: dict) -> AppConfig:
    s = raw.get("style", {})
    o = raw.get("output", {})
    i = raw.get("integrations", {})

    style = _parse_style(s)

    output = OutputConfig(
        filename_pattern=o.get("filename_pattern", "licensed_{n}"),
        strip_exif=bool(o.get("strip_exif", True)),
        write_license_meta=bool(o.get("write_license_meta", False)),
    )

    integrations = IntegrationsConfig(
        flickr_api_key=i.get("flickr_api_key", ""),
        dvids_api_key=i.get("dvids_api_key", ""),
    )

    presets = _default_presets()
    for name, ps in raw.get("presets", {}).items():
        presets[name] = _parse_style(ps)

    return AppConfig(style=style, output=output, integrations=integrations, presets=presets)

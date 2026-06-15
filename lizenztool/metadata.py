import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path

import exiftool

logger = logging.getLogger(__name__)


@dataclass
class LicenseInfo:
    copyright_holder: str = ""
    year: str = ""
    license_type: str = ""
    license_url: str = ""

    def is_empty(self) -> bool:
        return not any((self.copyright_holder, self.year, self.license_type, self.license_url))

    def overlay_text(self) -> str:
        parts = []
        if self.copyright_holder:
            parts.append(f"© {self.year} {self.copyright_holder}" if self.year else f"© {self.copyright_holder}")
        if self.license_type:
            parts.append(self.license_type)
        return "  |  ".join(parts)


# Maps pyexiftool tag names → LicenseInfo fields (first match wins)
_TAG_MAP: dict[str, list[str]] = {
    "copyright_holder": [
        "IPTC:CopyrightNotice",
        "XMP:Rights",
        "EXIF:Copyright",
        "XMP:Creator",
        "IPTC:By-line",
    ],
    "year": [
        "XMP:DateCreated",
        "IPTC:DateCreated",
        "EXIF:DateTimeOriginal",
        "EXIF:CreateDate",
    ],
    "license_type": [
        "XMP:UsageTerms",
        "XMP-cc:License",
        "IPTC:SpecialInstructions",
    ],
    "license_url": [
        "XMP:WebStatement",
        "XMP-cc:License",
        "XMP:Rights",
    ],
}

_SKIP_TAGS = {"SourceFile", "ExifTool:ExifToolVersion"}


def _extract_license(tags: dict) -> LicenseInfo:
    info = LicenseInfo()
    for field_name, candidates in _TAG_MAP.items():
        for tag in candidates:
            value = tags.get(tag)
            if value:
                if field_name == "year" and isinstance(value, str):
                    value = value[:4]
                setattr(info, field_name, str(value).strip())
                break
    return info


def read_metadata_full(image_path: Path) -> tuple[LicenseInfo, dict[str, str]]:
    """Read EXIF/IPTC/XMP metadata with a single exiftool process."""
    try:
        with exiftool.ExifToolHelper() as et:
            tags = et.get_metadata(str(image_path))[0]
    except Exception as exc:
        logger.warning("read_metadata failed for %s: %s", image_path.name, exc)
        return LicenseInfo(), {}
    info = _extract_license(tags)
    raw = {
        k: str(v)
        for k, v in tags.items()
        if k not in _SKIP_TAGS
        and not k.startswith("File:")
        and isinstance(v, (str, int, float))
    }
    return info, raw


def read_metadata(image_path: Path) -> LicenseInfo:
    info, _ = read_metadata_full(image_path)
    return info


def strip_exif(path: Path) -> None:
    subprocess.run(
        ["exiftool", "-all=", "-overwrite_original", str(path)],
        check=True,
        capture_output=True,
    )


def write_metadata(image_path: Path, info: LicenseInfo) -> None:
    parts = " ".join(filter(None, [info.year, info.copyright_holder]))
    copyright_str = f"© {parts}" if parts else ""
    params = {
        "EXIF:Copyright": copyright_str,
        "IPTC:CopyrightNotice": copyright_str,
        "XMP:Rights": info.copyright_holder,
        "XMP:UsageTerms": info.license_type,
        "XMP:WebStatement": info.license_url,
    }
    with exiftool.ExifToolHelper() as et:
        et.set_tags(str(image_path), params)

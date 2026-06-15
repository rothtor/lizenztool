from dataclasses import dataclass, field
from pathlib import Path

import exiftool


@dataclass
class LicenseInfo:
    copyright_holder: str = ""
    year: str = ""
    license_type: str = ""
    license_url: str = ""

    def is_empty(self) -> bool:
        return not any([self.copyright_holder, self.year, self.license_type, self.license_url])

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


def read_metadata(image_path: Path) -> LicenseInfo:
    info = LicenseInfo()
    try:
        with exiftool.ExifToolHelper() as et:
            tags = et.get_metadata(str(image_path))[0]
    except Exception:
        return info

    for field_name, candidates in _TAG_MAP.items():
        for tag in candidates:
            value = tags.get(tag)
            if value:
                # Dates: keep only the year portion
                if field_name == "year" and isinstance(value, str):
                    value = value[:4]
                setattr(info, field_name, str(value).strip())
                break

    return info


def strip_exif(path: Path) -> None:
    import subprocess
    subprocess.run(
        ["exiftool", "-all=", "-overwrite_original", str(path)],
        check=True,
        capture_output=True,
    )


def write_metadata(image_path: Path, info: LicenseInfo) -> None:
    params = {
        "EXIF:Copyright": f"© {info.year} {info.copyright_holder}".strip(),
        "IPTC:CopyrightNotice": f"© {info.year} {info.copyright_holder}".strip(),
        "XMP:Rights": info.copyright_holder,
        "XMP:UsageTerms": info.license_type,
        "XMP:WebStatement": info.license_url,
    }
    with exiftool.ExifToolHelper() as et:
        et.set_tags(str(image_path), params)

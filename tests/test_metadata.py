"""Test metadata extraction and manipulation."""
import pytest
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
from lizenztool.metadata import (
    LicenseInfo,
    _extract_license,
)


class TestLicenseInfo:
    """Test LicenseInfo dataclass."""

    def test_license_info_empty(self):
        """Empty LicenseInfo is_empty() returns True."""
        info = LicenseInfo()
        assert info.is_empty() is True

    def test_license_info_not_empty_with_holder(self):
        """LicenseInfo with copyright_holder is not empty."""
        info = LicenseInfo(copyright_holder="John Doe")
        assert info.is_empty() is False

    def test_license_info_not_empty_with_year(self):
        """LicenseInfo with year is not empty."""
        info = LicenseInfo(year="2023")
        assert info.is_empty() is False

    def test_license_info_overlay_text_holder_only(self):
        """Overlay text with just holder."""
        info = LicenseInfo(copyright_holder="John Doe")
        text = info.overlay_text()
        assert "© John Doe" in text

    def test_license_info_overlay_text_holder_and_year(self):
        """Overlay text with holder and year."""
        info = LicenseInfo(copyright_holder="John Doe", year="2023")
        text = info.overlay_text()
        assert "© 2023 John Doe" in text

    def test_license_info_overlay_text_with_license(self):
        """Overlay text includes license type."""
        info = LicenseInfo(
            copyright_holder="John Doe",
            year="2023",
            license_type="CC BY 4.0"
        )
        text = info.overlay_text()
        assert "© 2023 John Doe" in text
        assert "CC BY 4.0" in text
        assert "|" in text  # separator

    def test_license_info_overlay_text_license_only(self):
        """Overlay text with just license (no holder)."""
        info = LicenseInfo(license_type="CC BY 4.0")
        text = info.overlay_text()
        assert "CC BY 4.0" in text
        assert "©" not in text


class TestExtractLicense:
    """Test _extract_license tag parsing."""

    def test_extract_license_empty_tags(self):
        """Extract from empty tag dict returns empty LicenseInfo."""
        info = _extract_license({})
        assert info.is_empty()

    def test_extract_license_copyright_iptc(self):
        """Extract copyright_holder from IPTC:CopyrightNotice."""
        tags = {"IPTC:CopyrightNotice": "Jane Photographer"}
        info = _extract_license(tags)
        assert info.copyright_holder == "Jane Photographer"

    def test_extract_license_copyright_xmp(self):
        """Extract copyright_holder from XMP:Rights when IPTC absent."""
        tags = {"XMP:Rights": "Jane Photographer"}
        info = _extract_license(tags)
        assert info.copyright_holder == "Jane Photographer"

    def test_extract_license_copyright_exif(self):
        """Extract copyright_holder from EXIF:Copyright when earlier absent."""
        tags = {"EXIF:Copyright": "Jane Photographer"}
        info = _extract_license(tags)
        assert info.copyright_holder == "Jane Photographer"

    def test_extract_license_copyright_priority(self):
        """IPTC takes priority over XMP and EXIF."""
        tags = {
            "IPTC:CopyrightNotice": "IPTC",
            "XMP:Rights": "XMP",
            "EXIF:Copyright": "EXIF",
        }
        info = _extract_license(tags)
        assert info.copyright_holder == "IPTC"

    def test_extract_license_year_date_created(self):
        """Extract year from XMP:DateCreated (YYYY-MM-DD format)."""
        tags = {"XMP:DateCreated": "2023-06-15"}
        info = _extract_license(tags)
        assert info.year == "2023"

    def test_extract_license_year_exif(self):
        """Extract year from EXIF:DateTimeOriginal."""
        tags = {"EXIF:DateTimeOriginal": "2023:04:10 14:30:00"}
        info = _extract_license(tags)
        assert info.year == "2023"

    def test_extract_license_year_strips_to_first_4_chars(self):
        """Year extraction takes only first 4 chars."""
        tags = {"XMP:DateCreated": "2023-12-25T10:30:00Z"}
        info = _extract_license(tags)
        assert info.year == "2023"

    def test_extract_license_license_type_xmp(self):
        """Extract license_type from XMP:UsageTerms."""
        tags = {"XMP:UsageTerms": "CC BY 4.0"}
        info = _extract_license(tags)
        assert info.license_type == "CC BY 4.0"

    def test_extract_license_license_url(self):
        """Extract license_url from XMP:WebStatement."""
        tags = {"XMP:WebStatement": "https://creativecommons.org/licenses/by/4.0/"}
        info = _extract_license(tags)
        assert info.license_url == "https://creativecommons.org/licenses/by/4.0/"

    def test_extract_license_strips_whitespace(self):
        """Whitespace is stripped from extracted values."""
        tags = {
            "IPTC:CopyrightNotice": "  Jane Photographer  ",
            "XMP:DateCreated": "  2023-06-15  ",
        }
        info = _extract_license(tags)
        assert info.copyright_holder == "Jane Photographer"
        assert info.year == "2023"

    def test_extract_license_coerces_to_string(self):
        """Non-string values are coerced to string."""
        tags = {
            "IPTC:CopyrightNotice": 12345,  # numeric value
            "XMP:UsageTerms": "CC BY 4.0",
        }
        info = _extract_license(tags)
        assert info.copyright_holder == "12345"
        assert isinstance(info.copyright_holder, str)

    def test_extract_license_skips_empty_values(self):
        """Skip empty/falsy values to next candidate."""
        tags = {
            "IPTC:CopyrightNotice": "",  # empty, skip
            "XMP:Rights": "Jane Photographer",
        }
        info = _extract_license(tags)
        assert info.copyright_holder == "Jane Photographer"

    def test_extract_license_multiple_fields(self):
        """Extract all fields from a complete metadata dict."""
        tags = {
            "IPTC:CopyrightNotice": "Jane Photographer",
            "XMP:DateCreated": "2023-06-15",
            "XMP:UsageTerms": "CC BY 4.0",
            "XMP:WebStatement": "https://creativecommons.org/licenses/by/4.0/",
        }
        info = _extract_license(tags)
        assert info.copyright_holder == "Jane Photographer"
        assert info.year == "2023"
        assert info.license_type == "CC BY 4.0"
        assert info.license_url == "https://creativecommons.org/licenses/by/4.0/"
        assert not info.is_empty()

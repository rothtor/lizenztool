"""License integrity: a license must never be silently turned into another one.

CC BY 2.0 is not CC BY 4.0, CC BY-SA 3.0 is not CC BY-SA 4.0, and public domain
is not CC0. These tests pin that behaviour down for every code path that can set
a license from an external source.
"""
import json
import re
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from lizenztool.api import _cc_label_from_url, _flickr_license_table, app

_STATIC = Path(__file__).parent.parent / "lizenztool" / "static"


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture(scope="module")
def html() -> str:
    return (_STATIC / "index.html").read_text()


@pytest.fixture(autouse=True)
def _clear_license_cache():
    """The Flickr license list is lru_cached — don't leak it between tests."""
    _flickr_license_table.cache_clear()
    yield
    _flickr_license_table.cache_clear()


def _flickr_photo(license_id: str) -> MagicMock:
    resp = MagicMock()
    resp.__enter__.return_value = resp
    resp.read.return_value = json.dumps({
        "stat": "ok",
        "photo": {
            "owner": {"realname": "Jane Doe", "username": "jane"},
            "license": license_id,
            "dates": {"taken": "2009-04-02 10:00:00"},
        },
    }).encode()
    return resp


def _cfg_with_keys():
    from lizenztool.config import AppConfig
    cfg = AppConfig()
    cfg.integrations.flickr_api_key = "test_key"
    cfg.integrations.dvids_api_key = "test_key"
    return cfg


class TestCcLabelFromUrl:
    """The short code is read out of the canonical CC URL, version included."""

    @pytest.mark.parametrize("url,expected", [
        ("https://creativecommons.org/licenses/by/2.0/",        "CC BY 2.0"),
        ("https://creativecommons.org/licenses/by-sa/3.0/",     "CC BY-SA 3.0"),
        ("https://creativecommons.org/licenses/by-nc-sa/2.0/",  "CC BY-NC-SA 2.0"),
        ("https://creativecommons.org/licenses/by-nc-nd/4.0/",  "CC BY-NC-ND 4.0"),
        ("http://creativecommons.org/licenses/by/2.5/",         "CC BY 2.5"),
    ])
    def test_versions_are_preserved(self, url, expected):
        assert _cc_label_from_url(url) == expected

    def test_cc0_url_maps_to_cc0(self):
        assert _cc_label_from_url("https://creativecommons.org/publicdomain/zero/1.0/") == "CC0 1.0"

    def test_public_domain_mark_is_not_cc0(self):
        """The Public Domain Mark is a distinct instrument from CC0."""
        label = _cc_label_from_url("https://creativecommons.org/publicdomain/mark/1.0/")
        assert label == "Public Domain Mark 1.0"
        assert "CC0" not in label

    @pytest.mark.parametrize("url", ["", "https://example.com/license", "not a url"])
    def test_unknown_urls_yield_nothing(self, url):
        assert _cc_label_from_url(url) == ""


class TestFlickrLicenseFidelity:
    """Flickr license IDs are resolved via flickr.photos.licenses.getInfo."""

    @patch("lizenztool.api._flickr_license_table")
    @patch("urllib.request.urlopen")
    @patch("lizenztool.api.cfg")
    def test_cc_by_2_0_stays_cc_by_2_0(self, mock_cfg, mock_urlopen, mock_table, client):
        mock_cfg.return_value = _cfg_with_keys()
        mock_table.return_value = {
            "4": ("Attribution License", "https://creativecommons.org/licenses/by/2.0/"),
        }
        mock_urlopen.return_value = _flickr_photo("4")

        data = client.post("/flickr-meta", json={"photo_id": "1234"}).json()
        assert data["license"] == "CC BY 2.0"
        assert data["license_url"] == "https://creativecommons.org/licenses/by/2.0/"
        assert data["rights_check_required"] is False

    @patch("lizenztool.api._flickr_license_table")
    @patch("urllib.request.urlopen")
    @patch("lizenztool.api.cfg")
    def test_cc_by_sa_3_0_stays_cc_by_sa_3_0(self, mock_cfg, mock_urlopen, mock_table, client):
        mock_cfg.return_value = _cfg_with_keys()
        mock_table.return_value = {
            "5": ("Attribution-ShareAlike License", "https://creativecommons.org/licenses/by-sa/3.0/"),
        }
        mock_urlopen.return_value = _flickr_photo("5")

        data = client.post("/flickr-meta", json={"photo_id": "1234"}).json()
        assert data["license"] == "CC BY-SA 3.0"
        assert "4.0" not in data["license"]

    @patch("lizenztool.api._flickr_license_table")
    @patch("urllib.request.urlopen")
    @patch("lizenztool.api.cfg")
    def test_unknown_license_id_is_not_invented(self, mock_cfg, mock_urlopen, mock_table, client):
        """An ID missing from the list yields no license — not All Rights Reserved."""
        mock_cfg.return_value = _cfg_with_keys()
        mock_table.return_value = {"4": ("Attribution License", "https://creativecommons.org/licenses/by/2.0/")}
        mock_urlopen.return_value = _flickr_photo("99")

        resp = client.post("/flickr-meta", json={"photo_id": "1234"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["license"] == ""
        assert data["license_url"] == ""
        assert data["rights_check_required"] is True
        # Author/year are still usable metadata.
        assert data["author"] == "Jane Doe"
        assert data["year"] == "2009"

    @patch("lizenztool.api._flickr_license_table")
    @patch("urllib.request.urlopen")
    @patch("lizenztool.api.cfg")
    def test_failed_license_lookup_is_not_invented(self, mock_cfg, mock_urlopen, mock_table, client):
        """A broken license lookup must not fall back to any license."""
        mock_cfg.return_value = _cfg_with_keys()
        mock_table.side_effect = RuntimeError("Flickr license lookup failed")
        mock_urlopen.return_value = _flickr_photo("4")

        data = client.post("/flickr-meta", json={"photo_id": "1234"}).json()
        assert data["license"] == ""
        assert data["rights_check_required"] is True

    @patch("lizenztool.api._flickr_license_table")
    @patch("urllib.request.urlopen")
    @patch("lizenztool.api.cfg")
    def test_all_rights_reserved_is_passed_through_when_flickr_says_so(
        self, mock_cfg, mock_urlopen, mock_table, client
    ):
        """Reporting ARR is fine when Flickr actually reports it."""
        mock_cfg.return_value = _cfg_with_keys()
        mock_table.return_value = {"0": ("All Rights Reserved", "")}
        mock_urlopen.return_value = _flickr_photo("0")

        data = client.post("/flickr-meta", json={"photo_id": "1234"}).json()
        assert data["license"] == "All Rights Reserved"
        assert data["rights_check_required"] is False

    @patch("urllib.request.urlopen")
    def test_license_table_is_read_from_the_api(self, mock_urlopen):
        """The table comes from flickr.photos.licenses.getInfo, not a hardcoded map."""
        resp = MagicMock()
        resp.__enter__.return_value = resp
        resp.read.return_value = json.dumps({
            "stat": "ok",
            "licenses": {"license": [
                {"id": 4, "name": "Attribution License", "url": "https://creativecommons.org/licenses/by/2.0/"},
                {"id": 5, "name": "Attribution-ShareAlike License", "url": "https://creativecommons.org/licenses/by-sa/2.0/"},
            ]},
        }).encode()
        mock_urlopen.return_value = resp

        table = _flickr_license_table("some_key")
        assert table["4"] == ("Attribution License", "https://creativecommons.org/licenses/by/2.0/")
        assert table["5"][1].endswith("/by-sa/2.0/")

        called_url = mock_urlopen.call_args[0][0].full_url
        assert "flickr.photos.licenses.getInfo" in called_url

    @patch("urllib.request.urlopen")
    def test_license_table_is_cached(self, mock_urlopen):
        resp = MagicMock()
        resp.__enter__.return_value = resp
        resp.read.return_value = json.dumps({"stat": "ok", "licenses": {"license": []}}).encode()
        mock_urlopen.return_value = resp

        _flickr_license_table("cached_key")
        _flickr_license_table("cached_key")
        assert mock_urlopen.call_count == 1


class TestDvidsLicenseFidelity:
    @patch("urllib.request.urlopen")
    @patch("lizenztool.api.cfg")
    def test_dvids_asserts_no_license(self, mock_cfg, mock_urlopen, client):
        mock_cfg.return_value = _cfg_with_keys()
        resp = MagicMock()
        resp.__enter__.return_value = resp
        resp.read.return_value = json.dumps({
            "credit": [{"rank": "SSgt", "name": "John Smith"}],
            "date": "2023-07-20T00:00:00Z",
        }).encode()
        mock_urlopen.return_value = resp

        data = client.post("/dvids-meta", json={"asset_id": "4242"}).json()
        assert data["license"] == ""
        assert data["license_url"] == ""
        assert data["rights_check_required"] is True
        assert "CC0" not in json.dumps(data)
        assert "Public Domain" not in json.dumps(data)


class TestNoStaticFlickrTable:
    """The removed hardcoded Flickr ID -> license map must not come back."""

    def test_api_has_no_static_flickr_license_map(self):
        source = (Path(__file__).parent.parent / "lizenztool" / "api.py").read_text()
        assert "_FLICKR_LICENSES" not in source


class TestFrontendLicenseSemantics:
    """Static checks on the browser code, which has no test runner here."""

    def test_no_version_upgrade_maps(self, html):
        """No mapping rewrites a 1.0/2.0/2.5/3.0 license to a 4.0 one."""
        upgrades = re.findall(
            r'"CC ([A-Z-]+) (1\.0|2\.0|2\.5|3\.0)"\s*:\s*"CC \1 4\.0"', html
        )
        assert upgrades == [], f"license version upgrades still present: {upgrades}"

    def test_public_domain_is_not_mapped_to_cc0(self, html):
        assert not re.search(r'"Public Domain"\s*:\s*"CC0', html)

    def test_wikimedia_normalisation_table_is_gone(self, html):
        assert "_LICENSE_NORMALIZE_WM" not in html

    def test_cc0_and_public_domain_are_separate_options(self, html):
        assert '<option value="CC0 1.0">' in html
        assert '<option value="Public Domain">' in html
        assert "CC0 1.0 (Public Domain)" not in html

    def test_public_domain_has_no_cc0_url(self, html):
        """The Public Domain entry must not carry a CC0 deed URL."""
        block = re.search(r'const LICENSE_URLS = \{(.*?)\};', html, re.S).group(1)
        assert "Public Domain" not in block
        pd_entry = re.search(r'"Public Domain":\s*\{[^}]*\}', html).group(0)
        assert "publicdomain/zero" not in pd_entry
        assert "url: null" in pd_entry

    @pytest.mark.parametrize("source", ["flickr", "wikimedia", "dvids", "own"])
    def test_source_presets_set_no_license(self, html, source):
        block = re.search(r'const SOURCES = \{(.*?)\};', html, re.S).group(1)
        entry = re.search(rf'{source}:\s*\{{\s*license:\s*([^,]+),', block).group(1).strip()
        assert entry == "null", f"source {source!r} preselects a license: {entry}"

    def test_source_license_is_adopted_verbatim(self, html):
        """Externally reported licenses get inserted into the select as-is."""
        assert "function ensureLicenseOption(" in html
        assert "function applySourceLicense(" in html

    def test_wikimedia_uses_official_fields(self, html):
        assert "LicenseShortName" in html
        assert "LicenseUrl" in html

    def test_prompts_keep_cc0_and_public_domain_apart(self):
        from lizenztool.prompts import _LICENSE_CHOICES, _LICENSE_URLS
        assert "CC0 1.0" in _LICENSE_CHOICES
        assert "Public Domain" in _LICENSE_CHOICES
        assert "CC0 1.0 (Public Domain)" not in _LICENSE_CHOICES
        assert "Public Domain" not in _LICENSE_URLS

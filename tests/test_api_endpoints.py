"""Test FastAPI endpoints."""
import json
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from lizenztool.api import app


@pytest.fixture
def client():
    return TestClient(app)


class TestPresetsEndpoint:
    """Test GET /api/presets."""

    def test_presets_returns_json(self, client):
        """Return preset configurations as JSON."""
        response = client.get("/api/presets")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, dict)

    def test_presets_includes_standard(self, client):
        """Include 'standard' preset."""
        response = client.get("/api/presets")
        data = response.json()
        assert "standard" in data

    def test_presets_includes_minimal(self, client):
        """Include 'minimal' preset."""
        response = client.get("/api/presets")
        data = response.json()
        assert "minimal" in data

    def test_presets_includes_bold(self, client):
        """Include 'bold' preset."""
        response = client.get("/api/presets")
        data = response.json()
        assert "bold" in data

    def test_presets_preset_structure(self, client):
        """Preset has expected fields."""
        response = client.get("/api/presets")
        data = response.json()
        preset = data["standard"]
        assert "bar_ratio" in preset
        assert "bar_opacity" in preset
        assert "bar_color" in preset
        assert "text_color" in preset
        assert "font_size" in preset
        assert "padding_ratio" in preset

    def test_presets_bar_ratio_numeric(self, client):
        """bar_ratio is numeric."""
        response = client.get("/api/presets")
        data = response.json()
        assert isinstance(data["standard"]["bar_ratio"], (int, float))
        assert data["standard"]["bar_ratio"] > 0


class TestIntegrationsEndpoint:
    """Test GET /api/integrations."""

    def test_integrations_returns_json(self, client):
        """Return integration status as JSON."""
        response = client.get("/api/integrations")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, dict)

    def test_integrations_has_flickr(self, client):
        """Response includes 'flickr' key."""
        response = client.get("/api/integrations")
        data = response.json()
        assert "flickr" in data

    def test_integrations_has_dvids(self, client):
        """Response includes 'dvids' key."""
        response = client.get("/api/integrations")
        data = response.json()
        assert "dvids" in data

    def test_integrations_values_boolean(self, client):
        """Integration values are boolean."""
        response = client.get("/api/integrations")
        data = response.json()
        assert isinstance(data["flickr"], bool)
        assert isinstance(data["dvids"], bool)


class TestFetchUrlEndpoint:
    """Test POST /fetch-url with SSRF protection."""

    def test_fetch_url_rejects_empty_body(self, client):
        """Reject empty request body."""
        response = client.post("/fetch-url", json={})
        assert response.status_code in (422, 400)

    def test_fetch_url_rejects_missing_url(self, client):
        """Reject missing 'url' field."""
        response = client.post("/fetch-url", json={"other": "value"})
        assert response.status_code in (422, 400)

    def test_fetch_url_rejects_invalid_scheme(self, client):
        """Reject URLs with invalid schemes (ftp, file, etc)."""
        response = client.post("/fetch-url", json={"url": "ftp://example.com/image.jpg"})
        assert response.status_code == 422

    def test_fetch_url_rejects_no_scheme(self, client):
        """Reject URLs without a scheme."""
        response = client.post("/fetch-url", json={"url": "example.com/image.jpg"})
        assert response.status_code == 422

    def test_fetch_url_rejects_localhost(self, client):
        """Block http://localhost/...."""
        response = client.post("/fetch-url", json={"url": "http://localhost/image.jpg"})
        assert response.status_code == 422

    def test_fetch_url_rejects_127_0_0_1(self, client):
        """Block http://127.0.0.1/...."""
        response = client.post("/fetch-url", json={"url": "http://127.0.0.1/image.jpg"})
        assert response.status_code == 422

    def test_fetch_url_rejects_private_10(self, client):
        """Block http://10.0.0.1/...."""
        response = client.post("/fetch-url", json={"url": "http://10.0.0.1/image.jpg"})
        assert response.status_code == 422

    def test_fetch_url_rejects_private_192(self, client):
        """Block http://192.168.1.1/...."""
        response = client.post("/fetch-url", json={"url": "http://192.168.1.1/image.jpg"})
        assert response.status_code == 422

    def test_fetch_url_rejects_url_too_long(self, client):
        """Reject URLs longer than MAX_FETCH_URL_LEN (2048)."""
        long_url = "http://example.com/" + "x" * 2100
        response = client.post("/fetch-url", json={"url": long_url})
        assert response.status_code == 422

    @patch("lizenztool.api._safe_opener.open")
    def test_fetch_url_rejects_non_image_content_type(self, mock_open, client):
        """Reject response with non-image Content-Type."""
        mock_response = MagicMock()
        mock_response.__enter__.return_value = mock_response
        mock_response.headers.get_content_type.return_value = "text/html"
        mock_response.read.return_value = b"<html>...</html>"
        mock_open.return_value = mock_response

        response = client.post("/fetch-url", json={"url": "http://example.com/page.html"})
        assert response.status_code == 415

    @patch("lizenztool.api._safe_opener.open")
    def test_fetch_url_rejects_invalid_image_magic(self, mock_open, client):
        """Reject response with image Content-Type but invalid magic bytes."""
        mock_response = MagicMock()
        mock_response.__enter__.return_value = mock_response
        mock_response.headers.get_content_type.return_value = "image/jpeg"
        mock_response.read.return_value = b"not a real image"
        mock_open.return_value = mock_response

        response = client.post("/fetch-url", json={"url": "http://example.com/image.jpg"})
        assert response.status_code == 415

    @patch("lizenztool.api._safe_opener.open")
    def test_fetch_url_rejects_oversized_response(self, mock_open, client):
        """Reject response larger than MAX_UPLOAD_BYTES."""
        mock_response = MagicMock()
        mock_response.__enter__.return_value = mock_response
        mock_response.headers.get_content_type.return_value = "image/jpeg"
        # Return more than MAX_UPLOAD_BYTES
        mock_response.read.return_value = b"\xff\xd8\xff" + (b"x" * (20 * 1024 * 1024 + 1))
        mock_open.return_value = mock_response

        response = client.post("/fetch-url", json={"url": "http://example.com/image.jpg"})
        assert response.status_code == 413

    @patch("lizenztool.api._safe_opener.open")
    def test_fetch_url_accepts_valid_jpeg(self, mock_open, client):
        """Accept valid JPEG image."""
        jpeg_data = b"\xff\xd8\xff\xe0JFIF\x00\x01"
        mock_response = MagicMock()
        mock_response.__enter__.return_value = mock_response
        mock_response.headers.get_content_type.return_value = "image/jpeg"
        mock_response.read.return_value = jpeg_data
        mock_open.return_value = mock_response

        response = client.post("/fetch-url", json={"url": "http://example.com/image.jpg"})
        assert response.status_code == 200
        assert response.content == jpeg_data

    @patch("lizenztool.api._safe_opener.open")
    def test_fetch_url_accepts_valid_png(self, mock_open, client):
        """Accept valid PNG image."""
        png_data = b"\x89PNG\r\n\x1a\n"
        mock_response = MagicMock()
        mock_response.__enter__.return_value = mock_response
        mock_response.headers.get_content_type.return_value = "image/png"
        mock_response.read.return_value = png_data
        mock_open.return_value = mock_response

        response = client.post("/fetch-url", json={"url": "http://example.com/image.png"})
        assert response.status_code == 200
        assert response.content == png_data


class TestFlickrMetaEndpoint:
    """Test POST /flickr-meta."""

    def test_flickr_meta_rejects_empty_body(self, client):
        """Reject empty request body."""
        response = client.post("/flickr-meta", json={})
        assert response.status_code in (422, 400)

    def test_flickr_meta_rejects_missing_photo_id(self, client):
        """Reject missing 'photo_id' field."""
        response = client.post("/flickr-meta", json={"other": "value"})
        assert response.status_code in (422, 400)

    @patch("lizenztool.api.cfg")
    def test_flickr_meta_rejects_non_numeric_id(self, mock_cfg, client):
        """Reject non-numeric photo_id."""
        from lizenztool.config import AppConfig
        mock_cfg.return_value = AppConfig()
        mock_cfg.return_value.integrations.flickr_api_key = "test_key"

        response = client.post("/flickr-meta", json={"photo_id": "not-a-number"})
        assert response.status_code == 422

    @patch("lizenztool.api.cfg")
    def test_flickr_meta_rejects_oversized_id(self, mock_cfg, client):
        """Reject photo_id longer than MAX_ID_LEN (30)."""
        from lizenztool.config import AppConfig
        mock_cfg.return_value = AppConfig()
        mock_cfg.return_value.integrations.flickr_api_key = "test_key"

        response = client.post("/flickr-meta", json={"photo_id": "1" * 31})
        assert response.status_code == 422

    @patch("lizenztool.api.cfg")
    def test_flickr_meta_rejects_empty_id(self, mock_cfg, client):
        """Reject empty photo_id."""
        from lizenztool.config import AppConfig
        mock_cfg.return_value = AppConfig()
        mock_cfg.return_value.integrations.flickr_api_key = "test_key"

        response = client.post("/flickr-meta", json={"photo_id": ""})
        assert response.status_code == 422

    @patch("urllib.request.urlopen")
    @patch("lizenztool.api.cfg")
    def test_flickr_meta_accepts_valid_id(self, mock_cfg, mock_urlopen, client):
        """Accept valid numeric photo_id."""
        from lizenztool.config import AppConfig
        mock_cfg.return_value = AppConfig()
        mock_cfg.return_value.integrations.flickr_api_key = "test_key"

        mock_response = MagicMock()
        mock_response.__enter__.return_value = mock_response
        mock_response.read.return_value = json.dumps({
            "stat": "ok",
            "photo": {
                "owner": {"realname": "John Doe", "username": "johndoe"},
                "license": "4",
                "dates": {"taken": "2023-06-15 12:34:56"}
            }
        }).encode()
        mock_urlopen.return_value = mock_response

        response = client.post("/flickr-meta", json={"photo_id": "123456789"})
        assert response.status_code == 200
        data = response.json()
        assert data["author"] == "John Doe"
        assert data["year"] == "2023"
        assert data["license"] == "CC BY 4.0"

    @patch("urllib.request.urlopen")
    @patch("lizenztool.api.cfg")
    def test_flickr_meta_returns_error_on_api_failure(self, mock_cfg, mock_urlopen, client):
        """Return 502 when Flickr API fails."""
        from lizenztool.config import AppConfig
        mock_cfg.return_value = AppConfig()
        mock_cfg.return_value.integrations.flickr_api_key = "test_key"
        mock_urlopen.side_effect = Exception("Connection failed")

        response = client.post("/flickr-meta", json={"photo_id": "123456789"})
        assert response.status_code == 502


class TestDvidsMetaEndpoint:
    """Test POST /dvids-meta."""

    def test_dvids_meta_rejects_empty_body(self, client):
        """Reject empty request body."""
        response = client.post("/dvids-meta", json={})
        assert response.status_code in (422, 400)

    def test_dvids_meta_rejects_missing_asset_id(self, client):
        """Reject missing 'asset_id' field."""
        response = client.post("/dvids-meta", json={"other": "value"})
        assert response.status_code in (422, 400)

    @patch("lizenztool.api.cfg")
    def test_dvids_meta_rejects_non_numeric_id(self, mock_cfg, client):
        """Reject non-numeric asset_id."""
        from lizenztool.config import AppConfig
        mock_cfg.return_value = AppConfig()
        mock_cfg.return_value.integrations.dvids_api_key = "test_key"

        response = client.post("/dvids-meta", json={"asset_id": "not-a-number"})
        assert response.status_code == 422

    @patch("lizenztool.api.cfg")
    def test_dvids_meta_rejects_oversized_id(self, mock_cfg, client):
        """Reject asset_id longer than MAX_ID_LEN (30)."""
        from lizenztool.config import AppConfig
        mock_cfg.return_value = AppConfig()
        mock_cfg.return_value.integrations.dvids_api_key = "test_key"

        response = client.post("/dvids-meta", json={"asset_id": "1" * 31})
        assert response.status_code == 422

    @patch("urllib.request.urlopen")
    @patch("lizenztool.api.cfg")
    def test_dvids_meta_accepts_valid_id(self, mock_cfg, mock_urlopen, client):
        """Accept valid numeric asset_id."""
        from lizenztool.config import AppConfig
        mock_cfg.return_value = AppConfig()
        mock_cfg.return_value.integrations.dvids_api_key = "test_key"

        mock_response = MagicMock()
        mock_response.__enter__.return_value = mock_response
        mock_response.read.return_value = json.dumps({
            "credit": [
                {"rank": "SSgt", "name": "John Smith"}
            ],
            "date": "2023-07-20T00:00:00Z"
        }).encode()
        mock_urlopen.return_value = mock_response

        response = client.post("/dvids-meta", json={"asset_id": "987654321"})
        assert response.status_code == 200
        data = response.json()
        assert "John Smith" in data["author"]
        assert data["year"] == "2023"
        assert data["license"] == "CC0 1.0 (Public Domain)"


class TestIndexEndpoint:
    """Test GET /."""

    def test_index_returns_html(self, client):
        """Serve index.html as HTML."""
        response = client.get("/")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/html")

    def test_index_contains_form(self, client):
        """HTML contains form elements."""
        response = client.get("/")
        html = response.text
        assert "<form" in html or "form" in html.lower()

    def test_index_contains_canvas(self, client):
        """HTML contains canvas for drawing."""
        response = client.get("/")
        html = response.text
        assert "<canvas" in html

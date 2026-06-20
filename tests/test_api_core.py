"""Test core API functions: IP detection, SSRF protection, utilities."""
import pytest
from lizenztool.api import _client_ip, _detect_ext, _is_ssrf_target, _safe_log
from fastapi import Request
from unittest.mock import Mock


class TestClientIp:
    """Test _client_ip extraction from headers and socket."""

    def test_client_ip_from_x_forwarded_for_single(self):
        """Extract single IP from X-Forwarded-For."""
        request = Mock(spec=Request)
        request.headers.get.return_value = "192.0.2.1"
        assert _client_ip(request) == "192.0.2.1"

    def test_client_ip_from_x_forwarded_for_multiple(self):
        """Extract first IP from comma-separated X-Forwarded-For."""
        request = Mock(spec=Request)
        request.headers.get.return_value = "192.0.2.1, 10.0.0.1, 172.16.0.1"
        assert _client_ip(request) == "192.0.2.1"

    def test_client_ip_from_x_forwarded_for_with_spaces(self):
        """Strip whitespace from extracted IP."""
        request = Mock(spec=Request)
        request.headers.get.return_value = " 192.0.2.1 , 10.0.0.1"
        assert _client_ip(request) == "192.0.2.1"

    def test_client_ip_fallback_to_socket(self):
        """Fall back to request.client.host when X-Forwarded-For missing."""
        request = Mock(spec=Request)
        request.headers.get.return_value = None
        request.client.host = "203.0.113.5"
        assert _client_ip(request) == "203.0.113.5"

    def test_client_ip_fallback_no_client(self):
        """Return 'unknown' when no client info available."""
        request = Mock(spec=Request)
        request.headers.get.return_value = None
        request.client = None
        assert _client_ip(request) == "unknown"


class TestDetectExt:
    """Test magic-byte image format detection."""

    def test_detect_ext_jpeg(self):
        """Detect JPEG by magic bytes."""
        data = b"\xff\xd8\xff\xe0JFIF"
        assert _detect_ext(data) == ".jpg"

    def test_detect_ext_png(self):
        """Detect PNG by magic bytes."""
        data = b"\x89PNG\r\n\x1a\n"
        assert _detect_ext(data) == ".png"

    def test_detect_ext_tiff_little_endian(self):
        """Detect TIFF (little-endian) by magic bytes."""
        data = b"II*\x00"
        assert _detect_ext(data) == ".tif"

    def test_detect_ext_tiff_big_endian(self):
        """Detect TIFF (big-endian) by magic bytes."""
        data = b"MM\x00*"
        assert _detect_ext(data) == ".tif"

    def test_detect_ext_webp(self):
        """Detect WebP by magic bytes."""
        data = b"RIFF\x00\x00\x00\x00WEBP"
        assert _detect_ext(data) == ".webp"

    def test_detect_ext_unknown(self):
        """Return None for unrecognized format."""
        data = b"\x00\x00\x00\x00unknown"
        assert _detect_ext(data) is None

    def test_detect_ext_empty(self):
        """Handle empty data gracefully."""
        assert _detect_ext(b"") is None


class TestIsSsrfTarget:
    """Test SSRF protection: block private/loopback/reserved IPs."""

    def test_is_ssrf_target_localhost_ipv4(self):
        """Block 127.0.0.1."""
        assert _is_ssrf_target("127.0.0.1") is True

    def test_is_ssrf_target_localhost_name(self):
        """Block 'localhost' (resolves to 127.0.0.1)."""
        assert _is_ssrf_target("localhost") is True

    def test_is_ssrf_target_private_10(self):
        """Block 10.x.x.x range."""
        assert _is_ssrf_target("10.0.0.1") is True

    def test_is_ssrf_target_private_172(self):
        """Block 172.16.x.x range."""
        assert _is_ssrf_target("172.16.0.1") is True

    def test_is_ssrf_target_private_192(self):
        """Block 192.168.x.x range."""
        assert _is_ssrf_target("192.168.1.1") is True

    def test_is_ssrf_target_link_local(self):
        """Block 169.254.x.x (link-local)."""
        assert _is_ssrf_target("169.254.1.1") is True

    def test_is_ssrf_target_reserved(self):
        """Block 0.0.0.0."""
        assert _is_ssrf_target("0.0.0.0") is True

    def test_is_ssrf_target_public(self):
        """Allow public IPs (e.g. 8.8.8.8)."""
        assert _is_ssrf_target("8.8.8.8") is False

    def test_is_ssrf_target_public_cloudflare(self):
        """Allow Cloudflare DNS (1.1.1.1)."""
        assert _is_ssrf_target("1.1.1.1") is False

    def test_is_ssrf_target_invalid_hostname(self):
        """Block unresolvable hostnames (conservative approach)."""
        assert _is_ssrf_target("this.hostname.does.not.exist.invalid") is True


class TestSafeLog:
    """Test control-character stripping for safe logging."""

    def test_safe_log_normal_string(self):
        """Pass through normal strings unchanged."""
        assert _safe_log("normal string") == "normal string"

    def test_safe_log_strips_null(self):
        """Replace null bytes with underscore."""
        assert _safe_log("str\x00ing") == "str_ing"

    def test_safe_log_strips_control_chars(self):
        """Replace control characters (0x00-0x1f) with underscore."""
        assert _safe_log("str\x01\x02\x03ing") == "str___ing"

    def test_safe_log_strips_del(self):
        """Replace DEL (0x7f) with underscore."""
        assert _safe_log("str\x7fing") == "str_ing"

    def test_safe_log_truncates(self):
        """Truncate to max_len (default 200)."""
        long_str = "x" * 300
        assert len(_safe_log(long_str)) == 200

    def test_safe_log_custom_max_len(self):
        """Respect custom max_len."""
        long_str = "x" * 100
        assert len(_safe_log(long_str, max_len=50)) == 50

    def test_safe_log_none_input(self):
        """Handle None input."""
        assert _safe_log(None) == ""

    def test_safe_log_empty_string(self):
        """Handle empty string."""
        assert _safe_log("") == ""

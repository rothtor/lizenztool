"""SSRF regression tests: IPv4, IPv6, mixed DNS answers, redirects, pinning."""
import http.server
import ipaddress
import socket
import threading
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

import lizenztool.api as api
from lizenztool.api import (
    _ip_is_global,
    _is_ssrf_target,
    _NoSSRFRedirectHandler,
    _resolve_global_addrinfo,
    _safe_create_connection,
    _safe_opener,
    _SSRFBlockedError,
    app,
)


@pytest.fixture
def client():
    return TestClient(app)


def _addrinfo(*ips):
    """Build getaddrinfo-shaped records for the given IP strings."""
    out = []
    for ip in ips:
        v6 = ":" in ip
        family = socket.AF_INET6 if v6 else socket.AF_INET
        sockaddr = (ip, 80, 0, 0) if v6 else (ip, 80)
        out.append((family, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", sockaddr))
    return out


class TestIpClassification:
    @pytest.mark.parametrize("ip", [
        "127.0.0.1", "127.1.2.3",          # loopback
        "10.0.0.1", "172.16.0.1", "192.168.1.1",  # RFC1918
        "169.254.169.254",                  # link-local / cloud metadata
        "0.0.0.0", "255.255.255.255",       # unspecified / broadcast
        "100.64.0.1",                       # CGNAT shared address space
        "224.0.0.1",                        # multicast
    ])
    def test_non_global_ipv4_is_rejected(self, ip):
        assert _ip_is_global(ipaddress.ip_address(ip)) is False

    @pytest.mark.parametrize("ip", [
        "::1",            # loopback
        "::",             # unspecified
        "fe80::1",        # link-local
        "fc00::1",        # unique local
        "fd00::1",        # unique local
        "ff02::1",        # multicast
    ])
    def test_non_global_ipv6_is_rejected(self, ip):
        assert _ip_is_global(ipaddress.ip_address(ip)) is False

    @pytest.mark.parametrize("ip", [
        "::ffff:127.0.0.1",   # IPv4-mapped loopback
        "::ffff:10.0.0.1",    # IPv4-mapped RFC1918
        "::ffff:169.254.169.254",
        "2002:7f00:1::",      # 6to4 wrapping 127.0.0.1
        "2002:a00:1::",       # 6to4 wrapping 10.0.0.1
    ])
    def test_ipv6_wrapped_private_ipv4_is_rejected(self, ip):
        """An IPv6 wrapper must not smuggle a private IPv4 address through."""
        assert _ip_is_global(ipaddress.ip_address(ip)) is False

    @pytest.mark.parametrize("ip", ["8.8.8.8", "1.1.1.1", "93.184.216.34",
                                    "2001:4860:4860::8888", "2606:4700:4700::1111"])
    def test_global_addresses_are_allowed(self, ip):
        assert _ip_is_global(ipaddress.ip_address(ip)) is True


class TestResolveGlobalAddrinfo:
    def test_all_records_are_checked_not_just_the_first(self):
        """A host with one public and one private address must be blocked."""
        with patch("socket.getaddrinfo", return_value=_addrinfo("93.184.216.34", "127.0.0.1")):
            with pytest.raises(_SSRFBlockedError):
                _resolve_global_addrinfo("rebind.example.com")

    def test_private_record_first_is_blocked(self):
        with patch("socket.getaddrinfo", return_value=_addrinfo("10.0.0.5", "93.184.216.34")):
            with pytest.raises(_SSRFBlockedError):
                _resolve_global_addrinfo("rebind.example.com")

    def test_public_ipv4_with_private_ipv6_is_blocked(self):
        """The IPv6 answer must be checked too, not skipped."""
        with patch("socket.getaddrinfo", return_value=_addrinfo("93.184.216.34", "::1")):
            with pytest.raises(_SSRFBlockedError):
                _resolve_global_addrinfo("dual.example.com")

    def test_all_global_records_are_allowed(self):
        infos = _addrinfo("93.184.216.34", "2001:4860:4860::8888")
        with patch("socket.getaddrinfo", return_value=infos):
            assert _resolve_global_addrinfo("example.com") == infos

    def test_dns_failure_blocks(self):
        with patch("socket.getaddrinfo", side_effect=socket.gaierror("nope")):
            with pytest.raises(_SSRFBlockedError):
                _resolve_global_addrinfo("example.com")

    def test_empty_answer_blocks(self):
        with patch("socket.getaddrinfo", return_value=[]):
            with pytest.raises(_SSRFBlockedError):
                _resolve_global_addrinfo("example.com")

    def test_empty_hostname_blocks(self):
        with pytest.raises(_SSRFBlockedError):
            _resolve_global_addrinfo("")

    def test_is_ssrf_target_never_fails_open(self):
        """Any unexpected error must still block."""
        with patch("socket.getaddrinfo", side_effect=RuntimeError("boom")):
            assert _is_ssrf_target("example.com") is True


class TestFetchUrlBlocking:
    @pytest.mark.parametrize("url", [
        "http://127.0.0.1/image.jpg",
        "http://localhost/image.jpg",
        "http://10.0.0.1/image.jpg",
        "http://172.16.0.1/image.jpg",
        "http://192.168.1.1/image.jpg",
        "http://169.254.169.254/latest/meta-data/",
        "http://0.0.0.0/image.jpg",
        "http://[::1]/image.jpg",
        "http://[fe80::1]/image.jpg",
        "http://[fc00::1]/image.jpg",
        "http://[::ffff:127.0.0.1]/image.jpg",
    ])
    def test_blocked_targets(self, client, url):
        assert client.post("/fetch-url", json={"url": url}).status_code == 422

    def test_mixed_dns_answer_is_blocked_end_to_end(self, client):
        with patch("socket.getaddrinfo", return_value=_addrinfo("93.184.216.34", "127.0.0.1")):
            resp = client.post("/fetch-url", json={"url": "http://rebind.example.com/a.jpg"})
        assert resp.status_code == 422

    def test_global_host_passes_the_ssrf_gate(self, client):
        """A fully global answer reaches the fetch stage (mocked below it)."""
        resp_obj = MagicMock()
        resp_obj.__enter__.return_value = resp_obj
        resp_obj.headers.get_content_type.return_value = "image/jpeg"
        resp_obj.read.return_value = b"\xff\xd8\xff\xe0JFIF"

        with patch("socket.getaddrinfo", return_value=_addrinfo("93.184.216.34")), \
             patch("lizenztool.api._safe_opener.open", return_value=resp_obj):
            resp = client.post("/fetch-url", json={"url": "http://example.com/a.jpg"})
        assert resp.status_code == 200


class TestRedirectValidation:
    """Every redirect is a fresh, untrusted URL and gets re-checked."""

    def _redirect_to(self, newurl):
        handler = _NoSSRFRedirectHandler()
        req = MagicMock()
        handler.redirect_request(req, MagicMock(), 302, "Found", {}, newurl)

    @pytest.mark.parametrize("newurl", [
        "http://127.0.0.1/admin",
        "http://localhost/admin",
        "http://169.254.169.254/latest/meta-data/",
        "http://10.0.0.1/",
        "http://[::1]/",
    ])
    def test_redirect_to_internal_address_is_blocked(self, newurl):
        with pytest.raises(_SSRFBlockedError):
            self._redirect_to(newurl)

    @pytest.mark.parametrize("newurl", [
        "file:///etc/passwd",
        "ftp://example.com/x",
        "gopher://example.com/",
        "data:text/plain,hello",
    ])
    def test_redirect_to_disallowed_scheme_is_blocked(self, newurl):
        with pytest.raises(_SSRFBlockedError):
            self._redirect_to(newurl)

    def test_redirect_without_host_is_blocked(self):
        with pytest.raises(_SSRFBlockedError):
            self._redirect_to("http:///no-host")

    def test_redirect_to_global_host_is_allowed(self):
        with patch("socket.getaddrinfo", return_value=_addrinfo("93.184.216.34")), \
             patch.object(_NoSSRFRedirectHandler.__bases__[0], "redirect_request",
                          return_value="delegated") as parent:
            handler = _NoSSRFRedirectHandler()
            result = handler.redirect_request(MagicMock(), MagicMock(), 302, "Found", {},
                                              "http://example.com/other.jpg")
        assert result == "delegated"
        assert parent.called


class TestOpenerHardening:
    def test_opener_has_no_file_ftp_or_data_handlers(self):
        names = {type(h).__name__ for h in _safe_opener.handlers}
        assert not names & {"FileHandler", "FTPHandler", "DataHandler", "ProxyHandler"}

    def test_opener_uses_the_pinned_connection_handlers(self):
        names = {type(h).__name__ for h in _safe_opener.handlers}
        assert "_PinnedHTTPHandler" in names
        assert "_PinnedHTTPSHandler" in names
        assert "_NoSSRFRedirectHandler" in names

    def test_pinned_connections_use_the_validating_factory(self):
        for cls in (api._PinnedHTTPConnection, api._PinnedHTTPSConnection):
            conn = cls("example.com")
            assert conn._create_connection is _safe_create_connection

    def test_safe_create_connection_blocks_a_private_target(self):
        with pytest.raises(_SSRFBlockedError):
            _safe_create_connection(("127.0.0.1", 80), 1)

    def test_safe_create_connection_resolves_only_once(self):
        """DNS is queried once and the connect uses that answer (no second lookup)."""
        infos = _addrinfo("93.184.216.34")
        with patch("socket.getaddrinfo", return_value=infos) as resolve, \
             patch("socket.socket") as sock_cls:
            _safe_create_connection(("example.com", 80), 1)
        assert resolve.call_count == 1
        sock_cls.return_value.connect.assert_called_once_with(("93.184.216.34", 80))


def _serve(handler_cls):
    """Run a throwaway HTTP server on loopback; yields its base URL."""
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler_cls)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()


@pytest.fixture
def allow_loopback():
    """Treat loopback as global so a local test server is reachable.

    Everything else keeps its real classification, so a redirect to e.g.
    169.254.169.254 is still blocked — which is exactly what we want to prove.
    """
    real = api._ip_is_global

    def patched(ip):
        return True if ip.is_loopback else real(ip)

    with patch.object(api, "_ip_is_global", patched):
        yield


class TestPinnedOpenerEndToEnd:
    """Exercise the real opener stack against a local server."""

    def test_pinned_opener_fetches_a_real_response(self, allow_loopback):
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                body = b"\xff\xd8\xff\xe0JFIF"
                self.send_response(200)
                self.send_header("Content-Type", "image/jpeg")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        for base in _serve(Handler):
            with _safe_opener.open(base + "/img.jpg", timeout=5) as resp:
                assert resp.headers.get_content_type() == "image/jpeg"
                assert resp.read().startswith(b"\xff\xd8\xff")

    def test_redirect_to_metadata_service_is_blocked_by_the_real_opener(self, allow_loopback):
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(302)
                self.send_header("Location", "http://169.254.169.254/latest/meta-data/")
                self.end_headers()

            def log_message(self, *args):
                pass

        for base in _serve(Handler):
            with pytest.raises(_SSRFBlockedError):
                _safe_opener.open(base + "/redirect", timeout=5)

    def test_redirect_to_file_scheme_is_blocked_by_the_real_opener(self, allow_loopback):
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(302)
                self.send_header("Location", "file:///etc/passwd")
                self.end_headers()

            def log_message(self, *args):
                pass

        for base in _serve(Handler):
            with pytest.raises(_SSRFBlockedError):
                _safe_opener.open(base + "/redirect", timeout=5)

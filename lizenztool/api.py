import http.client
import ipaddress
import json
import logging
import os
import re
import socket
import urllib.request
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlencode, urljoin, urlparse

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from .config import AppConfig, load_config, _SEARCH_PATHS

MAX_UPLOAD_BYTES  = int(os.getenv("MAX_UPLOAD_MB", "20")) * 1024 * 1024
MAX_FETCH_URL_LEN = 2048
MAX_ID_LEN        = 30

_STATIC = Path(__file__).parent / "static"
logger = logging.getLogger(__name__)


def _configure_logging() -> None:
    level = os.getenv("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-8s %(name)s  %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    # Keep uvicorn's own loggers consistent
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logging.getLogger(name).handlers = []
        logging.getLogger(name).propagate = True


_configure_logging()


def _client_ip(request: Request) -> str:
    """Client IP used for rate limiting.

    Deliberately does NOT read X-Forwarded-For itself: that header is
    attacker-controlled, and trusting its first value lets anyone reset their
    own rate-limit bucket per request. request.client.host is authoritative —
    uvicorn's --proxy-headers rewrites it from X-Forwarded-For, but only when
    the peer is inside --forwarded-allow-ips. Deciding which proxies to trust
    therefore lives in the deployment config, not in application code.
    """
    return request.client.host if request.client else "unknown"


def _detect_ext(data: bytes) -> str | None:
    if data[:3] == b"\xff\xd8\xff":
        return ".jpg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return ".png"
    if data[:4] in (b"II*\x00", b"MM\x00*"):
        return ".tif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    return None


_ALLOWED_SCHEMES = {"http", "https"}
_ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png", "image/tiff", "image/webp"}


class _SSRFBlockedError(Exception):
    pass


def _unwrap_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address):
    """Peel IPv6 wrappers so an embedded IPv4 address is judged on its own.

    ::ffff:127.0.0.1 and 2002:7f00:1:: reach the same loopback as 127.0.0.1;
    without unwrapping, is_global would be asked about the wrapper instead.
    """
    if isinstance(ip, ipaddress.IPv6Address):
        for embedded in (ip.ipv4_mapped, ip.sixtofour):
            if embedded is not None:
                return embedded
        if ip.teredo is not None:
            return ip.teredo[1]
    return ip


def _ip_is_global(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """True only for addresses that are globally routable on the public internet."""
    ip = _unwrap_ip(ip)
    if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
        return False
    if ip.is_multicast or ip.is_unspecified:
        return False
    # is_global is the authoritative check (it also covers shared address space,
    # benchmarking ranges, IPv6 ULAs, …); the explicit checks above stay so the
    # intent is readable and so we fail closed if a category is ever reclassified.
    return bool(ip.is_global)


def _resolve_global_addrinfo(hostname: str, port: int = 0) -> list:
    """Resolve a host and return its addrinfo records — or raise if any is unsafe.

    Fail closed in three ways: every A and AAAA record must be globally routable
    (one private answer blocks the whole host, which defeats the "one public,
    one private address" trick), an empty answer blocks, and a DNS failure
    blocks. The records are returned so the caller can connect to exactly the
    addresses that were validated instead of resolving a second time.

    DNS-rebinding caveat: this closes the TOCTOU window between validation and
    connect for THIS request (_safe_create_connection reuses these exact
    records instead of re-resolving). It does not, and cannot by itself,
    guarantee every future request to the same hostname sees the same address —
    an attacker who controls DNS can still return a fresh, different validated
    answer on a later call within this process's DNS cache TTL. Full protection
    against that would need connection-level pinning across requests (e.g. a
    custom DNS resolver cache with a fixed TTL keyed per outbound call), which
    is out of scope for a stateless single-shot fetch like /fetch-url. Treat
    this as "no rebinding within one fetch", not "rebinding solved".
    """
    if not hostname:
        raise _SSRFBlockedError("missing host")
    try:
        infos = socket.getaddrinfo(hostname, port or None, type=socket.SOCK_STREAM)
    except (socket.gaierror, UnicodeError, OSError) as exc:
        raise _SSRFBlockedError(f"cannot resolve {hostname!r}") from exc
    if not infos:
        raise _SSRFBlockedError(f"no addresses for {hostname!r}")

    for family, _type, _proto, _canon, sockaddr in infos:
        try:
            ip = ipaddress.ip_address(sockaddr[0])
        except ValueError as exc:
            raise _SSRFBlockedError(f"unparsable address for {hostname!r}") from exc
        if not _ip_is_global(ip):
            raise _SSRFBlockedError(f"non-global address {ip} for {hostname!r}")
    return infos


def _is_ssrf_target(hostname: str) -> bool:
    """True when the host must not be fetched. Blocks on any doubt."""
    try:
        _resolve_global_addrinfo(hostname)
        return False
    except _SSRFBlockedError:
        return True
    except Exception:  # pragma: no cover - defensive: never fail open
        return True


def _safe_create_connection(address, timeout=socket._GLOBAL_DEFAULT_TIMEOUT, source_address=None):
    """socket.create_connection replacement that validates and pins the address.

    Resolution happens exactly once here and the socket connects to one of the
    addresses that were just validated, so a DNS answer cannot change between
    the check and the connect for this request.
    """
    host, port = address[0], address[1]
    infos = _resolve_global_addrinfo(host, port)

    last_error: Exception | None = None
    for family, socktype, proto, _canon, sockaddr in infos:
        sock = None
        try:
            sock = socket.socket(family, socktype, proto)
            if timeout is not socket._GLOBAL_DEFAULT_TIMEOUT:
                sock.settimeout(timeout)
            if source_address:
                sock.bind(source_address)
            sock.connect(sockaddr)
            return sock
        except OSError as exc:
            last_error = exc
            if sock is not None:
                sock.close()
    raise last_error if last_error else OSError(f"could not connect to {host!r}")


class _PinnedHTTPConnection(http.client.HTTPConnection):
    """HTTPConnection whose address resolution is validated and pinned."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # http.client documents this attribute as the connection factory.
        self._create_connection = _safe_create_connection


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    """As above; TLS still uses the hostname for SNI and certificate checks."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._create_connection = _safe_create_connection


class _PinnedHTTPHandler(urllib.request.HTTPHandler):
    def http_open(self, req):
        return self.do_open(_PinnedHTTPConnection, req)


class _PinnedHTTPSHandler(urllib.request.HTTPSHandler):
    def https_open(self, req):
        return self.do_open(_PinnedHTTPSConnection, req, context=self._context)


class _NoSSRFRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Re-validate every redirect target: a 302 is a fresh, untrusted URL."""

    @staticmethod
    def _check_redirect_target(newurl: str) -> None:
        parsed = urlparse(newurl)
        if parsed.scheme not in _ALLOWED_SCHEMES:
            raise _SSRFBlockedError(f"redirect scheme {parsed.scheme!r}: {newurl}")
        if not parsed.netloc or not parsed.hostname:
            raise _SSRFBlockedError(f"redirect without host: {newurl}")
        if _is_ssrf_target(parsed.hostname):
            raise _SSRFBlockedError(f"redirect to non-global host: {newurl}")

    def http_error_302(self, req, fp, code, msg, headers):
        # urllib screens a few schemes (file:, …) before it ever calls
        # redirect_request, raising a different exception. Check here first so
        # every unsafe redirect surfaces uniformly as _SSRFBlockedError.
        location = headers.get("location") or headers.get("uri")
        if location:
            self._check_redirect_target(urljoin(req.full_url, location))
        return super().http_error_302(req, fp, code, msg, headers)

    # The base class aliases these to its own http_error_302; re-point them.
    http_error_301 = http_error_303 = http_error_307 = http_error_308 = http_error_302

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        self._check_redirect_target(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _build_safe_opener() -> urllib.request.OpenerDirector:
    """Opener with only the handlers /fetch-url needs.

    build_opener() would also install FileHandler, FTPHandler, DataHandler and
    ProxyHandler. The first three are extra URL schemes we never want reachable,
    and a proxy would carry the request to an address we never validated,
    defeating the pinning below. So the opener is assembled explicitly.
    """
    opener = urllib.request.OpenerDirector()
    for handler in (
        _PinnedHTTPHandler(),
        _PinnedHTTPSHandler(),
        _NoSSRFRedirectHandler(),
        urllib.request.HTTPErrorProcessor(),
        urllib.request.HTTPDefaultErrorHandler(),
        urllib.request.UnknownHandler(),
    ):
        opener.add_handler(handler)
    return opener


_safe_opener = _build_safe_opener()


def _safe_log(value: str | None, max_len: int = 200) -> str:
    """Strip control characters from user-supplied strings before logging."""
    if not value:
        return ""
    return re.sub(r"[\x00-\x1f\x7f]", "_", str(value))[:max_len]


limiter = Limiter(key_func=_client_ip)
app = FastAPI(title="Lizenztool", docs_url=None, redoc_url=None)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.mount("/static", StaticFiles(directory=str(_STATIC)), name="static")

# Config is reloaded automatically when the toml file changes on disk.
_cfg_cache: AppConfig = load_config()
_cfg_mtime: float = 0.0

def _cfg_path() -> Path | None:
    for p in _SEARCH_PATHS:
        if p.exists():
            return p
    return None

def cfg() -> AppConfig:
    global _cfg_cache, _cfg_mtime
    p = _cfg_path()
    if p is not None:
        mtime = p.stat().st_mtime
        if mtime != _cfg_mtime:
            _cfg_cache = load_config()
            _cfg_mtime = mtime
    return _cfg_cache


_version_cache: str | None = None

def _app_version() -> str:
    """Resolve the app version from a single source of truth. Prefer the
    pyproject.toml that sits next to the source tree (dev runs, where installed
    metadata can be stale); fall back to installed package metadata (prod, where
    pyproject.toml isn't beside the installed package). Cached after first lookup."""
    global _version_cache
    if _version_cache is not None:
        return _version_cache
    version = ""
    try:
        import tomllib
        pyproject = Path(__file__).parent.parent / "pyproject.toml"
        if pyproject.exists():
            version = tomllib.loads(pyproject.read_text())["project"]["version"]
    except Exception:
        pass
    if not version:
        try:
            from importlib.metadata import version as pkg_version
            version = pkg_version("lizenztool")
        except Exception:
            version = "0.0.0"
    _version_cache = version
    return version


class FetchUrlRequest(BaseModel):
    url: str


# Canonical Creative Commons deed URLs carry the exact version of a license.
# Deriving the short code from the URL is a pure re-spelling of what the source
# said ("…/licenses/by/2.0/" -> "CC BY 2.0"); it never upgrades a version and
# never turns a public-domain mark into CC0.
_CC_LICENSE_RE = re.compile(
    r"^https?://creativecommons\.org/licenses/([a-z-]+)/(\d+\.\d+)/?", re.I
)
_CC_PUBLICDOMAIN_RE = re.compile(
    r"^https?://creativecommons\.org/publicdomain/(zero|mark)/(\d+\.\d+)/?", re.I
)


def _cc_label_from_url(url: str) -> str:
    """Return the exact CC short code encoded in a canonical CC URL, else ""."""
    if not url:
        return ""
    m = _CC_LICENSE_RE.match(url.strip())
    if m:
        return f"CC {m.group(1).upper()} {m.group(2)}"
    m = _CC_PUBLICDOMAIN_RE.match(url.strip())
    if m:
        kind, version = m.group(1).lower(), m.group(2)
        # CC0 and the Public Domain Mark are distinct instruments and must stay so.
        return f"CC0 {version}" if kind == "zero" else f"Public Domain Mark {version}"
    return ""


@lru_cache(maxsize=8)
def _flickr_license_table(api_key: str) -> dict[str, tuple[str, str]]:
    """Flickr license ID -> (official name, license URL), straight from the API.

    Resolving IDs through flickr.photos.licenses.getInfo keeps the exact license
    Flickr reports (including its version). Cached because the list is static.
    """
    params = urlencode({
        "method": "flickr.photos.licenses.getInfo",
        "api_key": api_key,
        "format": "json",
        "nojsoncallback": "1",
    })
    req = urllib.request.Request(
        f"https://api.flickr.com/services/rest/?{params}",
        headers={"User-Agent": "Lizenztool/1.0"},
    )
    with urllib.request.urlopen(req, timeout=8) as resp:
        data = json.loads(resp.read())
    if data.get("stat") != "ok":
        raise RuntimeError(data.get("message") or "Flickr license lookup failed")

    result: dict[str, tuple[str, str]] = {}
    for item in data.get("licenses", {}).get("license", []):
        license_id = str(item.get("id", "")).strip()
        name = str(item.get("name") or "").strip()
        license_url = str(item.get("url") or "").strip()
        if license_id and name:
            result[license_id] = (name, license_url)
    return result


@app.get("/api/presets")
async def presets_info() -> dict:
    return {
        name: {
            "bar_ratio":     s.bar_ratio,
            "bar_opacity":   s.bar_opacity,
            "bar_color":     list(s.bar_color),
            "text_color":    list(s.text_color),
            "text_stroke": {
                "width": s.text_stroke.width,
                "color": list(s.text_stroke.color),
            },
            "font_size":     s.font_size,
            "padding_ratio": s.padding_ratio,
            "position":      s.position,
        }
        for name, s in cfg().presets.items()
    }


@app.get("/api/integrations")
async def integrations_info() -> dict:
    return {
        "flickr": bool(cfg().integrations.flickr_api_key),
        "dvids":  bool(cfg().integrations.dvids_api_key),
    }


@app.get("/api/version")
async def version_info() -> dict:
    return {"version": _app_version()}


class FlickrMetaRequest(BaseModel):
    photo_id: str


@app.post("/flickr-meta")
@limiter.limit("30/minute")
async def flickr_meta(request: Request, body: FlickrMetaRequest) -> dict:
    key = cfg().integrations.flickr_api_key
    if not key:
        raise HTTPException(503, "Flickr API key not configured")
    photo_id = body.photo_id.strip()
    if len(photo_id) > MAX_ID_LEN or not photo_id.isdigit():
        raise HTTPException(422, "Invalid Flickr photo ID")

    params = urlencode({
        "method": "flickr.photos.getInfo",
        "api_key": key,
        "photo_id": photo_id,
        "format": "json",
        "nojsoncallback": "1",
    })
    api_url = f"https://api.flickr.com/services/rest/?{params}"
    try:
        req = urllib.request.Request(api_url, headers={"User-Agent": "Lizenztool/1.0"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read())
    except Exception as exc:
        logger.error("Flickr API error: %s", exc)
        raise HTTPException(502, "Flickr API unreachable") from exc

    if data.get("stat") != "ok":
        logger.warning("Flickr API returned error: %s", data.get("message"))
        raise HTTPException(502, "Flickr API unreachable")

    photo = data["photo"]
    owner = photo.get("owner", {})
    author = owner.get("realname") or owner.get("username", "")
    license_id = str(photo.get("license", "")).strip()

    # Resolve the ID through Flickr's own license list. An unknown ID or a failed
    # lookup must NOT fall back to "All Rights Reserved" or to any CC license —
    # the missing information is handed to the UI instead.
    official_name = license_url = ""
    try:
        official_name, license_url = _flickr_license_table(key)[license_id]
    except (KeyError, OSError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        logger.warning("Flickr license unresolved for id %r: %s", _safe_log(license_id), exc)

    # Prefer the exact short code encoded in the license URL (e.g. "CC BY 2.0");
    # otherwise keep Flickr's official wording verbatim.
    license_name = _cc_label_from_url(license_url) or official_name

    date_taken = photo.get("dates", {}).get("taken", "")
    year = date_taken[:4] if date_taken else ""

    return {
        "author": author,
        "year": year,
        "license": license_name,
        "license_url": license_url,
        "license_id": license_id,
        "license_name_official": official_name,
        "rights_check_required": not license_name,
    }


class DvidsMetaRequest(BaseModel):
    asset_id: str


@app.post("/dvids-meta")
@limiter.limit("30/minute")
async def dvids_meta(request: Request, body: DvidsMetaRequest) -> dict:
    key = cfg().integrations.dvids_api_key
    if not key:
        raise HTTPException(503, "DVIDS API key not configured")
    asset_id = body.asset_id.strip()
    if len(asset_id) > MAX_ID_LEN or not asset_id.isdigit():
        raise HTTPException(422, "Invalid DVIDS asset ID")

    api_url = (
        f"https://api.dvidshub.net/asset"
        f"?id=image:{asset_id}&api_key={key}&format=json"
    )
    try:
        req = urllib.request.Request(api_url, headers={"User-Agent": "Lizenztool/1.0"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read())
    except Exception as exc:
        logger.error("DVIDS API error: %s", exc)
        raise HTTPException(502, "DVIDS API unreachable") from exc

    credits = data.get("credit") or []
    if isinstance(credits, list) and credits:
        c = credits[0]
        rank = c.get("rank", "").strip()
        name = c.get("name", "").strip()
        author = f"{rank} {name}".strip() if rank else name
    else:
        author = ""

    date_raw = data.get("date", "")
    year = date_raw[:4] if date_raw else ""

    # The DVIDS asset API carries no per-asset copyright status. Most DVIDS
    # material is a U.S. Government work, but that is not guaranteed for every
    # asset (contractor, coalition-partner and third-party imagery appear too),
    # so no license is asserted here — the UI asks the user to check the notice.
    return {
        "author": author,
        "year": year,
        "license": "",
        "license_url": "",
        "rights_check_required": True,
        "source_url": str(data.get("url") or ""),
    }


@app.get("/", response_class=HTMLResponse)
async def index() -> str:
    return (_STATIC / "index.html").read_text()


@app.post("/fetch-url")
@limiter.limit("20/minute")
async def fetch_url(request: Request, body: FetchUrlRequest) -> Response:
    if len(body.url) > MAX_FETCH_URL_LEN:
        raise HTTPException(422, "URL too long")
    parsed = urlparse(body.url)
    if parsed.scheme not in _ALLOWED_SCHEMES or not parsed.netloc:
        raise HTTPException(422, "Invalid URL")
    if _is_ssrf_target(parsed.hostname or ""):
        logger.warning("SSRF blocked: %s from %s", _safe_log(body.url), _client_ip(request))
        raise HTTPException(422, "URL unreachable")

    # _safe_opener repeats the address check at connect time and connects to the
    # address it just validated, so the pre-check above is a fast rejection path
    # rather than the only line of defence. Redirect targets are validated too.
    try:
        req = urllib.request.Request(
            body.url,
            headers={"User-Agent": "Lizenztool/1.0"},
        )
        with _safe_opener.open(req, timeout=10) as resp:
            content_type = resp.headers.get_content_type()
            if content_type not in _ALLOWED_CONTENT_TYPES:
                raise HTTPException(415, f"URL does not provide a supported image format ({content_type})")
            data = resp.read(MAX_UPLOAD_BYTES + 1)
    except _SSRFBlockedError as exc:
        logger.warning("SSRF blocked: %s (%s) from %s", _safe_log(body.url), exc, _client_ip(request))
        raise HTTPException(422, "URL unreachable")
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("fetch-url failed for %s: %s", _safe_log(body.url), exc)
        raise HTTPException(502, "Could not load image") from exc

    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, f"File too large (max {MAX_UPLOAD_BYTES // 1024 // 1024} MB)")

    if not _detect_ext(data):
        raise HTTPException(415, "Not a valid image file")

    return Response(content=data, media_type=content_type)



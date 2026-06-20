import ipaddress
import json
import logging
import os
import re
import socket
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

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
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
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


def _is_ssrf_target(hostname: str) -> bool:
    try:
        ip = ipaddress.ip_address(socket.gethostbyname(hostname))
        return ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved
    except Exception:
        return True


class _SSRFBlockedError(Exception):
    pass


class _NoSSRFRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        parsed = urlparse(newurl)
        if _is_ssrf_target(parsed.hostname or ""):
            raise _SSRFBlockedError(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_safe_opener = urllib.request.build_opener(_NoSSRFRedirectHandler())


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


_ALLOWED_SCHEMES = {"http", "https"}
_ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png", "image/tiff", "image/webp"}


class FetchUrlRequest(BaseModel):
    url: str


_FLICKR_LICENSES: dict[str, str] = {
    "0": "All Rights Reserved",
    "1": "CC BY-NC-SA 4.0",
    "2": "CC BY-NC 4.0",
    "3": "CC BY-NC-ND 4.0",
    "4": "CC BY 4.0",
    "5": "CC BY-SA 4.0",
    "6": "CC BY-ND 4.0",
    "7": "CC0 1.0 (Public Domain)",
    "8": "CC0 1.0 (Public Domain)",
    "9": "CC0 1.0 (Public Domain)",
    "10": "CC0 1.0 (Public Domain)",
}


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
        }
        for name, s in cfg().presets.items()
    }


@app.get("/api/integrations")
async def integrations_info() -> dict:
    return {
        "flickr": bool(cfg().integrations.flickr_api_key),
        "dvids":  bool(cfg().integrations.dvids_api_key),
    }


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

    api_url = (
        f"https://api.flickr.com/services/rest/"
        f"?method=flickr.photos.getInfo&api_key={key}"
        f"&photo_id={photo_id}&format=json&nojsoncallback=1"
    )
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
    license_id = str(photo.get("license", "0"))
    license_name = _FLICKR_LICENSES.get(license_id, "All Rights Reserved")
    date_taken = photo.get("dates", {}).get("taken", "")
    year = date_taken[:4] if date_taken else ""

    return {"author": author, "year": year, "license": license_name}


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

    return {"author": author, "year": year, "license": "CC0 1.0 (Public Domain)"}


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
        logger.warning("SSRF blocked via redirect: %s from %s", exc, _client_ip(request))
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



# Lizenztool

Lizenztool adds a license overlay to images and optionally writes license metadata (EXIF/IPTC/XMP). It is available as both a **command-line tool** and a **web application**.

Supported formats: JPEG · PNG · WebP · TIFF (CLI only — the browser canvas has
no TIFF encoder, so the web UI refuses TIFF instead of silently exporting JPEG)

---

## Features

- Overlay with copyright holder, year, and license type (top or bottom)
- Reads existing EXIF/IPTC/XMP metadata and auto-fills fields
- Automatic metadata retrieval from **Flickr**, **DVIDS**, and **Wikimedia Commons**
- Removes EXIF data from output file (optional)
- Writes license information back as XMP/IPTC (optional)
- Three style presets (Standard, Minimal, Bold) plus custom configuration
- Web UI with live canvas preview
- Rate limiting and SSRF protection for public deployment

---

## License integrity

A license is legal information, so the tool never reinterprets one:

- **Versions are preserved.** `CC BY 2.0` stays `CC BY 2.0`, `CC BY-SA 3.0` stays
  `CC BY-SA 3.0`. Nothing is silently upgraded to 4.0. Licenses that are not in
  the dropdown are inserted into it verbatim, with their own URL.
- **`CC0 1.0` and `Public Domain` are separate states.** CC0 is an explicit
  rights waiver with its own deed URL; public domain is a legal status and gets
  no CC URL. Neither is ever mapped onto the other.
- **Flickr** license IDs are resolved through `flickr.photos.licenses.getInfo`,
  so the license and version come from Flickr itself, not a hardcoded table.
- **Wikimedia Commons** licenses are taken from the `LicenseShortName` and
  `LicenseUrl` fields exactly as returned.
- **DVIDS** exposes no per-asset rights status, so no license is assigned. The
  API returns `rights_check_required: true` and the UI asks you to check the
  rights notice of that specific asset.
- **Own photos** get no preselected license — the author decides.
- If a source gives no unambiguous license, the tool sets **no license** rather
  than guessing one (including never defaulting to `All Rights Reserved`).

---

## Security

- **SSRF protection** validates every A/AAAA record `socket.getaddrinfo()`
  returns for a host (IPv4 and IPv6), not just the first one, and blocks the
  whole host if any record is non-global. DNS failures and empty answers block
  too. The same check runs again on every redirect target, and redirects are
  restricted to `http`/`https`.
- The outbound HTTP client resolves each host once and connects to exactly the
  addresses that were validated (`_safe_create_connection`), closing the gap
  between the check and the connect for that request. This does **not** fully
  solve DNS rebinding: an attacker controlling DNS can still return a
  different, individually-valid answer on a later, separate request within the
  process's DNS cache TTL. See the docstring on `_resolve_global_addrinfo` in
  `lizenztool/api.py` for the exact boundary of what is and isn't covered.
- **Client IP / rate limiting**: the app never reads `X-Forwarded-For` itself —
  it uses `request.client.host`, which uvicorn rewrites from that header only
  for peers listed in `--forwarded-allow-ips`. Reading the header directly
  would let any client reset its own rate-limit bucket by sending a fake value.
- **Proxy trust** defaults to loopback only (`FORWARDED_ALLOW_IPS=127.0.0.1` in
  the Dockerfile, uvicorn's own default). The bundled `docker-compose.yml`
  puts Caddy and the app on a fixed-subnet network and sets
  `FORWARDED_ALLOW_IPS` to that subnet, since Caddy reaches the app over the
  Docker network rather than loopback. On Railway or another PaaS, the
  platform's edge proxy must be configured to pass a trustworthy
  `X-Forwarded-For` in the first place — this setting only decides whether
  uvicorn believes it once it arrives, so verify your platform's setup before
  relying on `request.client.host` for anything security-sensitive.

---

## Requirements

- Python 3.11 or newer
- [ExifTool](https://exiftool.org/) (for EXIF read/write/strip)

```bash
# Debian / Ubuntu
sudo apt install libimage-exiftool-perl

# macOS
brew install exiftool
```

---

## Installation

### As Python Package

```bash
git clone https://github.com/rothtor/lizenztool.git
cd lizenztool
pip install .
```

This installs the `lizenztool` CLI command and the FastAPI server.

### With uv (Recommended)

```bash
uv sync
uv run lizenztool --help
```

---

## CLI Usage

```bash
# Process single image (interactive)
lizenztool image.jpg

# Process multiple images to separate directory
lizenztool *.jpg --output-dir ./output/

# Batch mode: apply same license to all images (confirm once)
lizenztool *.jpg --batch

# Preview only, do not save
lizenztool image.jpg --dry-run

# Custom config file
lizenztool image.jpg --config /path/to/config.toml
```

License information is requested interactively. If metadata already exists in the image, fields are pre-filled.

---

## Web Application

### Development

```bash
uvicorn lizenztool.api:app --reload
```

The interface is available at [http://localhost:8000](http://localhost:8000).

### Docker

```bash
# Build image
docker build -t lizenztool .

# Start (Caddy as reverse proxy on port 8080)
docker compose up -d
```

For public deployment, replace `:8080` with your own domain name in the `Caddyfile` — Caddy will then automatically obtain a Let's Encrypt certificate and enable HTTPS. Afterwards, uncomment the HSTS line in the `Caddyfile`.

#### Environment Variables

| Variable | Default | Description |
|---|---|---|
| `MAX_UPLOAD_MB` | `20` | Maximum upload size in MB |
| `LOG_LEVEL` | `INFO` | Log level (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |

---

## Configuration

The configuration file `lizenztool.toml` is looked up automatically:

1. `./lizenztool.toml` (current directory / Docker mount)
2. `~/.config/lizenztool/config.toml`

```toml
[style]
position    = "bottom"   # "top" or "bottom"
bar_opacity = 200        # 0–255
bar_color   = [0, 0, 0]
text_color  = [255, 255, 255]
bar_ratio   = 0.06       # bar height as fraction of image height
font_size   = 0          # 0 = proportional to bar height

[output]
strip_exif         = true   # remove EXIF from output
write_license_meta = false  # write license back as XMP/IPTC
filename_pattern   = "img_{date}-{time}-{n}"  # {date}=YYYYMMDD, {time}=HHMM, {n}=counter
```

`{n}` is a sequential counter within the run (1, 2, 3, …), zero-padded to the
width of the batch size. Regardless of the pattern, an existing file is never
overwritten — a numeric suffix is appended on collision, so a constant pattern
such as `filename_pattern = "fixed"` produces `fixed.jpg`, `fixed-2.jpg`,
`fixed-3.jpg` rather than one repeatedly overwritten file.

```toml
[integrations]
# flickr_api_key = "..."
# dvids_api_key  = "..."

[presets.dark]
bar_color   = [30, 30, 30]
bar_opacity = 230
bar_ratio   = 0.07
```

The configuration file is automatically reloaded at runtime when it changes on the filesystem.

### Flickr Integration

1. Request a free API key at [flickr.com/services/apps/create](https://www.flickr.com/services/apps/create/)
2. Add `flickr_api_key` to `lizenztool.toml`
3. When loading a Flickr URL, author, year, and license are filled in automatically

### DVIDS Integration

1. Request an API key at [api.dvidshub.net](https://api.dvidshub.net/)
2. Add `dvids_api_key` to `lizenztool.toml`

---

## Development

```bash
# Install dependencies (including test tools)
pip install -e ".[dev]"

# Check types
mypy lizenztool/

# Syntax check
python -m py_compile lizenztool/*.py
```

### Testing

The project includes a comprehensive test suite covering API endpoints, configuration parsing, metadata extraction, and security.

#### Install Test Dependencies

```bash
pip install -e ".[dev]"
```

This installs:
- **pytest** (test runner)
- **pytest-cov** (coverage reporting)
- **httpx** (async HTTP client for FastAPI TestClient)

```bash
# Run all tests with summary
pytest tests/

# Run with verbose output
pytest tests/ -v

# Run with coverage report
pytest tests/ --cov=lizenztool --cov-report=term-missing
```

Current coverage:
- **API module**: 90% (186 statements)
- **Config module**: 100% (dataclass parsing tested)
- **Metadata module**: 70% (CLI-only functions excluded)

Run coverage report:
```bash
pytest tests/ --cov=lizenztool --cov-report=html
open htmlcov/index.html
```

---

## Supported License Types

| License | Description |
|---|---|
| CC0 1.0 | Public Domain |

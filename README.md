# License Tool

License Tool adds a license overlay to images and optionally writes license metadata (EXIF/IPTC/XMP). It is available as both a **command-line tool** and a **web application**.

Supported formats: JPEG · PNG · TIFF · WebP

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
git clone https://github.com/rothtor/license-tool.git
cd license-tool
pip install .
```

This installs the `license-tool` CLI command and the FastAPI server.

### With uv (Recommended)

```bash
uv sync
uv run license-tool --help
```

---

## CLI Usage

```bash
# Process single image (interactive)
license-tool image.jpg

# Process multiple images to separate directory
license-tool *.jpg --output-dir ./output/

# Batch mode: apply same license to all images (confirm once)
license-tool *.jpg --batch

# Preview only, do not save
license-tool image.jpg --dry-run

# Custom config file
license-tool image.jpg --config /path/to/config.toml
```

License information is requested interactively. If metadata already exists in the image, fields are pre-filled.

---

## Web Application

### Development / Local Start

```bash
uvicorn license_tool.api:app --reload
```

The interface is available at [http://localhost:8000](http://localhost:8000).

### Docker Compose (Production)

```bash
# Build image
docker build -t license-tool .

# Start (Caddy as reverse proxy on port 8080)
docker compose up -d
```

Für den öffentlichen Betrieb in `Caddyfile` `:8080` durch den eigenen Domainnamen ersetzen — Caddy bezieht dann automatisch ein Let's-Encrypt-Zertifikat und aktiviert HTTPS. Anschließend die HSTS-Zeile in der `Caddyfile` einkommentieren.

#### Umgebungsvariablen

| Variable | Standard | Beschreibung |
|---|---|---|
| `MAX_UPLOAD_MB` | `20` | Maximale Upload-Größe in MB |
| `LOG_LEVEL` | `INFO` | Log-Ebene (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |

---

## Konfiguration

Die Konfigurationsdatei `lizenztool.toml` wird automatisch gesucht:

1. `./lizenztool.toml` (aktuelles Verzeichnis / Docker-Mount)
2. `~/.config/lizenztool/config.toml`

```toml
[style]
position    = "bottom"   # "top" oder "bottom"
bar_opacity = 200        # 0–255
bar_color   = [0, 0, 0]
text_color  = [255, 255, 255]
bar_ratio   = 0.06       # Balkenhöhe als Anteil der Bildhöhe
font_size   = 0          # 0 = proportional zur Balkenhöhe

[output]
strip_exif         = true   # EXIF aus Ausgabe entfernen
write_license_meta = false  # Lizenz als XMP/IPTC zurückschreiben
filename_pattern   = "img_{date}-{time}"  # {date}, {time}, {n}

[integrations]
# flickr_api_key = "..."
# dvids_api_key  = "..."

[presets.dunkel]
bar_color   = [30, 30, 30]
bar_opacity = 230
bar_ratio   = 0.07
```

Die Konfigurationsdatei wird im laufenden Betrieb automatisch neu geladen, wenn sie auf dem Dateisystem geändert wird.

### Flickr-Integration

1. Kostenlosen API-Schlüssel unter [flickr.com/services/apps/create](https://www.flickr.com/services/apps/create/) beantragen
2. `flickr_api_key` in `lizenztool.toml` eintragen
3. Beim Laden einer Flickr-URL werden Autor, Jahr und Lizenz automatisch ausgefüllt

### DVIDS-Integration

1. API-Schlüssel unter [api.dvidshub.net](https://api.dvidshub.net/) beantragen
2. `dvids_api_key` in `lizenztool.toml` eintragen

---

## Entwicklung

```bash
# Abhängigkeiten installieren
pip install -e ".[dev]"

# Typen prüfen
mypy lizenztool/

# Syntax-Check
python -m py_compile lizenztool/*.py
```

---

## Unterstützte Lizenztypen

| Lizenz | Beschreibung |
|---|---|
| CC0 1.0 | Gemeinfrei |

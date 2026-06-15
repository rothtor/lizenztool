# Lizenztool

Lizenztool fügt Bildern ein Lizenz-Overlay hinzu und schreibt optional Lizenzmetadaten (EXIF/IPTC/XMP). Es steht als **Kommandozeilen-Werkzeug** und als **Web-Anwendung** zur Verfügung.

Unterstützte Formate: JPEG · PNG · TIFF · WebP

---

## Funktionen

- Overlay mit Copyright-Inhaber, Jahr und Lizenztyp (oben oder unten)
- Liest vorhandene EXIF/IPTC/XMP-Metadaten aus und befüllt die Felder automatisch
- Automatischer Abruf von Metadaten von **Flickr**, **DVIDS** und **Wikimedia Commons**
- Entfernt EXIF-Daten aus der Ausgabedatei (optional)
- Schreibt Lizenzinformationen als XMP/IPTC zurück (optional)
- Drei Stil-Presets (Standard, Minimal, Kräftig) sowie eigene Konfiguration
- Web-UI mit Live-Vorschau im Canvas
- Rate Limiting und SSRF-Schutz für den öffentlichen Betrieb

---

## Voraussetzungen

- Python 3.11 oder neuer
- [ExifTool](https://exiftool.org/) (für EXIF-Lesen/-Schreiben/-Entfernen)

```bash
# Debian / Ubuntu
sudo apt install libimage-exiftool-perl

# macOS
brew install exiftool
```

---

## Installation

### Als Python-Paket

```bash
git clone https://github.com/rothtor/lizenztool.git
cd lizenztool
pip install .
```

Das installiert den CLI-Befehl `lizenztool` und den FastAPI-Server.

### Mit uv (empfohlen)

```bash
uv sync
uv run lizenztool --help
```

---

## CLI-Nutzung

```bash
# Einzelnes Bild verarbeiten (interaktive Eingabe)
lizenztool bild.jpg

# Mehrere Bilder, Ausgabe in separates Verzeichnis
lizenztool *.jpg --output-dir ./ausgabe/

# Batch-Modus: gleiche Lizenz für alle Bilder (einmalige Eingabe)
lizenztool *.jpg --batch

# Vorschau ohne Speichern
lizenztool bild.jpg --dry-run

# Eigene Konfigurationsdatei
lizenztool bild.jpg --config /pfad/zur/config.toml
```

Die Lizenzinformationen werden interaktiv abgefragt. Sind bereits Metadaten im Bild vorhanden, werden sie vorausgefüllt.

---

## Web-Anwendung

### Entwicklung / lokaler Start

```bash
uvicorn lizenztool.api:app --reload
```

Die Oberfläche ist unter [http://localhost:8000](http://localhost:8000) erreichbar.

### Docker Compose (Produktion)

```bash
# Image bauen
docker build -t lizenztool .

# Starten (Caddy als Reverse Proxy auf Port 8080)
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

## Sicherheitshinweise (öffentlicher Betrieb)

- Port 8000 (App) **nicht** direkt nach außen öffnen — ausschließlich über den Caddy-Reverse-Proxy betreiben
- API-Schlüssel niemals im Docker-Image ablegen; ausschließlich über die gemountete `lizenztool.toml` übergeben
- Für TLS/HTTPS den Domainnamen in der `Caddyfile` eintragen und HSTS-Zeile einkommentieren
- Für reproduzierbare Builds Abhängigkeiten einfrieren: `pip-compile pyproject.toml` oder `uv lock`

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
| CC BY 4.0 | Namensnennung |
| CC BY-SA 4.0 | Namensnennung + Weitergabe unter gleicher Lizenz |
| CC BY-NC 4.0 | Namensnennung + nur nicht-kommerziell |
| CC BY-NC-SA 4.0 | Namensnennung + nicht-kommerziell + gleiche Lizenz |
| CC BY-ND 4.0 | Namensnennung + keine Bearbeitungen |
| CC BY-NC-ND 4.0 | Namensnennung + nicht-kommerziell + keine Bearbeitungen |
| CC0 1.0 | Gemeinfrei |
| All Rights Reserved | Alle Rechte vorbehalten |
| Eigene Lizenz | Beliebiger Text und URL |

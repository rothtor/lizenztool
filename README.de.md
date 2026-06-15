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

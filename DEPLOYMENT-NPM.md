# Deployment: Lizenztool auf meinedomain.com

Runbook für eine Debian-VM auf Proxmox hinter einem vorgelagerten
Nginx Proxy Manager (NPM). TLS und Domain macht die NPM, der Stack auf der
App-VM bleibt bei reinem HTTP auf Port 8080.

Geprüft gegen `caddy:2-alpine` (2.11.4) und uvicorn 0.49.

## Ausgangslage

Zwei getrennte Maschinen. Die Platzhalter tauchen in Caddyfile, Compose-Datei
und Firewall-Regel wieder auf — überall konsistent ersetzen.

| Rolle | Beispielwert | Bedeutung |
|---|---|---|
| Domain | `meinedomain.com` | A-Record zeigt auf die öffentliche IP der NPM-Maschine |
| NPM-VM | `10.0.0.5` | Nginx Proxy Manager, terminiert TLS |
| App-VM | `10.0.0.20` | Debian-VM mit Docker, hier läuft der Stack |
| Docker-Netz | `172.28.0.0/24` | festes Subnetz aus `docker-compose.yml` |
| Projektpfad | `/opt/lizenztool` | Ablage auf der App-VM |

Weg einer Anfrage:

```
Browser                NPM                  Caddy                 uvicorn
meinedomain.com  ──▶   10.0.0.5      ──▶    10.0.0.20:8080  ──▶   app:8000
:443 TLS               setzt XFF+XFP        Header + 25 MB        Rate-Limit pro IP
```

Jeder Hop muss dem vorherigen ausdrücklich vertrauen, sonst endet die
Besucher-IP unterwegs — Schritte 4 und 5 sind genau dafür da.

---

## 1 · DNS setzen

A-Record beim DNS-Anbieter anlegen. Ziel ist die **öffentliche IP der
NPM-Maschine**, nicht die der App-VM.

```
meinedomain.com.      A     203.0.113.10   # öffentliche IP von NPM
www.meinedomain.com.  CNAME meinedomain.com.
```

Vor Schritt 8 prüfen — sonst scheitert die Let's-Encrypt-Validierung:

```bash
dig +short meinedomain.com
```

## 2 · Docker auf der App-VM installieren

```bash
apt update && apt install -y ca-certificates curl git
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] \
https://download.docker.com/linux/debian $(. /etc/os-release && echo $VERSION_CODENAME) stable" \
  > /etc/apt/sources.list.d/docker.list
apt update && apt install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
```

Proxmox-Hinweis: In einem LXC-Container statt einer VM braucht Docker
zusätzliche Freigaben (nesting, keyctl). Für diesen Stack ist die VM der
ruhigere Weg.

## 3 · Projekt holen und Image bauen

```bash
git clone <repo-url> /opt/lizenztool
cd /opt/lizenztool
docker build -t lizenztool .
```

`lizenztool.toml` im Projektverzeichnis ist die Laufzeitkonfiguration. Sie wird
read-only in den Container gemountet und bei Änderung automatisch neu geladen —
kein Neustart nötig.

## 4 · Caddyfile: Domain draußen lassen, Proxys vertrauen

Zwei Änderungen gegenüber dem mitgelieferten Caddyfile:

1. Die Site-Adresse bleibt `:8080`. Trägst du hier `meinedomain.com` ein,
   versucht Caddy selbst ein Let's-Encrypt-Zertifikat auf Port 80/443 zu holen,
   die die NPM bereits belegt.
2. Der neue globale Block. Ohne ihn verwirft Caddy 2.7+ eingehende
   `X-Forwarded-*`-Header und ersetzt sie durch die IP des direkten Peers —
   alle Besucher landen dann im selben Rate-Limit-Bucket.

```caddyfile
{
	# Kein ACME hier — TLS macht die NPM.
	auto_https off

	# Ohne diesen Block ersetzt Caddy XFF durch die IP des direkten Peers.
	servers {
		trusted_proxies static 10.0.0.5/32 172.28.0.0/24
	}
}

:8080 {
	reverse_proxy app:8000

	request_body {
		max_size 25MB
	}

	header -Server
	header X-Content-Type-Options "nosniff"
	header X-Frame-Options "DENY"
	header Referrer-Policy "strict-origin-when-cross-origin"
	header Permissions-Policy "geolocation=(), microphone=(), camera=()"
	# HSTS bleibt aus — den Header setzt die NPM (Schritt 8).
	header Content-Security-Policy "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; connect-src 'self' https://commons.wikimedia.org; img-src 'self' blob: data:; frame-ancestors 'none'; form-action 'self'; object-src 'none'"
}
```

Syntax vor dem Start prüfen:

```bash
docker run --rm -v /opt/lizenztool/Caddyfile:/etc/caddy/Caddyfile:ro \
  caddy:2-alpine caddy validate --config /etc/caddy/Caddyfile
# → Valid configuration
```

> **Vorsicht:** `trusted_proxies` ist eine Vertrauensliste, keine Zugriffsliste.
> Dort gehören nur die NPM und das Docker-Subnetz hinein. Die Abkürzung
> `private_ranges` ist nur in Ordnung, wenn Port 8080 wirklich ausschließlich
> aus dem privaten Netz erreichbar ist (Schritt 6).

## 5 · Compose: Port binden und Proxy-Trust erweitern

uvicorn geht die XFF-Liste von rechts nach links durch und nimmt den ersten
Eintrag, der **nicht** in `FORWARDED_ALLOW_IPS` steht. Fehlt dort die
NPM-Adresse, gilt die NPM selbst als Besucher. Also Docker-Subnetz *und*
NPM-IP eintragen.

```yaml
services:
  app:
    image: lizenztool
    restart: unless-stopped
    environment:
      MAX_UPLOAD_MB: "20"
      LOG_LEVEL: "INFO"
      FORWARDED_ALLOW_IPS: "172.28.0.0/24,10.0.0.5"   # geändert
    volumes:
      - ./lizenztool.toml:/app/lizenztool.toml:ro
    expose:
      - "8000"
    networks:
      - internal

  caddy:
    image: caddy:2-alpine
    restart: unless-stopped
    ports:
      - "10.0.0.20:8080:8080"   # geändert: internes Interface statt 0.0.0.0
    volumes:
      - ./Caddyfile:/etc/caddy/Caddyfile:ro
      - caddy_data:/data
      - caddy_config:/config
    depends_on:
      - app
    networks:
      - internal
```

Die drei Größenlimits müssen zueinander passen, sonst bricht der Upload an der
engsten Stelle ab — oft mit einem nichtssagenden 413:

| Stelle | Wert | Fehler bei Überschreitung |
|---|---|---|
| NPM `client_max_body_size` | `25m` | nginx 413, Request erreicht Caddy nie |
| Caddy `request_body` | `25MB` | 413 von Caddy |
| App `MAX_UPLOAD_MB` | `20` | saubere Fehlermeldung in der UI |

Variante: Läuft die NPM als Container auf *derselben* VM, ist es sauberer, sie
ins Netz `internal` zu hängen, den `ports`-Block ganz zu streichen und als
Forward-Ziel `caddy` / `8080` einzutragen. Dann ist überhaupt kein Port
veröffentlicht.

## 6 · Port 8080 auf die NPM einschränken

Docker schreibt seine DNAT-Regeln an ufw vorbei — ein `ufw deny 8080` greift
für veröffentlichte Container-Ports schlicht nicht. Die Regel gehört in die
Kette `DOCKER-USER`:

```bash
apt install -y iptables-persistent
iptables -I DOCKER-USER -p tcp --dport 8080 ! -s 10.0.0.5 -j DROP
netfilter-persistent save
```

Gegenprobe: von einer dritten Maschine muss `curl -m 5 http://10.0.0.20:8080/`
in einen Timeout laufen, von der NPM-VM aus dieselbe Anfrage HTML liefern.

## 7 · Stack starten

```bash
cd /opt/lizenztool
docker compose up -d
docker compose ps
curl -sI http://10.0.0.20:8080/ | head -n 1   # → HTTP/1.1 200 OK
```

## 8 · Proxy Host in der NPM anlegen

Hosts → Proxy Hosts → Add Proxy Host:

| Feld | Wert | Warum |
|---|---|---|
| Domain Names | `meinedomain.com` | ggf. zusätzlich `www.meinedomain.com` |
| Scheme | `http` | Caddy spricht intern kein TLS |
| Forward Hostname / IP | `10.0.0.20` | App-VM |
| Forward Port | `8080` | Caddy |
| Cache Assets | aus | Antworten sind nutzerspezifisch |
| Block Common Exploits | an | schadet nicht |
| Websockets Support | aus | die App nutzt keine |
| SSL Certificate | Request a new certificate | Let's Encrypt über die NPM |
| Force SSL · HTTP/2 | an | — |
| HSTS Enabled | an | genau eine Quelle für den Header: die NPM kennt das öffentliche Schema |

Reiter *Advanced*:

```nginx
client_max_body_size 25m;
proxy_read_timeout 120s;
proxy_send_timeout 120s;
```

Zum XFF-Header: Die Standardvorlage der NPM setzt
`X-Forwarded-For $proxy_add_x_forwarded_for;`, hängt die Client-IP also an einen
mitgeschickten Header an. Das ist hier unkritisch — uvicorn wertet von rechts
aus und ignoriert alles links der echten IP. Eingreifen musst du nur, wenn
*vor* der NPM noch ein CDN sitzt; dann gehört dessen Adressbereich zusätzlich
in `FORWARDED_ALLOW_IPS`.

---

## Abnahme

### 1 · Header und TLS

```bash
curl -sI https://meinedomain.com/ | grep -iE 'HTTP/|content-security|strict-transport|x-frame'
```

Erwartet: `HTTP/2 200`, die CSP aus dem Caddyfile, genau **eine**
`strict-transport-security`-Zeile. Zwei davon heißt: HSTS ist sowohl in der NPM
als auch im Caddyfile aktiv — eine Stelle abschalten.

### 2 · Echte Besucher-IP (die wichtige Prüfung)

Auf der App-VM mitlesen und währenddessen die Seite vom Handy im Mobilfunknetz
aufrufen:

```bash
docker compose logs -f app | grep -v /static
```

In der Zugriffszeile muss die öffentliche IP des Handys stehen. Steht dort
`172.28.0.1` oder `10.0.0.5`, greift die Kette nicht — dann teilen sich alle
Besucher ein einziges Rate-Limit-Kontingent (20–30 Anfragen pro Minute für
*alle zusammen*). Ursache ist fast immer ein fehlender
`trusted_proxies`-Block oder eine nicht eingetragene NPM-IP.

### 3 · Upload in voller Größe

Ein Bild nahe 20 MB durch die Oberfläche schicken. Ein 413 *vor* dem
Fortschrittsbalken kommt von nginx, ein 413 danach von Caddy — siehe die
Limit-Tabelle in Schritt 5.

---

## Wenn etwas klemmt

| Symptom | Ursache | Behebung |
|---|---|---|
| NPM zeigt `502 Bad Gateway` | Caddy nicht erreichbar oder DOCKER-USER-Regel zu streng | `docker compose ps`; von der NPM-VM `curl 10.0.0.20:8080` |
| Zertifikatsanforderung schlägt fehl | A-Record zeigt nicht auf die NPM, oder Port 80 ist von außen dicht | `dig +short meinedomain.com`; Port 80 auf der NPM öffnen |
| Caddy-Log meldet ACME-Fehler | Domain steht doch im Caddyfile | Site-Adresse zurück auf `:8080` |
| Alle Nutzer bekommen 429 | Client-IP kommt nicht durch | Abnahme 2; `trusted_proxies` und `FORWARDED_ALLOW_IPS` prüfen |
| 413 bei großen Bildern | `client_max_body_size` in der NPM nicht gesetzt | Advanced-Feld, Schritt 8 |
| Seite lädt ohne Styles | CSP durch eine zweite Quelle überschrieben | CSP nur im Caddyfile setzen, nicht zusätzlich in der NPM |

## Betrieb

```bash
cd /opt/lizenztool

# Update einspielen
git pull && docker build -t lizenztool . && docker compose up -d

# Logs
docker compose logs -f --tail=100 app
docker compose logs -f --tail=100 caddy

# Konfiguration ändern — kein Neustart nötig
$EDITOR lizenztool.toml

# Sichern: reicht für ein vollständiges Wiederaufsetzen
tar czf lizenztool-backup.tgz Caddyfile docker-compose.yml lizenztool.toml
```

Alte Images gelegentlich mit `docker image prune -f` aufräumen. Die Volumes
`caddy_data` und `caddy_config` enthalten in diesem Aufbau keine Zertifikate —
die liegen bei der NPM.
